"""波浪頁上方的「最新波浪／細浪」：照「主劇本」的大架構，用最新的 5 分K（日盤＋夜盤）數細浪、給看法和多空建議。
  - 主劇本：data/wave_scripts.json，一個日期一個版本（劇本有變就新增當天的版本，舊的留著可以翻）
  - 細浪紀錄：data/wave_subs.json，每天「日盤盤後」「夜盤」各留一筆最新的分析（Claude 手寫的另外存、不會被蓋掉）
  - 資料：資料庫的台指期 5 分K（期交所逐筆，每天下午 4 點後才有當天日盤）＋還沒進資料庫的即時走勢
    （夜盤／盤中：群益 TX00 逐筆；群益沒開時只能用期交所 MIS 夜盤的開高低收當一根）
分析是規則式（不用 API key、按一下就算）：主劇本給「已確認的轉折點、現在走第幾浪、失效價」，
程式算最後一個轉折點之後的小轉折（ZigZag）、回檔比例、費波南希價位，再套用固定的多空規則。"""
import calendar
import datetime as dt
import json
import os
import threading
import time

import pandas as pd

import settings
import waves
from data import connect

SCRIPT_PATH = os.path.join(settings.BASE, "data", "wave_scripts.json")
SUB_PATH = os.path.join(settings.BASE, "data", "wave_subs.json")
_lock = threading.Lock()
_last = {"t": 0, "v": None}
SUB_PCT = 0.0035          # 細浪 ZigZag 門檻（約 150 點）
FIB = (0.236, 0.382, 0.5, 0.618, 0.786)


# ---------- 存檔 ----------

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def scripts():
    """主劇本全部版本，新的在後面"""
    return sorted(_read(SCRIPT_PATH), key=lambda s: (s.get("date", ""), s.get("time", "")))


def current_script():
    s = scripts()
    return s[-1] if s else None


def save_script(entry):
    """新增一個版本；同一天同一個作者再存就蓋掉當天那版（一天一版，舊日期都留著）"""
    with _lock:
        allv = _read(SCRIPT_PATH)
        now = dt.datetime.now()
        entry = dict(entry)
        entry.setdefault("date", now.strftime("%Y-%m-%d"))
        entry.setdefault("time", now.strftime("%H:%M"))
        allv = [s for s in allv if not (s.get("date") == entry["date"] and s.get("author") == entry.get("author"))]
        allv.append(entry)
        _write(SCRIPT_PATH, sorted(allv, key=lambda s: (s.get("date", ""), s.get("time", ""))))
    _last["t"] = 0
    return entry


def subs():
    return sorted(_read(SUB_PATH), key=lambda s: (s.get("date", ""), s.get("time", "")))


def save_sub(entry):
    """細浪紀錄：同一天、同一盤別、同一作者只留最新一筆"""
    with _lock:
        allv = _read(SUB_PATH)
        allv = [s for s in allv if not (s.get("date") == entry["date"] and s.get("session") == entry["session"]
                                        and s.get("author", "auto") == entry.get("author", "auto"))]
        allv.append(entry)
        _write(SUB_PATH, sorted(allv, key=lambda s: (s.get("date", ""), s.get("time", "")))[-400:])


# ---------- 5 分K（資料庫＋即時） ----------

def _tw_ts(d):
    """台北時間 datetime → 資料庫用的「台北時間當成 UTC」秒數"""
    return calendar.timegm(d.timetuple())


def _ts_str(ts):
    return (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(ts))).strftime("%m/%d %H:%M")


def _live_bars(after_ts):
    """還沒進資料庫的走勢（5 分K），回傳 (DataFrame, 來源說明)"""
    out = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    # 1) 群益 TX00 逐筆（含夜盤；App 有連群益時最準。剛訂閱時群益會回補今天的逐筆，等幾秒）
    try:
        import capital
        if capital.ready():
            for _ in range(8):
                b = capital.bars_1m("TX00")
                if len(b):
                    break
                time.sleep(0.5)
            if len(b):
                b = b[b["date"] >= after_ts + 300]
                if len(b):
                    return _to5(b), "群益 TX00 逐筆"
    except Exception as e:
        print("波浪：群益逐筆讀取失敗", e)
    # 2) 期交所 MIS 沒有公開的分K介面：只拿得到夜盤開高低收
    # 3) 只有開高低收：當成一根（至少高低點、最新價是對的）
    try:
        import futures
        lv = futures.tx_live()
        if lv and lv.get("night"):
            _, o, h, l, c, _v = lv["night"]
            now = _tw_ts(dt.datetime.now().replace(second=0, microsecond=0))
            if now >= after_ts + 300:
                return pd.DataFrame([[now, o, h, l, c]], columns=out.columns), "期交所 MIS 夜盤開高低收（沒有分K，只有一根）"
    except Exception as e:
        print("波浪：MIS 行情讀取失敗", e)
    return out, ""


