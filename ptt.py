"""
PTT 股票版「盤中閒聊」「盤後閒聊」情緒分析。
  盤中閒聊（D 日）→ D 日日盤的情緒
  盤後閒聊（D 日）→ 夜盤＋美股，代表對下一個交易日的看法
做法：每則推文用關鍵字權重打分（含嘲笑空軍/多軍、否定詞），整天加總換算成 -100（極度恐慌）～ +100（極度貪婪）。
只存推文內容與時間，不存帳號。
"""
import datetime as dt
import json
import re
import time
from collections import Counter

import requests

from data import connect

BASE_URL = "https://www.ptt.cc"
HEADERS = {"User-Agent": "Mozilla/5.0", "Cookie": "over18=1"}
KINDS = {"盤中閒聊": "intra", "盤後閒聊": "after"}

# ---------------- 權重表（之後要調整就改這裡）----------------
# 特殊句型（優先比對；比對到的文字不會再被單字重複計分）
PATTERNS = [
    # 許願式：「可不可以噴一下」「拜託噴」「好想要爆噴」→ 代表現在正在跌，偏空
    (r"(可不可以|可以不可以|能不能|拜託|求求?|快點?|好想要?|希望|給我|趕快|快給我).{0,5}(大?爆?噴|漲|反彈|拉|[Vv]+)", -1.5, "許願反彈"),
    (r"[Vv]{3,}|[Vv]轉", 2, "V轉"),       # 「VVVVV」＝正在反彈
    (r"[Aa]{3,}|[Aa]轉", -2, "A轉"),      # 「AAAA」＝正在下跌
    (r"空軍.{0,4}(哭|死|慘|畢業|爆|被軋|被嘎|出來|在哪|面對|燒|斷頭|住公園|跪|崩潰|GG)", 3, "嘲笑空軍"),
    (r"(軋|嘎)空", 3, "軋空"),
    (r"多軍.{0,4}(哭|死|慘|畢業|住公園|斷頭|被套|被割|跪|崩潰|GG)", -3, "嘲笑多軍"),
    (r"台股.{0,2}世界強", 3, "台股世界強"),
    (r"(做空|放空|空單|買權證空|空軍).{0,6}(發財|賺|噴|爽|數錢)", -2, "看空賺錢"),
    (r"GG\s*(了|惹|啦|囉|掉)", -3, "GG了"),   # 股票版的「GG」常指台積電，只有「GG了」才算完蛋
]
WORDS = {
    # 強烈偏多 +3
    "大爆噴": 3, "噴爆": 3, "爆噴": 3, "漲停": 3, "數錢": 3, "賺爛": 3, "財富自由": 3, "歐印": 3, "發財": 2.5,
    # 明確偏多 +2
    "大漲": 2, "噴出": 2, "噴": 2, "飆": 2, "起飛": 2, "火箭": 2, "創高": 2, "新高": 2, "多頭": 2, "印鈔": 2,
    "買爆": 2, "加碼": 2, "滿倉": 2, "紅通通": 2, "強勢": 1.5, "爽": 1.5, "賺": 1.5,
    # 輕微偏多 +1
    "上車": 1, "抄底": 1, "反彈": 1, "撐住": 1, "抱緊": 1, "穩": 0.5, "漲": 1, "紅": 0.5, "多單": 1, "吃飽": 1,
    # 強烈偏空 -3
    "大爆崩": -3, "爆崩": -3, "大崩": -3, "崩盤": -3, "跌停": -3, "暴跌": -3, "血洗": -3, "血流成河": -3, "畢業": -3, "斷頭": -3, "追繳": -3,
    "救命": -3, "完了": -3, "完蛋": -3, "逃命": -3, "快逃": -3,
    # 明確偏空 -2
    "崩": -2, "大跌": -2, "下殺": -2, "殺盤": -2, "破底": -2, "公園": -2, "慘": -2, "套牢": -2, "被套": -2, "套房": -2,
    "停損": -2, "割肉": -2, "認賠": -2, "出貨": -2, "倒貨": -2, "綠油油": -2, "恐慌": -2, "嚇死": -2, "賠": -1.5, "虧": -1.5,
    # 輕微偏空 -1
    "跌": -1, "哭": -1, "怕": -1, "觀望": -1, "減碼": -1, "韭菜": -1, "放空": -1, "空單": -1, "綠": -0.5, "修正": -1,
}
NEGATORS = "不沒別免無非"
# 長的詞先比對（「大崩」先於「崩」）
_WORD_RE = re.compile("|".join(re.escape(w) for w in sorted(WORDS, key=len, reverse=True)))


