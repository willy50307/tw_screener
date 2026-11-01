"""
籌碼整理：每天晚上抓三大法人、融資融券、借券賣出、漲停股的券商分點，存進資料庫，再整理成報表。
  三大法人：證交所 T86、櫃買 insti/dailyTrade（單位：股 → 存成張）
  融資融券：證交所 MI_MARGN、櫃買 margin/balance（張）
  借券賣出：證交所 TWT93U、櫃買 margin/sbl（股 → 張）
  券商分點：MoneyDJ（富邦 e 點通）個股主力進出，每檔前 15 名買超／賣超分點（張）
            只抓「當天收漲停」和「前一天收漲停」的股票（看隔日沖買進、隔天有沒有倒貨）
全部存在 stocks.db：inst / margin / sbl / broker / chips_fetched
"""
import datetime as dt
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import settings
from data import HEADERS, _get_json, _num, connect, update_prices
from limitup import limit_up

KINDS = ("inst", "margin", "sbl")
_lock = threading.Lock()

IND = {"01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷",
       "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅",
       "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療", "23": "油電燃氣",
       "24": "半導體", "25": "電腦週邊", "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路",
       "30": "資訊服務", "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
       "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證"}

# 隔日沖分點：使用者提供＋網路常見名單（名稱去掉「-」「證券」比對）。可在設定 dt_branches 修改
DT_BRANCHES = ["凱基台北", "凱基站前", "凱基城中", "統一城中", "國票安和", "國票敦北法人",
               "元大土城永寧", "富邦建國", "群益金鼎大安", "凱基松山", "康和永和", "凱基復興", "富邦仁愛"]
# 券商總公司：沒有地點，只有「當天買超第一名」才當成隔日沖
DT_HQ = ["富邦", "元大"]


def norm(name):
    return re.sub(r"[-\s]|證券", "", name or "")


def _is_etf(code):
    return not (len(code) == 4 and code.isdigit() and code[0] != "0")