def _to5(b):
    b = b.copy()
    b["k"] = b["date"] // 300 * 300
    g = b.groupby("k")
    return pd.DataFrame({"date": g["date"].first() // 300 * 300, "open": g["open"].first(), "high": g["high"].max(),
                         "low": g["low"].min(), "close": g["close"].last()}).reset_index(drop=True)


def bars5(since_ts):
    con = connect()
    try:
        d = pd.read_sql("SELECT ts AS date, open, high, low, close FROM intraday WHERE code='TX' AND tf='5' AND ts>=? ORDER BY ts",
                        con, params=(int(since_ts),))
    finally:
        con.close()
    last = int(d["date"].iloc[-1]) if len(d) else int(since_ts)
    lv, src = _live_bars(last)
    db_to = _ts_str(last) if len(d) else ""
    if len(lv):
        d = pd.concat([d, lv], ignore_index=True)
    return d.reset_index(drop=True), src, db_to


# ---------- 細浪分析 ----------

def _session_label(now=None):
    """紀錄用的日期與盤別：夜盤（15:00～隔天 05:00）記在夜盤開始那天"""
    now = now or dt.datetime.now()
    t = now.time()
    if t >= dt.time(15, 0):
        return now.strftime("%Y-%m-%d"), "夜盤"
    if t < dt.time(5, 0):
        return (now - dt.timedelta(days=1)).strftime("%Y-%m-%d"), "夜盤"
    if dt.time(8, 45) <= t < dt.time(13, 45):
        return now.strftime("%Y-%m-%d"), "日盤盤中"
    if t >= dt.time(13, 45):
        return now.strftime("%Y-%m-%d"), "日盤盤後"
    return (now - dt.timedelta(days=1)).strftime("%Y-%m-%d"), "夜盤"   # 05:00~08:45：昨晚夜盤收完


def _pivot_ts(d, p, want_low):
    """主劇本的轉折點（日期/時間＋價位）對到 5 分K 上真正的那根"""
    t = p.get("t", "")
    try:
        base = dt.datetime.strptime(t, "%Y-%m-%d %H:%M") if len(t) > 10 else dt.datetime.strptime(t, "%Y-%m-%d")
    except ValueError:
        return None
    lo, hi = _tw_ts(base - dt.timedelta(days=1)), _tw_ts(base + dt.timedelta(days=2))
    w = d[(d["date"] >= lo) & (d["date"] <= hi)]
    if not len(w):
        return _tw_ts(base)
    col = "low" if want_low else "high"
    i = (w[col] - p["price"]).abs().idxmin()
    return int(d.loc[i, "date"])


def _f(x):
    return f"{x:,.0f}"