# ---------------- 個股／美股／題材股：不代表大盤情緒，權重打折 ----------------
STOCK_FACTOR = 0.3
MARKET_WORDS = re.compile(r"大盤|台股|加權|指數|台指|期指|鬼指|盤勢|美股|那斯達克|那指|費半|道瓊|台積|GG|2330|TSM|台崩電|護國神山")
US_STOCKS = ["特斯拉", "輝達", "蘋果", "超微", "英特爾", "美光", "博通", "微軟", "谷歌", "亞馬遜", "臉書", "高通", "甲骨文",
             "TSLA", "NVDA", "AAPL", "AMD", "INTC", "MU", "AVGO", "MSFT", "GOOG", "AMZN", "META", "SMCI", "ARM", "PLTR"]
_THEME_RE = re.compile(r"[\u4e00-\u9fff]{1,4}股(?<!台股)(?<!美股)(?<!陸股)(?<!港股)(?<!日股)(?<!韓股)(?<!歐股)|個股|\b\d{4}\b")
_STOCK_RE = None
COMMON_WORD_NAMES = {"大同", "統一", "中華", "台灣", "國泰", "富邦", "中信", "大成", "亞洲", "世界", "全新", "聯合", "新光",
                     "遠東", "光明", "正新", "美德", "永豐", "東元", "長興", "大亞", "精華", "大眾", "中興", "華新", "新產", "宏達",
                     "神達", "日勝", "興富", "名軒", "合一", "大魯閣", "一零四", "力積", "大學", "第一", "開發", "全國", "神基"}


def _stock_re():
    """資料庫裡所有上市櫃股票名稱（去掉跟日常用語撞名的）"""
    global _STOCK_RE
    if _STOCK_RE is None:
        try:
            con = connect()
            names = {r[0].strip().replace("*", "").replace("-KY", "") for r in con.execute(
                "SELECT DISTINCT name FROM prices WHERE date >= date('now', '-30 day') AND length(code) = 4")}
            con.close()
        except Exception:
            names = set()
        names = {n for n in names if len(n) >= 2 and n not in COMMON_WORD_NAMES} | set(US_STOCKS)
        _STOCK_RE = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.I) if names else re.compile("(?!)")
    return _STOCK_RE


def about_stock(text):
    """這則推文是在講個股／美股／題材股（而且沒有提到大盤或台積電）"""
    if MARKET_WORDS.search(text):
        return None
    m = _THEME_RE.search(text) or _stock_re().search(text)
    return m.group(0) if m else None


def score_text(text):
    """回傳 (分數, [(命中的詞, 權重), ...])；單則推文分數上限 ±6；講個股的推文分數 ×0.3"""
    s = text
    hits = []
    for pat, w, name in PATTERNS:
        for m in re.finditer(pat, s, re.I):
            hits.append((name, w))
        s = re.sub(pat, lambda m: "　" * len(m.group(0)), s, flags=re.I)   # 遮掉，避免「空軍哭」又被「哭」扣分
    for m in _WORD_RE.finditer(s):
        w = m.group(0)
        weight = WORDS.get(w, 0)
        if any(c in NEGATORS for c in s[max(0, m.start() - 2):m.start()]):   # 「不會崩」「沒在怕」→ 反轉減半
            weight = -weight * 0.5
            w = "（否定）" + w
        hits.append((w, weight))
    total = max(-6.0, min(6.0, sum(x for _, x in hits)))
    stock = about_stock(text) if hits else None
    if stock:
        total = round(total * STOCK_FACTOR, 2)
        hits = hits + [(f"（講個股：{stock}，整則 ×{STOCK_FACTOR}）", 0)]   # 關鍵字權重保持原值，只有整則分數打折
    return total, hits


# ---------------- 抓文章 ----------------
def _get(url, params=None):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        time.sleep(3 * (attempt + 1))
    return None


def find_posts(since: dt.date, max_pages=12):
    """搜尋盤中/盤後閒聊文章 → {(日期, kind): url}"""
    out = {}
    for title, kind in KINDS.items():
        for page in range(1, max_pages + 1):
            html = _get(f"{BASE_URL}/bbs/Stock/search", {"q": title, "page": page})
            if not html:
                break
            items = re.findall(r'<div class="title">\s*<a href="([^"]+)">([^<]+)</a>', html)
            if not items:
                break
            oldest = None
            for href, t in items:
                m = re.match(r"\s*\[閒聊\]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*" + title, t)
                if not m:
                    continue
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                oldest = d if oldest is None or d < oldest else oldest
                if d >= since:
                    out.setdefault((d.isoformat(), kind), href)
            if oldest and oldest < since:
                break
            time.sleep(0.8)
    return out