# ---------------- 資料庫 ----------------
def _init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS inst(date TEXT, code TEXT, fi REAL, fid REAL, it REAL, dp REAL, dh REAL, PRIMARY KEY(date, code));
    CREATE TABLE IF NOT EXISTS margin(date TEXT, code TEXT, m_prev REAL, m_bal REAL, s_prev REAL, s_bal REAL, PRIMARY KEY(date, code));
    CREATE TABLE IF NOT EXISTS sbl(date TEXT, code TEXT, prev REAL, sold REAL, ret REAL, bal REAL, PRIMARY KEY(date, code));
    CREATE TABLE IF NOT EXISTS broker(date TEXT, code TEXT, side TEXT, rank INTEGER, bid TEXT, branch TEXT,
                                      buy REAL, sell REAL, PRIMARY KEY(date, code, side, rank));
    CREATE TABLE IF NOT EXISTS margin_mkt(date TEXT, market TEXT, m_prev REAL, m_bal REAL, a_prev REAL, a_bal REAL, PRIMARY KEY(date, market));
    CREATE TABLE IF NOT EXISTS chips_fetched(kind TEXT, market TEXT, date TEXT, n INTEGER, PRIMARY KEY(kind, market, date));
    CREATE INDEX IF NOT EXISTS broker_bid ON broker(bid, date);
    """)


def _tw(d):
    return d.strftime("%Y%m%d")


def _tp(d):
    return d.strftime("%Y/%m/%d")


def _table(j, need):
    """在證交所/櫃買的回傳裡找出含有 need 欄位的表"""
    if not j:
        return None
    tabs = j.get("tables") or ([{"fields": j.get("fields"), "data": j.get("data")}] if j.get("fields") else [])
    for t in tabs:
        f = [x.strip() for x in (t.get("fields") or [])]
        if need in f and t.get("data"):
            return f, t["data"]
    return [], []


# 每個 fetcher 回傳 rows（list of tuple, 不含 date）；None = 連線失敗；[] = 當天沒資料
def inst_twse(d):
    j = _get_json("https://www.twse.com.tw/rwd/zh/fund/T86", {"date": _tw(d), "selectType": "ALLBUT0999", "response": "json"})
    if not j:
        return None
    if j.get("stat") != "OK":
        return []
    f, data = _table(j, "證券代號")
    i = {k: f.index(k) for k in f}
    g = lambda r, k: (_num(r[i[k]]) or 0) / 1000
    return [(r[0].strip(), g(r, "外陸資買賣超股數(不含外資自營商)"), g(r, "外資自營商買賣超股數"), g(r, "投信買賣超股數"),
             g(r, "自營商買賣超股數(自行買賣)"), g(r, "自營商買賣超股數(避險)")) for r in data]


def inst_tpex(d):
    j = _get_json("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade", {"type": "Daily", "sect": "EW", "date": _tp(d), "response": "json"})
    if not j:
        return None
    if j.get("date") != _tw(d):
        return []
    f, data = _table(j, "代號")
    # 欄位順序：外資(不含自營)、外資自營、外資合計、投信、自營(自行)、自營(避險)、自營合計，各有 買/賣/超
    g = lambda r, k: (_num(r[k]) or 0) / 1000
    return [(r[0].strip(), g(r, 4), g(r, 7), g(r, 13), g(r, 16), g(r, 19)) for r in data if len(r) >= 23]


def margin_twse(d):
    j = _get_json("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN", {"date": _tw(d), "selectType": "ALL", "response": "json"})
    if not j:
        return None
    if j.get("stat") != "OK":
        return []
    f, data = _table(j, "代號")
    # 代號 名稱 | 融資：買 賣 現償 前日餘額 今日餘額 限額 | 融券：買 賣 現券償還 前日餘額 今日餘額 限額 | 資券互抵 註記
    return [(r[0].strip(), _num(r[5]), _num(r[6]), _num(r[11]), _num(r[12])) for r in data]


def margin_tpex(d):
    j = _get_json("https://www.tpex.org.tw/www/zh-tw/margin/balance", {"date": _tp(d), "response": "json"})
    if not j:
        return None
    if j.get("date") != _tw(d):
        return []
    f, data = _table(j, "代號")
    i = {k: f.index(k) for k in ("前資餘額(張)", "資餘額", "前券餘額(張)", "券餘額")}
    return [(r[0].strip(), _num(r[i["前資餘額(張)"]]), _num(r[i["資餘額"]]), _num(r[i["前券餘額(張)"]]), _num(r[i["券餘額"]])) for r in data]


# 全市場融資合計（約晚上 9 點公布）：回傳 (前日張, 今日張, 前日金額仟元, 今日金額仟元)；None = 失敗；() = 還沒公布
def mtot_twse(d):
    j = _get_json("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN", {"date": _tw(d), "selectType": "MS", "response": "json"})
    if not j:
        return None
    if j.get("stat") != "OK" or j.get("date") != _tw(d):
        return ()
    rows = {r[0].strip(): r for r in (_table(j, "項目")[1] or [])}
    q, a = rows.get("融資(交易單位)"), rows.get("融資金額(仟元)")
    return (_num(q[4]), _num(q[5]), _num(a[4]), _num(a[5])) if q and a else ()


def mtot_tpex(d):
    j = _get_json("https://www.tpex.org.tw/www/zh-tw/margin/balance", {"date": _tp(d), "response": "json"})
    if not j:
        return None
    if j.get("date") != _tw(d):
        return ()
    for t in j.get("tables") or []:
        rows = {r[1].strip(): r for r in t.get("summary") or [] if len(r) > 6}
        q, a = rows.get("合計(張)"), rows.get("融資金(仟元)")
        if q and a:
            return (_num(q[2]), _num(q[6]), _num(a[2]), _num(a[6]))
    return ()


def update_margin_mkt(dates=None):
    """抓全市場（上市／上櫃）融資合計；回傳今天是否兩邊都抓到了"""
    con = connect()
    _init(con)
    dates = dates or [dt.date.today()]
    for d in dates:
        done = {r[0] for r in con.execute("SELECT market FROM margin_mkt WHERE date=?", (d.isoformat(),))}
        for market, fn in (("上市", mtot_twse), ("上櫃", mtot_tpex)):
            if market in done:
                continue
            r = fn(d)
            if r and None not in r:
                with _lock:
                    con.execute("INSERT OR REPLACE INTO margin_mkt VALUES(?,?,?,?,?,?)", (d.isoformat(), market, *r))
                    con.execute("INSERT OR REPLACE INTO chips_fetched VALUES('mtot',?,?,1)", (market, d.isoformat()))
                    con.commit()
    ok = con.execute("SELECT COUNT(*) FROM margin_mkt WHERE date=?", (dt.date.today().isoformat(),)).fetchone()[0] >= 2
    con.close()
    return ok


def margin_mkt(con, date):
    """某天全市場融資增減：{上市: {chg 張, amt 億, bal 張, amt_bal 億}, 上櫃: ...}"""
    out = {}
    for m, mp, mb, ap, ab in con.execute("SELECT market, m_prev, m_bal, a_prev, a_bal FROM margin_mkt WHERE date=?", (date,)):
        out[m] = {"chg": mb - mp, "amt": round((ab - ap) / 1e5, 2), "bal": mb, "amt_bal": round(ab / 1e5, 1)}
    return out


def _sbl_rows(data):
    # 代號 名稱 | 融券 前日 賣出 買進 現券 今日 限額 | 借券賣出 前日餘額 當日賣出 當日還券 當日調整 當日餘額 可限額 | 備註
    k = lambda x: (_num(x) or 0) / 1000
    return [(r[0].strip(), k(r[8]), k(r[9]), k(r[10]), k(r[12])) for r in data if len(r) >= 13]


def sbl_twse(d):
    j = _get_json("https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U", {"date": _tw(d), "response": "json"})
    if not j:
        return None
    if j.get("stat") != "OK":
        return []
    return _sbl_rows(_table(j, "代號")[1])


def sbl_tpex(d):
    j = _get_json("https://www.tpex.org.tw/www/zh-tw/margin/sbl", {"date": _tp(d), "response": "json"})
    if not j:
        return None
    if j.get("date") != _tw(d):
        return []
    return _sbl_rows(_table(j, "股票代號")[1])


FETCH = {("inst", "上市"): inst_twse, ("inst", "上櫃"): inst_tpex, ("margin", "上市"): margin_twse,
         ("margin", "上櫃"): margin_tpex, ("sbl", "上市"): sbl_twse, ("sbl", "上櫃"): sbl_tpex}
SQL = {"inst": "INSERT OR REPLACE INTO inst VALUES(?,?,?,?,?,?,?)", "margin": "INSERT OR REPLACE INTO margin VALUES(?,?,?,?,?,?)",
       "sbl": "INSERT OR REPLACE INTO sbl VALUES(?,?,?,?,?,?)"}


def _done(con, kind, market):
    return {r[0] for r in con.execute("SELECT date FROM chips_fetched WHERE kind=? AND market=?", (kind, market))}


def _market_job(market, dates, delay, progress, kinds=KINDS):
    con = connect()
    today = dt.date.today()
    for kind in kinds:
        done = _done(con, kind, market)
        todo = [d for d in dates if d.isoformat() not in done]
        for k, d in enumerate(todo, 1):
            progress[f"{market}{ {'inst': '法人', 'margin': '融資券', 'sbl': '借券'}[kind] }"] = [k, len(todo)]
            rows = FETCH[(kind, market)](d)
            if rows is None:
                continue
            with _lock:
                con.executemany(SQL[kind], [(d.isoformat(), *r) for r in rows])
                if rows or d < today:
                    con.execute("INSERT OR REPLACE INTO chips_fetched VALUES(?,?,?,?)", (kind, market, d.isoformat(), len(rows)))
                con.commit()
            time.sleep(delay)
    con.close()


# ---------------- 券商分點（MoneyDJ）----------------
DJ = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"
_TD = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
_A = re.compile(r'b=([^&"]+)[^>]*>([^<]+)</a>', re.I)


def fetch_branch(sess, code, d):
    """回傳 [(side, rank, bid, branch, buy, sell)]；None = 失敗"""
    ds = d.isoformat()
    for attempt in range(3):
        try:
            r = sess.get(DJ, params={"a": code, "e": ds, "f": ds}, headers=HEADERS, timeout=20)
            r.encoding = "big5"
            h = r.text
            break
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        return None
    k = h.find("買超券商")
    if k < 0:
        return []
    out, rank = [], {"B": 0, "S": 0}
    for tr in re.split(r"<TR[^>]*>", h[k:h.find("</table>", k)], flags=re.I)[1:]:
        cells = _TD.findall(tr)
        for side, cs in (("B", cells[0:5]), ("S", cells[5:10])):
            if len(cs) < 3:
                continue
            m = _A.search(cs[0])
            if not m:
                continue
            rank[side] += 1
            out.append((side, rank[side], m.group(1), m.group(2).strip(), _num(re.sub("<[^>]+>", "", cs[1])) or 0,
                        _num(re.sub("<[^>]+>", "", cs[2])) or 0))
    return out


def limitup_codes(con, dates):
    """每天收漲停的普通股 {date: [code]}"""
    if not dates:
        return {}
    lo = (min(dates) - dt.timedelta(days=15)).isoformat()
    px = pd.read_sql("SELECT code, date, close FROM prices WHERE date >= ? AND length(code)=4 AND substr(code,1,1) != '0' "
                     "ORDER BY code, date", con, params=(lo,))
    px["pc"] = px.groupby("code")["close"].shift(1)
    px = px[px["pc"] > 0]
    px = px[px["close"] >= limit_up(px["pc"]) - 1e-6]
    return {d: g["code"].tolist() for d, g in px.groupby("date")}


def _broker_job(dates, progress):
    con = connect()
    days = sorted(dates)
    lu = limitup_codes(con, days)
    trade_days = [r[0] for r in con.execute("SELECT DISTINCT date FROM prices WHERE date >= ? ORDER BY date",
                                            ((days[0] - dt.timedelta(days=15)).isoformat(),))] if days else []
    have = {(r[0], r[1]) for r in con.execute("SELECT DISTINCT date, code FROM broker WHERE date >= ?",
                                              (days[0].isoformat(),))} if days else set()
    done = _done(con, "broker", "all")
    todo = []
    for d in days:
        ds = d.isoformat()
        if ds in done or ds not in trade_days:
            continue
        i = trade_days.index(ds)
        prev = trade_days[i - 1] if i else None
        codes = sorted(set(lu.get(ds, [])) | set(lu.get(prev, [])))   # 今天漲停＋昨天漲停（看隔天賣出）
        todo.append((d, [c for c in codes if (ds, c) not in have]))
    total = sum(len(c) for _, c in todo)
    n = 0
    sess = requests.Session()
    for d, codes in todo:
        ok = True
        for c in codes:
            n += 1
            progress["分點"] = [n, total]
            rows = fetch_branch(sess, c, d)
            if rows is None:
                ok = False
                continue
            with _lock:
                con.executemany("INSERT OR REPLACE INTO broker VALUES(?,?,?,?,?,?,?,?)", [(d.isoformat(), c, *r) for r in rows])
                con.commit()
            time.sleep(0.25)
        if ok and (d < dt.date.today() or dt.datetime.now().hour >= 19):
            with _lock:
                con.execute("INSERT OR REPLACE INTO chips_fetched VALUES('broker','all',?,?)", (d.isoformat(), len(codes)))
                con.commit()
    con.close()


def update(days_back=0, broker_days=None, progress=None, kinds=KINDS + ("broker",)):
    """抓 days_back 天前到今天的籌碼資料（已經抓過的日子會跳過）；kinds 可只抓其中幾種"""
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    today = dt.date.today()
    if not con.execute("SELECT 1 FROM fetched WHERE date=? LIMIT 1", (today.isoformat(),)).fetchone() and today.weekday() < 5:
        progress["msg"] = "先更新今天收盤行情…"
        update_prices(5)
    trade = {r[0] for r in con.execute("SELECT DISTINCT date FROM fetched WHERE n > 0 AND date >= ?",
                                        ((today - dt.timedelta(days=days_back + 5)).isoformat(),))}
    dates = [today - dt.timedelta(days=i) for i in range(days_back, -1, -1)]
    dates = [d for d in dates if d.weekday() < 5 and (d.isoformat() in trade or d == today)]
    bdates = dates if broker_days is None else dates[-broker_days - 1:]
    progress["msg"] = "抓取法人／融資券／借券／分點…"
    with ThreadPoolExecutor(3) as ex:
        mk = tuple(k for k in KINDS if k in kinds)
        fs = [ex.submit(_market_job, "上市", dates, 3.0, progress, mk), ex.submit(_market_job, "上櫃", dates, 1.5, progress, mk)]
        if "broker" in kinds:
            fs.append(ex.submit(_broker_job, bdates, progress))
        for f in fs:
            f.result()
    if "margin" in kinds:
        update_margin_mkt(dates[-7:])
    con.close()
    _cache.clear()


def status():
    con = connect()
    _init(con)
    today = dt.date.today().isoformat()
    got = {(k, m) for k, m in con.execute("SELECT kind, market FROM chips_fetched WHERE date=?", (today,))}
    rng = {k: con.execute(f"SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM {k}").fetchone() for k in ("inst", "margin", "sbl", "broker")}
    con.close()
    mk = lambda ks: {(k, m) for k in ks for m in ("上市", "上櫃")}
    eve = mk(["inst"]) | {("broker", "all")}             # 晚上 7 點：法人＋分點
    night = mk(["margin", "sbl"])                         # 晚上 10 點：融資券＋借券
    return {"today_done": (eve | night) <= got, "eve_done": eve <= got, "night_done": night <= got,
            "mtot_done": {("mtot", "上市"), ("mtot", "上櫃")} <= got, "today_parts": sorted(f"{k}/{m}" for k, m in got), "range": rng}


# ---------------- 報表 ----------------
_cache = {}


def _clean(o):
    """轉成可以給 JSON 的格式（numpy 型別、NaN → None）"""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 2)
    return o


def _load(con, since):
    px = pd.read_sql("SELECT code, date, name, market, open, high, low, close, volume FROM prices WHERE date >= ? ORDER BY code, date",
                     con, params=(since,))
    g = px.groupby("code", sort=False)
    px["pc"] = g["close"].shift(1)
    px["chg"] = (px["close"] / px["pc"] - 1) * 100
    return px


def _rows(df, col, n=100, asc=False, extra=()):
    d = df[df[col].notna() & (df[col] != 0)]
    d = d[d[col] < 0] if asc else d[d[col] > 0]
    d = d.sort_values(col, ascending=asc).head(n)
    cols = ["code", "name", "market", "close", "chg", col, *extra]
    return [{k: (None if pd.isna(v) else (round(float(v), 2) if isinstance(v, (float, np.floating)) else v))
             for k, v in zip(cols, r)} for r in d[cols].itertuples(index=False)]


def report(date=None):
    key = date or "latest"
    con = connect()
    _init(con)
    stamp = con.execute("SELECT COUNT(*) FROM chips_fetched").fetchone()[0]   # 資料庫有新資料就重算
    if _cache.get("_stamp") != stamp:
        _cache.clear()
        _cache["_stamp"] = stamp
    if key in _cache:
        con.close()
        return _cache[key]
    dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM inst ORDER BY date DESC LIMIT 400")]
    if not dates:
        con.close()
        return {"error": "還沒有籌碼資料，請按「抓今天資料」或「補抓歷史」"}
    date = date if date in dates else dates[0]
    i0 = dates.index(date)
    win = dates[i0:i0 + 20]                          # 最近 20 個交易日（含今天）
    since = (dt.date.fromisoformat(win[-1]) - dt.timedelta(days=130)).isoformat()
    px = _load(con, since)
    day = px[px["date"] == date].set_index("code")
    meta_ind = _industry()

    inst = pd.read_sql("SELECT * FROM inst WHERE date IN (%s)" % ",".join("?" * len(win)), con, params=win)
    inst = inst.merge(px[["code", "date", "close"]], on=["code", "date"], how="left")
    for c in ("fi", "fid", "it", "dp", "dh"):
        inst[c + "_amt"] = inst[c] * inst["close"] / 1e5          # 張 × 價 × 1000 / 1e8 = 億
    today = inst[inst["date"] == date].set_index("code")
    base = day[["name", "market", "close", "chg"]].join(today[[c for c in today.columns if c not in ("date", "close")]], how="inner").reset_index()

    # ① 四種法人 買超／賣超 前 100
    out = {"date": date, "dates": dates[:120], "inst": {}, "summary": {}}
    names = {"fi": "外資", "it": "投信", "dh": "自營商(避險)", "dp": "自營商(自行買賣)"}
    for c, nm in names.items():
        out["inst"][c] = {"name": nm, "buy": _rows(base, c, extra=(c + "_amt",)), "sell": _rows(base, c, asc=True, extra=(c + "_amt",))}
        out["summary"][c] = {"name": nm, "amt": round(float(base[c + "_amt"].sum()), 2),
                             "twse": round(float(base.loc[base["market"] == "上市", c + "_amt"].sum()), 2)}

    off = official_twse(date)
    for c in names:
        out["summary"][c]["official"] = off.get(c)
    out["summary_all"] = off.get("all")

    # ⑤ 土洋同步（排除 ETF）
    st = base[~base["code"].map(_is_etf)].copy()
    st["fiit_amt"] = st["fi_amt"] + st["it_amt"]
    both_b = st[(st["fi"] > 0) & (st["it"] > 0)].sort_values("fiit_amt", ascending=False).head(100)
    both_s = st[(st["fi"] < 0) & (st["it"] < 0)].sort_values("fiit_amt").head(100)
    tcols = ["code", "name", "market", "close", "chg", "fi", "it", "fiit_amt"]
    rec = lambda d: [dict(zip(tcols, [None if pd.isna(x) else (round(float(x), 2) if isinstance(x, (float, np.floating)) else x) for x in r]))
                     for r in d[tcols].itertuples(index=False)]
    out["tuyang"] = {"buy": rec(both_b), "sell": rec(both_s), "n_buy": int(((st["fi"] > 0) & (st["it"] > 0)).sum()),
                     "n_sell": int(((st["fi"] < 0) & (st["it"] < 0)).sum())}

    # ④ 融資／融券／借券賣出
    mg = pd.read_sql("SELECT * FROM margin WHERE date=?", con, params=(date,))
    mg["m_chg"], mg["s_chg"] = mg["m_bal"] - mg["m_prev"], mg["s_bal"] - mg["s_prev"]
    sb = pd.read_sql("SELECT * FROM sbl WHERE date=?", con, params=(date,))
    sb["l_chg"] = sb["bal"] - sb["prev"]
    mb = day[["name", "market", "close", "chg"]].reset_index()
    m1, s1 = mb.merge(mg, on="code"), mb.merge(sb, on="code")
    out["margin"] = {
        "m_up": _rows(m1, "m_chg", extra=("m_bal",)), "m_dn": _rows(m1, "m_chg", asc=True, extra=("m_bal",)),
        "s_up": _rows(m1, "s_chg", extra=("s_bal",)), "s_dn": _rows(m1, "s_chg", asc=True, extra=("s_bal",)),
        "l_up": _rows(s1, "l_chg", extra=("bal", "sold")), "l_dn": _rows(s1, "l_chg", asc=True, extra=("bal", "ret")),
        "tot": {"m_chg": round(float(mg["m_chg"].sum()), 0), "s_chg": round(float(mg["s_chg"].sum()), 0),
                "l_chg": round(float(sb["l_chg"].sum()), 0), "has": bool(len(mg)), "has_sbl": bool(len(sb))},
        "mkt": margin_mkt(con, date)}

    # ③ 資金流向（外資、投信；1／5／20 日，排除 ETF）
    out["trend"] = _trend(inst[~inst["code"].map(_is_etf)], win, day, meta_ind)

    # ② 隔日沖分點
    out["daytrade"] = _daytrade(con, px, date, dates)
    con.close()
    out = _clean(out)
    _cache[key] = out
    if key != date:
        _cache[date] = out
    return out


_official = {}


def official_twse(date):
    """證交所公布的上市三大法人買賣金額（億）"""
    if date not in _official:
        try:
            j = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U", headers=HEADERS, timeout=8,
                             params={"type": "day", "dayDate": date.replace("-", ""), "response": "json"}).json()
            m = {"自營商(自行買賣)": "dp", "自營商(避險)": "dh", "投信": "it", "外資及陸資(不含外資自營商)": "fi", "合計": "all"}
            _official[date] = {m[r[0]]: round(_num(r[3]) / 1e8, 2) for r in j.get("data") or [] if r[0] in m}
        except Exception:
            return {}
    return _official[date]


def _industry():
    import notice
    comp = notice.load_meta().get("company", {})
    return {c: IND.get(v.get("ind", ""), v.get("ind") or "其他") for c, v in comp.items()}


def _trend(inst, win, day, ind):
    d = inst.copy()
    d["ind"] = d["code"].map(ind).fillna("其他")
    res = {"periods": [1, 5, 20], "n_days": len(win)}
    for who in ("fi", "it"):
        col = who + "_amt"
        per = {}
        for n in (1, 5, 20):
            sub = d[d["date"].isin(win[:n])]
            per[n] = sub.groupby("ind")[col].sum()
        tab = pd.DataFrame(per).fillna(0)
        cnt = d[d["date"] == win[0]].assign(b=lambda x: x[who] > 0).groupby("ind")["b"].agg(["sum", "size"])
        tab = tab.join(cnt).fillna(0).sort_values(5, ascending=False)
        res[who + "_ind"] = [{"ind": i, "d1": round(r[1], 2), "d5": round(r[5], 2), "d20": round(r[20], 2),
                              "nbuy": int(r["sum"]), "n": int(r["size"])} for i, r in tab.iterrows()]
        # 個股：5 日、20 日累計金額，連續買（賣）超天數
        p = d.pivot_table(index="code", columns="date", values=who, aggfunc="sum").reindex(columns=win)
        pa = d.pivot_table(index="code", columns="date", values=col, aggfunc="sum").reindex(columns=win)
        s5, s20 = pa[win[:5]].sum(axis=1), pa.sum(axis=1)
        sign = np.sign(p.fillna(0).values)
        streak = np.zeros(len(p), dtype=int)
        first = sign[:, 0]
        for k in range(len(win)):
            cont = (sign[:, k] == first) & (first != 0)
            if k == 0:
                streak = cont.astype(int)
            else:
                streak = np.where((streak == k) & cont, k + 1, streak)
        s = pd.DataFrame({"s1": pa[win[0]], "s5": s5, "s20": s20, "streak": streak * first,
                          "lots5": p[win[:5]].sum(axis=1)}, index=p.index)
        s = s.join(day[["name", "close", "chg"]], how="inner")
        s["ind"] = s.index.map(ind).fillna("其他")

        def top(k, asc):
            t = s.sort_values(k, ascending=asc).head(30)
            t = t[t[k] < 0] if asc else t[t[k] > 0]
            return [{"code": c, "name": r["name"], "ind": r["ind"], "close": r["close"], "chg": round(r["chg"], 2) if pd.notna(r["chg"]) else None,
                     "s1": round(r["s1"], 2) if pd.notna(r["s1"]) else 0, "s5": round(r["s5"], 2), "s20": round(r["s20"], 2),
                     "streak": int(r["streak"]), "lots5": round(r["lots5"])} for c, r in t.iterrows()]
        res[who + "_in5"], res[who + "_out5"] = top("s5", False), top("s5", True)
        res[who + "_in20"], res[who + "_out20"] = top("s20", False), top("s20", True)
        res[who + "_streak"] = top("streak", False)[:20]
    return res


# ---------------- 隔日沖分析 ----------------
def _dt_list():
    p = settings.load()
    return [norm(x) for x in (p.get("dt_branches") or DT_BRANCHES)]


def _features(px):
    """每檔每天的技術面／量價特徵（給漲停股用）"""
    g = px.groupby("code", sort=False)
    px["lim"] = limit_up(px["pc"])
    px["lu"] = (px["pc"] > 0) & (px["close"] >= px["lim"] - 1e-6)
    px["streak"] = g["lu"].transform(lambda s: s.groupby((~s).cumsum()).cumsum())
    px["vr"] = px["volume"] / g["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    px["hh20"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    px["hh60"] = g["high"].transform(lambda s: s.shift(1).rolling(60, min_periods=30).max())
    for n in (5, 20, 60):
        px[f"ma{n}"] = g["close"].transform(lambda s: s.rolling(n, min_periods=n).mean())
    px["r20"] = (px["close"] / g["close"].shift(20) - 1) * 100
    px["lu_type"] = np.select([(px["open"] >= px["lim"] - 1e-6) & (px["low"] >= px["lim"] - 1e-6), px["open"] >= px["lim"] - 1e-6],
                              ["一字鎖死", "開盤漲停打開又鎖"], "盤中拉上漲停")
    px["brk"] = np.select([px["close"] > px["hh60"], px["close"] > px["hh20"]], ["突破60日新高", "突破20日高"], "未突破")
    px["ma_st"] = np.select([(px["close"] > px["ma5"]) & (px["ma5"] > px["ma20"]) & (px["ma20"] > px["ma60"]), px["close"] < px["ma60"]],
                            ["均線多頭排列", "季線下"], "均線糾結")
    px["vol_st"] = np.select([px["vr"] >= 3, px["vr"] >= 1.5, px["vr"] < 1], ["爆量(≧3倍)", "放量(1.5~3倍)", "量縮(<1倍)"], "溫和(1~1.5倍)")
    for c in ("open", "high", "low", "close"):
        px["n_" + c] = g[c].shift(-1)
    px["n_gap"] = (px["n_open"] / px["close"] - 1) * 100
    px["n_hi"] = (px["n_high"] / px["close"] - 1) * 100
    px["n_cl"] = (px["n_close"] / px["close"] - 1) * 100
    px["n_o2c"] = (px["n_close"] / px["n_open"] - 1) * 100
    return px


def _classify(b, dtset):
    """一檔股票當天的買超分點 → 隔日沖張數、名單"""
    b = b.assign(net=b["buy"] - b["sell"], nm=b["branch"].map(norm)).sort_values("rank")
    hit = b["nm"].isin(dtset) | ((b["rank"] == 1) & b["nm"].isin(DT_HQ))
    return b, hit


def _daytrade(con, px, date, dates):
    br = pd.read_sql("SELECT * FROM broker WHERE side='B' AND date >= ?", con, params=(dates[min(len(dates) - 1, 119)],))
    brs = pd.read_sql("SELECT date, code, branch, bid, sell - buy AS net_sell FROM broker WHERE side='S' AND date >= ?",
                      con, params=(dates[min(len(dates) - 1, 119)],))
    if br.empty:
        return {"error": "還沒有分點資料"}
    f = _features(px[px["code"].isin(set(br["code"]))].copy())      # 只算有分點資料的股票，比較快
    lu = f[f["lu"] & ~f["code"].map(_is_etf)].set_index(["date", "code"])
    dtset = set(_dt_list())
    vol = f.set_index(["date", "code"])["volume"] / 1000

    # 每一檔漲停股：隔日沖張數（整批計算）
    keys = pd.MultiIndex.from_frame(br[["date", "code"]])
    b = br[keys.isin(lu.index)].copy()
    b["net"] = b["buy"] - b["sell"]
    b["nm"] = b["branch"].map(norm)
    b["hit"] = b["nm"].isin(dtset) | ((b["rank"] == 1) & b["nm"].isin(DT_HQ))
    b["dtnet"] = b["net"].where(b["hit"], 0)
    b = b.sort_values(["date", "code", "rank"])
    g = b.groupby(["date", "code"], sort=False)
    ev = g["dtnet"].sum().rename("dt_lots").to_frame()
    first = g.head(1).set_index(["date", "code"])
    ev["top1"], ev["top1_dt"] = first["branch"], first["hit"].astype(bool)
    ev = ev.reset_index()
    v = vol.reindex(pd.MultiIndex.from_frame(ev[["date", "code"]])).values
    ev["dt_pct"] = np.where(v > 0, ev["dt_lots"] / v * 100, 0)
    # 名單文字只有今天要顯示
    tb = b[b["date"] == date]
    names = tb[tb["hit"]].groupby("code").apply(lambda x: "、".join(f"{r.branch}({r.net:,.0f})" for r in x.itertuples()))
    top3 = tb.groupby("code").apply(lambda x: "、".join(f"{r.branch} {r.net:,.0f}" for r in x.head(3).itertuples()))
    ev["dt_names"] = [names.get(c, "") if d == date else "" for d, c in zip(ev["date"], ev["code"])]
    ev["top3"] = [top3.get(c, "") if d == date else "" for d, c in zip(ev["date"], ev["code"])]
    if ev.empty:
        return {"error": "分點資料裡沒有漲停股"}
    ev = ev.join(lu[["name", "close", "volume", "streak", "vr", "lu_type", "brk", "ma_st", "vol_st", "r20",
                     "n_gap", "n_hi", "n_cl", "n_o2c"]], on=["date", "code"])
    ev["lots"] = ev["volume"] / 1000
    ev["dt_b"] = pd.cut(ev["dt_pct"], [-1e9, 0.01, 5, 10, 1e9], labels=["沒有隔日沖", "隔日沖 <5%", "隔日沖 5~10%", "隔日沖 ≧10%"])

    # 今天的漲停股
    td = ev[ev["date"] == date].sort_values("dt_pct", ascending=False)
    keep = ["code", "name", "close", "lots", "streak", "vr", "lu_type", "brk", "ma_st", "vol_st", "r20", "dt_lots", "dt_pct",
            "dt_names", "top1", "top1_dt", "top3"]
    today = [{k: (None if pd.isna(v) else (round(float(v), 2) if isinstance(v, (float, np.floating)) else (int(v) if isinstance(v, np.integer) else v)))
              for k, v in r.items()} for r in td[keep].to_dict("records")]

    # 今天：分點鎖漲停排行（買超的漲停股檔數、張數）
    bt = br[br["date"] == date].merge(td[["code", "name"]], on="code")
    bt = bt.assign(net=bt["buy"] - bt["sell"], nm=bt["branch"].map(norm))
    rank_today = []
    for nm, g in bt[bt["net"] > 0].groupby("branch"):
        rank_today.append({"branch": nm, "n": int(len(g)), "lots": float(g["net"].sum()), "dt": norm(nm) in dtset,
                           "stocks": "、".join(f"{r.name}({r.net:,.0f})" for r in g.sort_values("net", ascending=False).itertuples())})
    rank_today = sorted(rank_today, key=lambda x: (-x["n"], -x["lots"]))[:40]

    # 歷史：分點的「隔日沖指數」＝ 買超漲停股後，隔天出現在賣超名單的比例
    hist = ev[ev["date"] < date]
    nxt = {d: dates[dates.index(d) - 1] for d in dates[1:] if d in dates}   # dates 由新到舊
    bb = br.assign(net=br["buy"] - br["sell"]).merge(ev[["date", "code"]], on=["date", "code"])
    bb = bb[(bb["net"] >= 30) & (bb["date"] < date)]
    bb["nd"] = bb["date"].map(nxt)
    got = set(zip(brs["date"], brs["code"]))                       # 隔天有抓到分點資料的才算
    bb = bb[[(a, b) in got for a, b in zip(bb["nd"], bb["code"])]]
    sold = brs.rename(columns={"date": "nd"})[["nd", "code", "bid", "net_sell"]]
    bb = bb.merge(sold, on=["nd", "code", "bid"], how="left")
    bb["sold"] = bb["net_sell"].fillna(0) > 0
    bb["sold_pct"] = (bb["net_sell"].fillna(0) / bb["net"]).clip(upper=1.5)
    bb = bb.merge(ev[["date", "code", "n_gap", "n_cl"]], on=["date", "code"], how="left")
    score = []
    for nm, g in bb.groupby("branch"):
        if len(g) < 8:
            continue
        score.append({"branch": nm, "n": int(len(g)), "sold": round(g["sold"].mean() * 100, 1),
                      "sold_pct": round(g["sold_pct"].mean() * 100, 1), "lots": round(g["net"].mean()),
                      "n_gap": round(g["n_gap"].mean(), 2), "n_cl": round(g["n_cl"].mean(), 2), "dt": norm(nm) in dtset})
    score = sorted(score, key=lambda x: (-x["sold"], -x["n"]))

    # 歷史：隔日沖比重 × 技術面 → 隔天走勢
    def grp(by):
        h = hist.dropna(subset=["n_cl"])
        t = h.groupby(by, observed=True).agg(n=("code", "size"), gap=("n_gap", "mean"), hi=("n_hi", "mean"), cl=("n_cl", "mean"),
                                             o2c=("n_o2c", "mean"), red=("n_cl", lambda s: (s > 0).mean() * 100),
                                             lu=("n_cl", lambda s: (s >= 9.4).mean() * 100))
        t = t[t["n"] >= 15].reset_index()
        return [{k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else (int(v) if isinstance(v, (int, np.integer)) else str(v)))
                 for k, v in r.items()} for r in t.to_dict("records")]
    stats = {"n": int(hist["n_cl"].notna().sum()), "period": [hist["date"].min(), hist["date"].max()] if len(hist) else None,
             "by_dt": grp("dt_b"), "by_top1": grp(hist["top1_dt"].map({True: "買超第一名是隔日沖", False: "買超第一名不是隔日沖"}).rename("top1")),
             "by_vol": grp(["dt_b", "vol_st"]), "by_type": grp(["dt_b", "lu_type"]), "by_brk": grp(["dt_b", "brk"]),
             "by_ma": grp(["dt_b", "ma_st"]), "by_streak": grp(["dt_b", hist["streak"].clip(upper=3).map({1: "首板", 2: "二連板", 3: "三連板以上"}).rename("streak")])}
    return {"today": today, "rank_today": rank_today, "score": score[:40], "stats": stats, "dt_list": sorted(dtset), "hq": DT_HQ}


# ---------------- 三大法人：某一類法人的區間買賣超 ----------------
INST_NAMES = {"fi": "外資", "it": "投信", "dh": "自營商(避險)", "dp": "自營商(自行買賣)"}
MIN_ROWS = {"上市": 500, "上櫃": 300}      # 當天筆數少於這個 → 視為那個市場沒抓到
_rng_cache = {}


def inst_range(who="fi", start=None, end=None, n=100, etf=True):
    """每天市場合計（張、估算億）＋區間個股累計買超／賣超排行；同時標出哪幾天哪個市場缺資料"""
    if who not in INST_NAMES:
        return {"error": "不認得的法人類別"}
    con = connect()
    _init(con)
    stamp = con.execute("SELECT COUNT(*) FROM chips_fetched").fetchone()[0]   # 有新資料就重算
    key = ("range", who, start, end, n, etf)
    if _rng_cache.get(key, (None,))[0] == stamp:
        con.close()
        return _rng_cache[key][1]
    first, last = con.execute("SELECT MIN(date), MAX(date) FROM inst").fetchone()
    if not last:
        con.close()
        return {"error": "還沒有三大法人資料"}
    end = min(end or last, last)
    start = start or (dt.date.fromisoformat(end) - dt.timedelta(days=30)).isoformat()
    if start > end:
        start, end = end, start
    # 交易日以台積電(2330)＋inst 有資料的日子為準
    days = sorted({r[0] for r in con.execute("SELECT date FROM prices WHERE code='2330' AND date BETWEEN ? AND ? "
                                             "UNION SELECT DISTINCT date FROM inst WHERE date BETWEEN ? AND ?", (start, end, start, end))})
    d = pd.read_sql(f"SELECT i.date, i.code, i.{who} AS v, p.name, p.market, p.close FROM inst i "
                    "LEFT JOIN prices p ON p.code=i.code AND p.date=i.date WHERE i.date BETWEEN ? AND ?", con, params=(start, end))
    # 區間前一天收盤，算區間漲跌
    pc = pd.read_sql("SELECT code, close FROM prices WHERE date=(SELECT MAX(date) FROM prices WHERE code='2330' AND date<?)",
                     con, params=(start,)).set_index("code")["close"]
    lastpx = pd.read_sql("SELECT p.code, p.name, p.market, p.close FROM prices p JOIN (SELECT code, MAX(date) md FROM prices "
                         "WHERE date BETWEEN ? AND ? GROUP BY code) m ON m.code=p.code AND m.md=p.date", con, params=(start, end)).set_index("code")
    con.close()
    d["amt"] = d["v"] * d["close"] / 1e5                              # 張 × 價 × 1000 / 1e8 = 億
    agg = d[d["market"].notna()].groupby(["date", "market"]).agg(n=("v", "size"), lots=("v", "sum"), amt=("amt", "sum"))
    agg = {k: r for k, r in zip(agg.index, agg.itertuples(index=False))}
    daily = []
    for day in days:
        ok = {m: agg[(day, m)] for m, k in MIN_ROWS.items() if (day, m) in agg and agg[(day, m)].n >= k}
        row = {"date": day, "miss": [m for m in MIN_ROWS if m not in ok], "lots": None, "amt": None}
        if ok:
            row.update(lots=round(float(sum(r.lots for r in ok.values()))), amt=round(float(sum(r.amt for r in ok.values())), 2))
            for m, r in ok.items():
                row[m] = {"lots": round(float(r.lots)), "amt": round(float(r.amt), 2)}
        daily.append(row)

    g = d.groupby("code").agg(lots=("v", "sum"), amt=("amt", "sum"), days=("v", "size"), buy_days=("v", lambda s: int((s > 0).sum())))
    g = g.join(lastpx, how="left")
    g["chg"] = (g["close"] / pc.reindex(g.index) - 1) * 100
    g = g.reset_index()
    if not etf:
        g = g[~g["code"].map(_is_etf)]
    cols = ["code", "name", "market", "close", "chg", "lots", "amt", "days", "buy_days"]
    rec = lambda t: [{k: (None if pd.isna(v) else v) for k, v in zip(cols, r)} for r in t[cols].itertuples(index=False)]
    full = [x for x in daily if not x["miss"]]
    if len(_rng_cache) > 30:
        _rng_cache.clear()
    out = _rng_cache[key] = (stamp, None)
    out = _clean({"who": who, "name": INST_NAMES[who], "start": start, "end": end, "first": first, "last": last,
                   "daily": daily, "n_days": len(days), "n_full": len(full),
                   "tot": {"lots": round(sum(x["lots"] for x in full)), "amt": round(sum(x["amt"] for x in full), 2)},
                   "buy": rec(g[g["lots"] > 0].sort_values("lots", ascending=False).head(n)),
                   "sell": rec(g[g["lots"] < 0].sort_values("lots").head(n)),
                   "buy_amt": rec(g[g["amt"] > 0].sort_values("amt", ascending=False).head(n)),
                   "sell_amt": rec(g[g["amt"] < 0].sort_values("amt").head(n))})
    _rng_cache[key] = (stamp, out)
    return out