def analyze(save=True, author="auto"):
    sc = current_script()
    if not sc:
        return {"error": "還沒有主劇本（data/wave_scripts.json）"}
    pv = sc["pivots"]
    down = sc.get("trend", "down") == "down"       # 這一級（例如 C 浪）的大方向
    now_up = sc.get("now_dir", "up" if down else "down") == "up"   # 現在走的這一浪方向
    counter = now_up == down                         # 現在是逆勢浪（2、4、B）
    P, Q = pv[-1], pv[-2]                            # 最後一個確認的轉折、前一個
    p_low = now_up                                   # 現在往上 → P 是低點
    since = _tw_ts(dt.datetime.strptime(Q["t"][:10], "%Y-%m-%d") - dt.timedelta(days=2))
    d, src, db_to = bars5(since)
    if len(d) < 10:
        return {"error": "5 分K 不夠（資料庫還沒有台指期 5 分K）"}
    pts = _pivot_ts(d, P, want_low=p_low) or int(d["date"].iloc[0])
    qts = _pivot_ts(d, Q, want_low=not p_low) or int(d["date"].iloc[0])
    seg = d[d["date"] >= pts].reset_index(drop=True)
    last = seg.iloc[-1]
    px = float(last.close)
    leg = abs(Q["price"] - P["price"])               # 上一段（例如 C-3）的長度
    sgn = 1 if now_up else -1
    ext_i = int(seg["high"].idxmax()) if now_up else int(seg["low"].idxmin())
    ext = float(seg["high"].iloc[ext_i] if now_up else seg["low"].iloc[ext_i])
    ext_ts = int(seg["date"].iloc[ext_i])
    retr = sgn * (ext - P["price"]) / leg if leg else 0          # 這一段走了上一段的幾 %
    retr_now = sgn * (px - P["price"]) / leg if leg else 0
    back = sgn * (ext - px)                                         # 從這段極值退回多少
    fibs = [{"r": r, "price": P["price"] + sgn * leg * r} for r in FIB]
    inv = sc.get("invalid") or {}
    inv_p = inv.get("price")
    broke_inv = bool(inv_p) and ((seg["high"].max() > inv_p) if inv.get("dir", "above") == "above" else (seg["low"].min() < inv_p))
    broke_p = (seg["low"].min() < P["price"] - 1) if now_up else (seg["high"].max() > P["price"] + 1)   # 跌破起點 → 這段反彈其實沒開始／上一浪延伸

    # 細浪：P 之後的小轉折
    # 門檻：至少 SUB_PCT，且跟著這一段的長度放大（這段走 1,800 點 → 約 270 點才算一個細浪）
    pct = max(SUB_PCT, 0.15 * abs(ext - P["price"]) / px)
    zz = waves.zigzag(seg, pct)
    swings = [{"ts": pts, "price": float(P["price"]), "label": P["label"], "type": "L" if p_low else "H"}]
    for q in zz:
        if q[1] == 0:
            continue
        s_ = {"ts": int(seg["date"].iloc[q[1]]), "price": q[2], "open": len(q) > 3, "type": q[0]}
        if s_["type"] == swings[-1]["type"]:          # 同方向連續兩個：留比較極端的那個（起點 P 不動）
            if len(swings) > 1 and (s_["price"] > swings[-1]["price"]) == (s_["type"] == "H"):
                swings[-1] = s_
            continue
        swings.append(s_)
    if not swings[-1].get("open") and swings[-1]["ts"] != int(last.date):   # 最後一段走到現在
        swings.append({"ts": int(last.date), "price": px, "open": True, "now": True})
    legs = len(swings) - 1
    names = ["a", "b", "c", "d", "e"] if counter else ["(i)", "(ii)", "(iii)", "(iv)", "(v)"]
    for k, s in enumerate(swings[1:], 1):
        s["label"] = names[k - 1] if k <= 5 else f"+{k}"
    lens = [abs(swings[k + 1]["price"] - swings[k]["price"]) for k in range(legs)]

    now_name = sc.get("now", "")
    nxt = sc.get("next", "")
    U = lambda x: "上漲" if x else "下跌"
    count, view, longs, shorts, levels = [], [], [], [], []
    count.append(f"主劇本：<b>{sc.get('title', '')}</b>（{sc['date']} 版）")
    count.append(f"已確認：" + " → ".join(f"{p['label']} {_f(p['price'])}" for p in pv[-4:]))
    count.append(f"現在：<b>{now_name}</b>（從 {P['label']} {_f(P['price'])} 開始{U(now_up)}），"
                 f"最{'高' if now_up else '低'} {_f(ext)}（{_ts_str(ext_ts)}），"
                 f"走了上一段 {Q['label']}→{P['label']}（{_f(leg)} 點）的 <b>{retr:.1%}</b>；最新 {_f(px)}（{retr_now:.1%}）")
    if legs >= 1:
        count.append("細浪：" + "、".join(f"{s['label']} {_f(s['price'])}" + ("（進行中）" if s.get("open") else "")
                                         for s in swings[1:]))
    # 細浪的狀態判讀
    stage = ""
    if counter:
        if legs <= 1:
            stage = f"{now_name} 目前只有一段 a 浪，還在走；a 浪結束後通常有 b 浪回檔、c 浪再{'彈' if now_up else '跌'}"
        elif legs == 2:
            stage = f"a 浪 {_f(lens[0])} 點、b 浪{'回檔' if now_up else '反彈'} {_f(lens[1])} 點（a 的 {lens[1] / lens[0]:.0%}）；接下來看 c 浪，常見 c＝a → 約 {_f(swings[2]['price'] + sgn * lens[0])}"
        elif legs >= 3:
            c_ok = lens[2] >= lens[0] * 0.9
            stage = (f"a-b-c 三段已經出現（c 浪 {_f(lens[2])} 點＝a 的 {lens[2] / lens[0]:.2f} 倍）" +
                     ("，c≈a 或更長 → <b>{0} 可能已經完成</b>，留意轉{1}".format(now_name, "跌" if now_up else "漲") if c_ok else "，c 還比 a 短，可能還沒走完"))
            if legs >= 4:
                stage += "；又多出新的一段，可能是更複雜的修正（W-X-Y／三角形），等跌破／突破 b 浪再確認"
    else:
        if legs >= 5:
            stage = f"{now_name} 內部已經有 5 段，可能接近完成"
        else:
            stage = f"{now_name} 內部第 {legs} 段進行中"
    if stage:
        count.append(stage)

    # 看法
    if broke_inv:
        view.append(f"⚠ <b>已經突破失效價 {_f(inv_p)}</b>（{inv.get('why', '')}）→ 主劇本的數法不成立，改看備選劇本：{(sc.get('alt') or {}).get('title', '')}")
    elif broke_p:
        view.append(f"⚠ {'跌破' if now_up else '突破'} {P['label']} {_f(P['price'])}：{now_name} 已經結束（或根本沒展開），"
                    f"改看 {nxt or P['label'] + ' 延伸'}；主劇本要更新轉折點")
    else:
        zone_hit = [f for f in fibs if (f["price"] - ext) * sgn <= 0]
        z = zone_hit[-1]["r"] if zone_hit else 0
        if counter:
            view.append(f"{now_name} {'反彈' if now_up else '回檔'}到 {retr:.1%}"
                        + (f"，已經到 {z:.1%} 的位置（逆勢浪常見 23.6%~50%）" if z else "，還不到 23.6%，逆勢浪可能還沒走完"))
            if back > 0 and lens:
                view.append(f"從最{'高' if now_up else '低'}點退了 {_f(back)} 點；要是{'跌破' if now_up else '突破'} {P['label']} {_f(P['price'])}，"
                            f"代表 {now_name} 已經結束、{nxt or '下一浪'} 提早展開")
            view.append(f"大方向不變：{now_name} 走完後是 <b>{nxt or '順勢浪'}</b>（{U(not now_up)}）；只有{'突破' if now_up else '跌破'}失效價 {_f(inv_p) if inv_p else '–'} 才翻{'多' if down else '空'}")
        else:
            view.append(f"順勢的 {now_name} 進行中，已走上一段的 {retr:.1%}")
    for x in sc.get("notes_live", []):
        view.append(x)

    # 多空建議（規則式；價位都從主劇本＋5 分K 算出）
    stop_c = P["price"] - sgn * 30           # 逆勢浪的起點外 30 點
    sub_lo = min(s["price"] for s in swings[-3:]) if now_up else max(s["price"] for s in swings[-3:])
    z382, z500, z618 = (next(f["price"] for f in fibs if f["r"] == r) for r in (0.382, 0.5, 0.618))
    if broke_inv:
        longs.append("主劇本失效，先依備選劇本操作；回測失效價不破可偏多")
        shorts.append("暫停順勢空單，等新的主劇本")
    elif counter and now_up:          # 大方向空、現在反彈
        longs.append(f"只做短多：回測細浪低點 {_f(sub_lo)} 不破再進，停損 {_f(sub_lo - 60)}；目標 {_f(z382)}（38.2%）／{_f(z500)}（50%）")
        if retr >= 0.382:
            longs.append(f"已經反彈超過 38.2%，追多空間有限，有多單在 {_f(z500)}~{_f(z618)} 先出")
        shorts.append(f"順勢空單等反彈到壓力區 {_f(z382)}~{_f(min(z618, inv_p - 50) if inv_p else z618)}，5 分K 跌破最近小低點再空；停損放失效價 {_f(inv_p) if inv_p else '–'} 上方")
        for t in sc.get("targets", []):
            shorts.append(f"目標：{_f(t['price'])}（{t.get('label', '')}）")
    elif counter and not now_up:      # 大方向多、現在回檔
        shorts.append(f"只做短空：反彈到細浪高點 {_f(sub_lo)} 不過再空，停損 {_f(sub_lo + 60)}；目標 {_f(z382)}／{_f(z500)}")
        longs.append(f"順勢多單等回檔到 {_f(z382)}~{_f(z618)}，5 分K 站回最近小高點再多；停損放失效價 {_f(inv_p) if inv_p else '–'} 下方")
        for t in sc.get("targets", []):
            longs.append(f"目標：{_f(t['price'])}（{t.get('label', '')}）")
    else:                             # 順勢浪進行中
        (shorts if down else longs).append(f"順勢浪進行中，{'反彈' if down else '回檔'}到細浪 {'高' if down else '低'}點附近再加碼，停損放上一個細浪{'高' if down else '低'}點外")
        (longs if down else shorts).append("逆勢單不做，等這一浪 5 段走完")
    if not broke_inv:
        longs.append(f"翻多條件：{'突破' if down else '守住'} {_f(inv_p) if inv_p else '–'}")
    levels += [f"{f['r']:.1%}：{_f(f['price'])}" for f in fibs[:4]]
    if inv_p:
        levels.append(f"<b>失效價 {_f(inv_p)}</b>：{inv.get('why', '')}")
    levels.append(f"{P['label']} {'低' if now_up else '高'}點 {_f(P['price'])}：{'跌破' if now_up else '突破'}＝{now_name} 結束")

    date, sess = _session_label()
    now = dt.datetime.now()
    out = {"date": date, "session": sess, "time": now.strftime("%H:%M"), "author": author, "src": src, "db_to": db_to,
           "asof": _ts_str(int(last.date)), "price": px, "script_date": sc["date"], "script_title": sc.get("title", ""),
           "now": now_name, "retr": retr, "ext": ext, "broke_inv": broke_inv,
           "count": count, "view": view, "long": longs, "short": shorts, "levels": levels,
           "swings": [{k: v for k, v in s.items()} for s in swings],
           "pivots": [{"label": Q["label"], "ts": qts, "price": Q["price"]}, {"label": P["label"], "ts": pts, "price": P["price"]}],
           "fibs": fibs, "invalid": inv_p,
           "bars": [[int(r.date), r.open, r.high, r.low, r.close] for r in d[d["date"] >= qts - 3600 * 6].itertuples()]}
    if save:
        lean = {k: v for k, v in out.items() if k != "bars"}
        save_sub(lean)
        if broke_inv:
            _auto_switch(sc, out)
    _last.update(t=time.time(), v=out)
    return out


def _auto_switch(sc, out):
    """主劇本被突破失效價：有寫備選劇本（alt.script）就自動新增今天的版本"""
    alt = (sc.get("alt") or {}).get("script")
    today = dt.datetime.now().strftime("%Y-%m-%d")
    if not alt or any(s.get("date") == today and s.get("author") == "auto" for s in scripts()):
        return
    new = dict(alt, date=today, author="auto",
               change=f"{out['asof']} 價格 {_f(out['ext'])} 突破失效價 {_f(out['invalid'])}，自動把備選劇本升為主劇本（原 {sc['date']} 版：{sc.get('title', '')}）")
    save_script(new)


def get(force=False):
    """頁面載入用：1 分鐘內算過就直接給"""
    if not force and _last["v"] and time.time() - _last["t"] < 60:
        return _last["v"]
    return analyze()


if __name__ == "__main__":
    o = analyze(save=False)
    for k in ("count", "view", "long", "short", "levels"):
        print(k, json.dumps(o.get(k), ensure_ascii=False, indent=1))
    print(o.get("src"), o.get("asof"), o.get("db_to"))