def fetch_pushes(href, post_date: dt.date):
    """抓整篇推文 → [(tag, 內容, 'YYYY-MM-DD HH:MM'), ...]"""
    html = _get(BASE_URL + href)
    if not html:
        return None
    raw = re.findall(r'<span class="[^"]*push-tag">([^<]+)</span><span class="[^"]*push-userid">[^<]*</span>'
                     r'<span class="[^"]*push-content">([^<]*)</span><span class="push-ipdatetime">([^<]*)</span>', html)
    out = []
    for tag, content, ipdt in raw:
        m = re.search(r"(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", ipdt)
        if not m:
            continue
        mo, d, hh, mm = map(int, m.groups())
        year = post_date.year + (1 if mo < post_date.month - 6 else 0)      # 跨年
        content = re.sub(r"^:\s*", "", content).strip()
        content = content.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").replace("&#34;", '"').replace("&#39;", "'")
        out.append((tag.strip(), content, f"{year:04d}-{mo:02d}-{d:02d} {hh:02d}:{mm:02d}"))
    return out


# ---------------- 資料庫 ----------------
def _init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS ptt_post(date TEXT, kind TEXT, url TEXT, fetched TEXT, n INTEGER,
                   PRIMARY KEY(date, kind))""")
    con.execute("CREATE TABLE IF NOT EXISTS ptt_push(date TEXT, kind TEXT, i INTEGER, tag TEXT, content TEXT, t TEXT, PRIMARY KEY(date, kind, i))")
    con.execute("CREATE TABLE IF NOT EXISTS taiex(date TEXT PRIMARY KEY, close REAL, chg REAL)")


def update(since: dt.date, refetch_recent_days=1, progress=None):
    """抓 since 之後的文章。已抓過的舊文章不重抓；最近 refetch_recent_days 天（含今天）一律重抓（推文還在增加）"""
    progress = progress if progress is not None else {}
    con = connect()
    _init(con)
    progress["msg"] = "搜尋 PTT 文章…"
    posts = find_posts(since)
    have = {(r[0], r[1]) for r in con.execute("SELECT date, kind FROM ptt_post")}
    recent = (dt.date.today() - dt.timedelta(days=refetch_recent_days + 1)).isoformat()
    todo = sorted([(k, v) for k, v in posts.items() if k not in have or k[0] >= recent], reverse=True)
    for n, ((d, kind), href) in enumerate(todo, 1):
        progress["msg"] = f"抓推文 {d} {'盤中' if kind == 'intra' else '盤後'}（{n}/{len(todo)}）"
        pushes = fetch_pushes(href, dt.date.fromisoformat(d))
        if pushes is None:
            continue
        con.execute("DELETE FROM ptt_push WHERE date=? AND kind=?", (d, kind))
        con.executemany("INSERT INTO ptt_push VALUES(?,?,?,?,?,?)", [(d, kind, i, *p) for i, p in enumerate(pushes)])
        con.execute("INSERT OR REPLACE INTO ptt_post VALUES(?,?,?,?,?)",
                    (d, kind, href, dt.datetime.now().strftime("%Y-%m-%d %H:%M"), len(pushes)))
        con.commit()
        time.sleep(1.0)
    progress["msg"] = "抓加權指數…"
    update_taiex(con, since)
    con.close()
    progress["msg"] = "完成"
    return len(todo)


def update_taiex(con, since: dt.date):
    """加權指數：收盤/漲跌（FMTQIK）＋ 開高低收（MI_5MINS_HIST）＋ 成交金額。至少抓到 2025/1 讓 MACD 有足夠暖身"""
    con.execute("CREATE TABLE IF NOT EXISTS taiex_k(date TEXT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, amount REAL)")
    have = con.execute("SELECT MIN(date) FROM taiex_k").fetchone()[0]
    start = min(since, dt.date(2025, 1, 1)) if not have or have > "2025-01-31" else since
    d = dt.date(start.year, start.month, 1)
    num = lambda x: float(str(x).replace(",", ""))
    while d <= dt.date.today():
        amt = {}
        try:
            j = json.loads(_get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK", {"date": d.strftime("%Y%m01"), "response": "json"}) or "{}")
            for r in j.get("data", []):
                y, m, dd = r[0].split("/")
                day = f"{int(y) + 1911}-{m}-{dd}"
                con.execute("INSERT OR REPLACE INTO taiex VALUES(?,?,?)", (day, num(r[4]), num(r[5])))
                amt[day] = num(r[2])
            time.sleep(1.2)
            j = json.loads(_get("https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST", {"date": d.strftime("%Y%m01"), "response": "json"}) or "{}")
            for r in j.get("data", []):
                y, m, dd = r[0].split("/")
                day = f"{int(y) + 1911}-{m}-{dd}"
                con.execute("INSERT OR REPLACE INTO taiex_k VALUES(?,?,?,?,?,?)",
                            (day, num(r[1]), num(r[2]), num(r[3]), num(r[4]), amt.get(day, 0)))
        except Exception:
            pass
        con.commit()
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        time.sleep(1.2)


def rebound_stats(days, closes):
    """恐慌到什麼程度、連續幾天，容易反彈？ closes：{日期: 加權收盤}"""
    tdays = sorted(closes)
    pos = {d: i for i, d in enumerate(tdays)}

    def fwd(d, k):
        i = pos.get(d)
        return closes[tdays[i + k]] / closes[d] - 1 if i is not None and i + k < len(tdays) else None

    rows = [r for r in days if r["date"] in pos]
    out = {"thresholds": [], "streaks": [], "lows": [], "highs": []}

    def agg(sel):
        r1 = [fwd(r["date"], 1) for r in sel]; r1 = [x for x in r1 if x is not None]
        r3 = [fwd(r["date"], 3) for r in sel]; r3 = [x for x in r3 if x is not None]
        r5 = [fwd(r["date"], 5) for r in sel]; r5 = [x for x in r5 if x is not None]
        m = lambda v: round(sum(v) / len(v) * 100, 2) if v else None
        return {"n": len(sel), "up1": round(sum(x > 0 for x in r1) / len(r1) * 100) if r1 else None,
                "r1": m(r1), "r3": m(r3), "up3": round(sum(x > 0 for x in r3) / len(r3) * 100) if r3 else None, "r5": m(r5)}

    # 1. 恐慌門檻：分數低於多少
    for kind in ("intra", "after"):
        for thr in (-20, -30, -40, -50):
            sel = [r for r in rows if r.get(kind) and r[kind]["score"] <= thr]
            out["thresholds"].append({"kind": kind, "thr": thr, **agg(sel)})
    # 2. 連續恐慌天數（盤中分數 ≤ -12），第 k 天收盤進場
    streak, byk = 0, {}
    for r in rows:
        streak = streak + 1 if r.get("intra") and r["intra"]["score"] <= -12 else 0
        if streak:
            byk.setdefault(min(streak, 4), []).append(r)
    lens, cur = [], 0
    for r in rows:
        if r.get("intra") and r["intra"]["score"] <= -12:
            cur += 1
        elif cur:
            lens.append(cur); cur = 0
    out["avg_streak"] = round(sum(lens) / len(lens), 1) if lens else None
    out["max_streak"] = max(lens) if lens else None
    for k in sorted(byk):
        out["streaks"].append({"k": k, **agg(byk[k])})
    # 3. 大盤波段低點／高點（前後 3 天最低／最高）那天的情緒
    for i, d in enumerate(tdays):
        if i < 3 or i + 3 >= len(tdays) or d not in {r["date"] for r in rows}:
            continue
        win = [closes[x] for x in tdays[i - 3:i + 4]]
        r = next(x for x in rows if x["date"] == d)
        k = 0
        for x in reversed([y for y in rows if y["date"] <= d]):
            if x.get("intra") and x["intra"]["score"] <= -12:
                k += 1
            else:
                break
        item = {"date": d, "intra": r["intra"]["score"] if r.get("intra") else None,
                "after": r["after"]["score"] if r.get("after") else None, "streak": k,
                "r5": round(fwd(d, 5) * 100, 2) if fwd(d, 5) is not None else None}
        if closes[d] == min(win):
            out["lows"].append(item)
        elif closes[d] == max(win):
            out["highs"].append(item)
    return out


# ---------------- 計分 ----------------
def label(score):
    return "極度恐慌" if score <= -40 else "偏空" if score <= -12 else "中性" if score < 12 else "偏多" if score < 40 else "極度貪婪"


def analyze_day(con, d, kind, detail=False):
    rows = con.execute("SELECT tag, content, t FROM ptt_push WHERE date=? AND kind=? ORDER BY i", (d, kind)).fetchall()
    if not rows:
        return None
    pos = neg = 0.0
    kw = Counter()
    kw_w = {}
    buckets = {}
    scored = []
    tags = Counter(r[0] for r in rows)
    for tag, content, t in rows:
        s, hits = score_text(content)
        for w, x in hits:
            kw[w] += 1
            kw_w[w] = x
        pos += max(s, 0)
        neg += max(-s, 0)
        if detail:
            hh, mm = int(t[11:13]), int(t[14:16])
            key = f"{t[:10]} {hh:02d}:{mm // 15 * 15:02d}"
            b = buckets.setdefault(key, [0.0, 0.0, 0])
            b[0] += max(s, 0); b[1] += max(-s, 0); b[2] += 1
            if s:
                scored.append((s, content, t))
    score = round(100 * (pos - neg) / (pos + neg), 1) if pos + neg else 0.0
    res = {"date": d, "kind": kind, "n": len(rows), "score": score, "label": label(score),
           "pos": round(pos, 1), "neg": round(neg, 1), "heat": round((pos + neg) / len(rows), 2),
           "tags": dict(tags)}
    if detail:
        res["keywords"] = sorted([{"w": w, "n": n, "weight": kw_w[w]} for w, n in kw.items()], key=lambda x: -x["n"])
        res["timeline"] = [{"t": k, "score": round(100 * (p - q) / (p + q), 1) if p + q else 0, "n": c}
                           for k, (p, q, c) in sorted(buckets.items())]
        scored.sort(key=lambda x: x[0])
        res["top_bear"] = [{"s": s, "c": c, "t": t} for s, c, t in scored[:8]]
        res["top_bull"] = [{"s": s, "c": c, "t": t} for s, c, t in scored[::-1][:8]]
    return res


def summary():
    """每天兩個分數 + 加權指數，以及「情緒 vs 大盤」驗證統計"""
    con = connect()
    _init(con)
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM ptt_post ORDER BY date")]
    tx = {r[0]: (r[1], r[2]) for r in con.execute("SELECT date, close, chg FROM taiex")}
    tdays = sorted(tx)
    out = []
    for d in days:
        row = {"date": d}
        for kind in ("intra", "after"):
            a = analyze_day(con, d, kind)
            row[kind] = a and {k: a[k] for k in ("n", "score", "label", "heat")}
        if d in tx:
            c, chg = tx[d]
            row["taiex"], row["taiex_chg"] = c, round(chg / (c - chg) * 100, 2)
        nxt = next((x for x in tdays if x > d), None)       # 下一個交易日（盤後情緒對應）
        if nxt:
            c, chg = tx[nxt]
            row["next_date"], row["next_chg"] = nxt, round(chg / (c - chg) * 100, 2)
        out.append(row)
    con.close()
    return {"days": out, "validation": validate(out), "rebound": rebound_stats(out, {d: v[0] for d, v in tx.items()})}


def validate(days):
    """盤中分數 vs 當天漲跌、盤後分數 vs 隔天漲跌"""
    res = {}
    for kind, ret_key, name in (("intra", "taiex_chg", "盤中情緒 → 當天大盤"), ("after", "next_chg", "盤後情緒 → 隔天大盤")):
        pts = [(r[kind]["score"], r[ret_key]) for r in days if r.get(kind) and r.get(ret_key) is not None]
        if len(pts) < 5:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in pts)
        vx, vy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
        corr = cov / (vx * vy) ** 0.5 if vx and vy else 0
        hi = [y for x, y in pts if x >= 12]
        lo = [y for x, y in pts if x <= -12]
        res[kind] = {"name": name, "n": len(pts), "corr": round(corr, 2),
                     "bull_n": len(hi), "bull_up": round(sum(y > 0 for y in hi) / len(hi) * 100) if hi else None,
                     "bull_avg": round(sum(hi) / len(hi), 2) if hi else None,
                     "bear_n": len(lo), "bear_up": round(sum(y > 0 for y in lo) / len(lo) * 100) if lo else None,
                     "bear_avg": round(sum(lo) / len(lo), 2) if lo else None}
    return res


def day_detail(d):
    con = connect()
    _init(con)
    res = {k: analyze_day(con, d, k, detail=True) for k in ("intra", "after")}
    con.close()
    return res
