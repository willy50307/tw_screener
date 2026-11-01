"""
主力進出（券商分點）：資料來源 MoneyDJ（富邦 e 點通）
  個股：某天／近 N 日 買超、賣超前 15 名分點
  分點 × 個股：某分點在某檔股票每天的買進、賣出（一次可抓好幾年）
都是點的時候才去查，查過的存進資料庫（broker、broker_hist），30 分鐘內重複查直接用快取
"""
import datetime as dt
import re
import threading
import time

import pandas as pd
import requests

from data import HEADERS, _num, connect

DJ = "https://fubon-ebrokerdj.fbs.com.tw"
_sess = requests.Session()
_cache = {}
_lock = threading.Lock()
TTL = 1800


def _init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS broker(date TEXT, code TEXT, side TEXT, rank INTEGER, bid TEXT, branch TEXT,
                                      buy REAL, sell REAL, PRIMARY KEY(date, code, side, rank));
    CREATE TABLE IF NOT EXISTS broker_id(bid TEXT PRIMARY KEY, bhid TEXT, branch TEXT);
    CREATE TABLE IF NOT EXISTS broker_hist(code TEXT, bid TEXT, date TEXT, buy REAL, sell REAL, PRIMARY KEY(code, bid, date));
    """)


def _get(path, params=None):
    for k in range(3):
        try:
            r = _sess.get(DJ + path, params=params, headers=HEADERS, timeout=20)
            r.encoding = "big5"
            return r.text
        except Exception:
            time.sleep(2 * (k + 1))
    return None


_TD = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
_A = re.compile(r'b=([^&"]+)&(?:amp;)?BHID=([^"&]+)"[^>]*>([^<]+)</a>', re.I)
_strip = lambda s: re.sub(r"<[^>]+>|&nbsp;", "", s).strip()


def _parse_stock(h):
    k = h.find("買超券商")
    if k < 0:
        return None, []
    m = re.search(r"最後更新日：\s*(\d{4})/(\d{2})/(\d{2})", h)
    last = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    out, rank = [], {"B": 0, "S": 0}
    for tr in re.split(r"<TR[^>]*>", h[k:h.find("</table>", k)], flags=re.I)[1:]:
        cells = _TD.findall(tr)
        for side, cs in (("B", cells[0:5]), ("S", cells[5:10])):
            if len(cs) < 5:
                continue
            a = _A.search(cs[0])
            if not a:
                continue
            rank[side] += 1
            buy, sell = _num(_strip(cs[1])) or 0, _num(_strip(cs[2])) or 0
            out.append({"side": side, "rank": rank[side], "bid": a.group(1), "bhid": a.group(2), "branch": a.group(3).strip(),
                        "buy": buy, "sell": sell, "net": buy - sell, "pct": _strip(cs[4])})
    return last, out


def _trade_days(con, until, n):
    return [r[0] for r in con.execute("SELECT DISTINCT date FROM prices WHERE date <= ? AND code='2330' ORDER BY date DESC LIMIT ?",
                                      (until, n))]


def stock(code, days=1):
    """某檔股票 近 days 日 主力進出（買超／賣超前 15）"""
    key = ("s", code, days)
    c = _cache.get(key)
    if c and time.time() - c[0] < TTL:
        return c[1]
    h = _get("/z/zc/zco/zco.djhtm", {"a": code})            # 不帶日期＝最新一日
    if h is None:
        return {"error": "連不上資料來源，請稍後再試"}
    last, rows = _parse_stock(h)
    if last is None:
        return {"error": "這檔沒有分點資料（ETF、權證或剛上市的可能沒有）"}
    con = connect()
    _init(con)
    start = last
    if days > 1:
        td = _trade_days(con, last, days)
        start = td[-1] if td else last
        h = _get("/z/zc/zco/zco.djhtm", {"a": code, "e": start, "f": last})
        _, rows = _parse_stock(h or "")
    with _lock:
        con.executemany("INSERT OR REPLACE INTO broker_id VALUES(?,?,?)", [(r["bid"], r["bhid"], r["branch"]) for r in rows])
        if days == 1:
            con.executemany("INSERT OR REPLACE INTO broker VALUES(?,?,?,?,?,?,?,?)",
                            [(last, code, r["side"], r["rank"], r["bid"], r["branch"], r["buy"], r["sell"]) for r in rows])
        con.commit()
    con.close()
    out = {"code": code, "date": last, "start": start, "days": days,
           "buy": [r for r in rows if r["side"] == "B"], "sell": [r for r in rows if r["side"] == "S"]}
    _mark_dt(out)
    _cache[key] = (time.time(), out)
    return out


def mainforce(code, n=20):
    """每天的主力買賣超（張）＝ 買超前 15 名分點買超合計 − 賣超前 15 名分點賣超合計（跟 XQ、CMoney 一樣）
    資料來源：MoneyDJ K 線圖的資料檔，一次就有約 6 年（1440 個交易日）每天的主力買賣超，不用一天一天抓
    抓不到時退回資料庫裡存過的單日主力進出（broker 表）"""
    key = ("mf", code)
    c = _cache.get(key)
    if c and time.time() - c[0] < TTL:
        rows = c[1]
    else:
        rows = []
        d = _get("/Z/ZC/ZCW/CZKC1.djbcd", {"a": code, "b": "D", "c": 1440})
        try:
            cols = [x.split(",") for x in d.split(";")[0].strip().split(" ")]
            rows = [[t.replace("/", "-"), int(float(v))] for t, v in zip(cols[0], cols[15]) if v not in ("", "-")]
        except Exception:
            rows = []
        if rows:
            _cache[key] = (time.time(), rows)
        else:
            con = connect()
            _init(con)
            rows = [[a, int(b)] for a, b in con.execute(
                "SELECT date, SUM(buy - sell) FROM broker WHERE code=? GROUP BY date HAVING COUNT(*) >= 2 ORDER BY date", (code,))]
            con.close()
    if not rows:
        return {"code": code, "error": "這檔沒有主力買賣超資料", "rows": []}
    n = max(1, int(n or 20))
    s = pd.Series([v for _, v in rows]).rolling(n, min_periods=1).sum()
    return {"code": code, "n": n, "rows": [[t, v, int(x)] for (t, v), x in zip(rows, s)]}   # [日期, 當日主力買賣超, N日累計]


def _mark_dt(out):
    try:
        import chips
        dts = set(chips._dt_list())
        hq = set(chips.DT_HQ)
    except Exception:
        return
    for side in ("buy", "sell"):
        for r in out[side]:
            n = chips.norm(r["branch"])
            r["dt"] = n in dts or (n in hq and r["rank"] == 1 and side == "buy" and out["days"] == 1)


def hist(code, bid, bhid, years=1.0):
    """某分點在某檔股票每天的買賣超＋股價（畫圖用）"""
    end = dt.date.today()
    start = end - dt.timedelta(days=int(365 * years))
    key = ("h", code, bid, years)
    c = _cache.get(key)
    if c and time.time() - c[0] < TTL:
        return c[1]
    h = _get("/z/zc/zco/zco0/zco0.djhtm", {"A": code, "BHID": bhid, "b": bid, "C": 1, "D": start.isoformat(), "E": end.isoformat(), "ver": "V3"})
    if h is None:
        return {"error": "連不上資料來源，請稍後再試"}
    rows = re.findall(r"(\d{4})/(\d{2})/(\d{2})</TD>\s*<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>[\d,]+</TD>\s*<TD[^>]*>(-?[\d,]+)</TD>",
                      h, re.I)
    m = re.search(r"<title>([^<]*)</title>", h, re.I)
    con = connect()
    _init(con)
    name = con.execute("SELECT branch FROM broker_id WHERE bid=?", (bid,)).fetchone()
    data = [(f"{y}-{mo}-{d}", _num(b) or 0, _num(s) or 0) for y, mo, d, b, s, _ in rows]
    with _lock:
        con.executemany("INSERT OR REPLACE INTO broker_hist VALUES(?,?,?,?,?)", [(code, bid, *x) for x in data])
        con.commit()
    px = pd.read_sql("SELECT date, name, open, high, low, close FROM prices WHERE code=? AND date >= ? ORDER BY date", con,
                     params=(code, start.isoformat()))
    con.close()
    df = pd.DataFrame(data, columns=["date", "buy", "sell"])
    if len(df):
        px = px[px["date"] <= df["date"].max()]          # 資料來源還沒更新的日子不要畫
    px = px.merge(df, on="date", how="left").fillna({"buy": 0, "sell": 0})
    px["net"] = px["buy"] - px["sell"]
    px["cum"] = px["net"].cumsum()
    px["avgp"] = (px["high"] + px["low"] + 2 * px["close"]) / 4           # 當天均價估算
    out = {"code": code, "name": px["name"].iloc[-1] if len(px) else code, "bid": bid, "bhid": bhid,
           "branch": name[0] if name else bid, "years": years,
           "rows": [[r.date, r.close, r.buy, r.sell, r.net, r.cum, round(r.avgp, 2)] for r in px.itertuples()]}
    _cache[key] = (time.time(), out)
    return out
