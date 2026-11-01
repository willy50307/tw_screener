"""
權證分點（盤後）＋ 盤中 12:00 快照
  warrant_info    權證代號 → 標的、發行商、認購/認售、履約價（證交所 t187ap37_L ＋ 名稱解析）
  warrant_daily   每天每檔權證成交（證交所 MI_INDEX 0999、櫃買 otc WW）
  warrant_broker  熱門權證的分點買賣超（MoneyDJ，每檔前 15 名買超／賣超）
                  每天抓：成交金額前 N 名 ＋ 前 5 天有「單一分點大量買進」的權證（追蹤是不是隔天就賣）
  warrant_snap    盤中快照（證交所 MIS 即時報價，12:00 開始分批抓）
分點分類（慢慢累積）：大量買進後幾天賣出 → 1 天＝隔日沖、2~5 天＝短波段、超過 5 天＝長波段
"""
import datetime as dt
import re
import threading
import time

import numpy as np
import pandas as pd
import requests

import broker
from data import HEADERS, _num, connect

_lock = threading.Lock()
TOP_N = 300                      # 每天抓分點的權證數（成交金額排名）
BIG_LOTS, BIG_PCT, BIG_AMT = 100, 8.0, 30.0      # 大量買進：買超 ≥100 張、佔該權證成交量 ≥8%、金額 ≥30 萬
ISSUER_HQ = {   # 權證名稱裡的發行商簡稱 → 發行商自己的分點（造市，不是真的買盤）
    "元大": ["元大證券", "元大"], "凱基": ["凱基"], "群益": ["群益金鼎"], "富邦": ["富邦證券", "富邦"], "統一": ["統一"],
    "國票": ["國票證券", "國票"], "永豐": ["永豐金證券", "永豐金"], "台新": ["台新"], "兆豐": ["兆豐", "兆豐證券"], "中信": ["中國信託"],
    "元富": ["元富"], "第一": ["第一金", "第一金證券"], "華南": ["華南永昌"], "康和": ["康和", "康和證券"], "宏遠": ["宏遠", "宏遠證券"], "亞東": ["亞東", "亞東證券"],
    "國泰": ["國泰證券", "國泰"], "玉山": ["玉山"], "日盛": ["日盛", "富邦證券"], "摩根": ["摩根大通"], "麥格理": ["港商麥格理"],
    "法興": ["法國興業"], "匯豐": ["香港上海匯豐"], "中國信託": ["中國信託"], "永豐金": ["永豐金證券"]}


FOREIGN_BR = {"美林", "摩根大通", "台灣摩根士丹利", "美商高盛", "新加坡商瑞銀", "港商野村", "花旗環球", "港商麥格理", "瑞士信貸",
              "法國興業", "香港上海匯豐", "大和國泰", "法銀巴黎", "德意志", "港商德意志", "台灣匯立", "港商法國興業"}


def is_corp(branch):
    """券商總公司（名稱沒有「-分點」、也不是外資券商）：常常是自營、避險或造市部位"""
    return "-" not in (branch or "") and branch not in FOREIGN_BR


def _init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS warrant_info(code TEXT PRIMARY KEY, name TEXT, market TEXT, cp TEXT, und_code TEXT, und_name TEXT,
                                            issuer TEXT, strike REAL, last_trade TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS warrant_daily(date TEXT, code TEXT, close REAL, chg REAL, volume REAL, amount REAL, und_code TEXT,
                                             PRIMARY KEY(date, code));
    CREATE TABLE IF NOT EXISTS warrant_broker(date TEXT, code TEXT, side TEXT, rank INTEGER, bid TEXT, bhid TEXT, branch TEXT,
                                              buy REAL, sell REAL, PRIMARY KEY(date, code, side, rank));
    CREATE TABLE IF NOT EXISTS warrant_done(date TEXT, code TEXT, PRIMARY KEY(date, code));
    CREATE TABLE IF NOT EXISTS warrant_snap(ts TEXT, code TEXT, und_code TEXT, price REAL, ref REAL, volume REAL, amount REAL,
                                            und_chg REAL, PRIMARY KEY(ts, code));
    CREATE INDEX IF NOT EXISTS wb_branch ON warrant_broker(branch, date);
    CREATE INDEX IF NOT EXISTS wd_und ON warrant_daily(und_code, date);
    """)


def _get(url, params):
    for k in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            r.encoding = "utf-8"
            return r.json()
        except Exception:
            time.sleep(4 * (k + 1))
    return None


# ---------------- 基本資料 ----------------
def _issuer(name):
    m = re.search(r"(元大|凱基|群益|富邦|統一|國票|永豐金|永豐|台新|兆豐|中信|元富|第一|華南|康和|宏遠|亞東|國泰|玉山|日盛|摩根|麥格理|法興|匯豐)", name or "")
    return m.group(1) if m else ""


def update_info(con):
    names = {n: c for c, n in con.execute("SELECT code, name FROM prices WHERE date = (SELECT MAX(date) FROM prices) AND length(code)=4")}
    rows = []
    for r in _get("https://openapi.twse.com.tw/v1/opendata/t187ap37_L", None) or []:
        und = r.get("標的證券/指數", "").strip()
        rows.append((r["權證代號"].strip(), r["權證簡稱"].strip(), "上市", "P" if "售" in r.get("權證類型", "") else "C", names.get(und, ""), und,
                     _issuer(r["權證簡稱"]), _num(r.get("最新履約價格(元)/履約指數")), r.get("最後交易日", ""), dt.date.today().isoformat()))
    with _lock:
        con.executemany("INSERT OR REPLACE INTO warrant_info VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    return len(rows)


def _guess_und(name, names_sorted):
    """上櫃權證：從名稱開頭比對股票簡稱（取最長的）"""
    for n, c in names_sorted:
        if name.startswith(n):
            return c, n
    return "", ""


# ---------------- 每日成交 ----------------
def fetch_daily(con, d):
    ds = d.isoformat()
    out = []
    j = _get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX", {"date": d.strftime("%Y%m%d"), "type": "0999", "response": "json"})
    if j is None:
        return None
    for t in (j.get("tables") or []) if j.get("stat") == "OK" else []:
        f = t.get("fields") or []
        if "證券代號" in f and "成交金額" in f and ("標的代號" in f or "權證" in str(t.get("title", ""))):
            i = {k: f.index(k) for k in f}
            g = lambda r, k: str(r[i[k]] if k in i and r[i[k]] is not None else "").strip()
            for r in t["data"]:
                amt = _num(g(r, "成交金額")) or 0
                sign = -1 if "-" in g(r, "漲跌(+/-)") else 1
                out.append((ds, g(r, "證券代號"), _num(g(r, "收盤價")), sign * (_num(g(r, "漲跌價差")) or 0),
                            (_num(g(r, "成交股數")) or 0) / 1000, amt, g(r, "標的代號")))
    j2 = _get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc", {"date": d.strftime("%Y/%m/%d"), "type": "WW", "response": "json"})
    if j2 and j2.get("date") == d.strftime("%Y%m%d"):
        info = {c: u for c, u in con.execute("SELECT code, und_code FROM warrant_info WHERE market='上櫃'")}
        names = sorted({(n, c) for c, n in con.execute("SELECT code, name FROM prices WHERE date=(SELECT MAX(date) FROM prices) AND length(code)=4")},
                       key=lambda x: -len(x[0]))
        new_info = []
        for t in j2.get("tables") or []:
            f = [x.strip() for x in (t.get("fields") or [])]
            if "代號" not in f:
                continue
            i = {k: f.index(k) for k in f}
            for r in t["data"]:
                code, name = r[0].strip(), r[1].strip()
                amt = _num(r[i["成交金額(元)"]]) or 0
                if code not in info:
                    uc, un = _guess_und(name, names)
                    info[code] = uc
                    new_info.append((code, name, "上櫃", "P" if "售" in name else "C", uc, un, _issuer(name), None, "", ds))
                cv = str(r[i["漲跌"]] or "")
                ch = _num(cv.replace("+", "")) if cv not in ("---", "") else 0
                out.append((ds, code, _num(r[i["收盤"]]), ch or 0, (_num(r[i["成交股數"]]) or 0) / 1000, amt, info.get(code, "")))
        with _lock:
            con.executemany("INSERT OR IGNORE INTO warrant_info VALUES(?,?,?,?,?,?,?,?,?,?)", new_info)
    with _lock:
        con.executemany("INSERT OR REPLACE INTO warrant_daily VALUES(?,?,?,?,?,?,?)", [r for r in out if r[5] > 0])
        con.commit()
    return len(out)


# ---------------- 分點 ----------------
def _hq(issuer):
    return set(ISSUER_HQ.get(issuer, []))


def _big_events(con, dates):
    """這幾天「非發行商分點」大量買進的 (date, code, branch)"""
    if not dates:
        return pd.DataFrame()
    q = ",".join("?" * len(dates))
    b = pd.read_sql(f"""SELECT b.date, b.code, b.branch, b.buy, b.sell, d.volume, d.close, i.issuer FROM warrant_broker b
                        JOIN warrant_daily d ON d.date=b.date AND d.code=b.code LEFT JOIN warrant_info i ON i.code=b.code
                        WHERE b.side='B' AND b.date IN ({q})""", con, params=dates)
    if b.empty:
        return b
    b["net"] = b.buy - b.sell
    b["amt"] = b.net * b.close * 1000 / 1e4          # 萬元
    b["pct"] = b.net / b.volume.replace(0, np.nan) * 100
    b["is_hq"] = [br in _hq(iss) for br, iss in zip(b.branch, b.issuer)]
    return b[(~b.is_hq) & (b.net >= BIG_LOTS) & (b.pct >= BIG_PCT) & (b.amt >= BIG_AMT)]


def update(days_back=0, top_n=TOP_N, progress=None, sleep=0.25):
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    if con.execute("SELECT COUNT(*) FROM warrant_info").fetchone()[0] == 0 or days_back == 0:
        progress["msg"] = "權證基本資料…"
        update_info(con)
    today = dt.date.today()
    trade = [r[0] for r in con.execute("SELECT DISTINCT date FROM prices WHERE code='2330' AND date >= ? ORDER BY date",
                                        ((today - dt.timedelta(days=days_back + 10)).isoformat(),))]
    trade = [d for d in trade if d >= (today - dt.timedelta(days=days_back)).isoformat()]
    have = {r[0] for r in con.execute("SELECT DISTINCT date FROM warrant_daily")}
    sess = requests.Session()
    for k, ds in enumerate(trade, 1):
        progress["權證"] = [k, len(trade)]
        d = dt.date.fromisoformat(ds)
        if ds not in have:
            if fetch_daily(con, d) is None:
                continue
            time.sleep(2)
        top = [r[0] for r in con.execute("SELECT code FROM warrant_daily WHERE date=? ORDER BY amount DESC LIMIT ?", (ds, top_n))]
        # 追蹤：前 5 個交易日有大量買進的權證（看隔天是不是賣掉）
        i = trade.index(ds)
        prev = trade[max(0, i - 5):i]
        ev = _big_events(con, prev)
        track = set(ev.code) if len(ev) else set()
        traded = {r[0] for r in con.execute("SELECT code FROM warrant_daily WHERE date=?", (ds,))}
        codes = [c for c in dict.fromkeys(top + sorted(track)) if c in traded]
        done = {r[0] for r in con.execute("SELECT code FROM warrant_done WHERE date=?", (ds,))}
        todo = [c for c in codes if c not in done]
        for n, c in enumerate(todo, 1):
            progress["權證分點"] = [n, len(todo), ds]
            h = broker._get("/z/zc/zco/zco.djhtm", {"a": c, "e": ds, "f": ds})
            if h is None:
                continue
            _, rows = broker._parse_stock(h)
            with _lock:
                con.executemany("INSERT OR REPLACE INTO warrant_broker VALUES(?,?,?,?,?,?,?,?,?)",
                                [(ds, c, r["side"], r["rank"], r["bid"], r["bhid"], r["branch"], r["buy"], r["sell"]) for r in rows])
                con.execute("INSERT OR REPLACE INTO warrant_done VALUES(?,?)", (ds, c))
                con.commit()
            time.sleep(sleep)
    con.close()
    _cache.clear()


def status():
    con = connect()
    _init(con)
    r = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM warrant_daily").fetchone()
    b = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date), COUNT(DISTINCT code) FROM warrant_broker").fetchone()
    s = con.execute("SELECT MAX(ts) FROM warrant_snap").fetchone()[0]
    con.close()
    return {"daily": r, "broker": b, "snap": s}


# ---------------- 分析 ----------------
_cache = {}


def _events_all(con, since):
    b = pd.read_sql("""SELECT b.date, b.code, b.side, b.branch, b.bid, b.bhid, b.buy, b.sell, d.volume, d.close, d.amount, d.chg,
                              i.name, i.issuer, i.cp, i.und_code, i.und_name
                       FROM warrant_broker b JOIN warrant_daily d ON d.date=b.date AND d.code=b.code
                       LEFT JOIN warrant_info i ON i.code=b.code WHERE b.date >= ?""", con, params=(since,))
    if b.empty:
        return b
    b["net"] = b.buy - b.sell
    b["amt"] = b.net * b.close * 1000 / 1e4
    b["pct"] = b.net.abs() / b.volume.replace(0, np.nan) * 100
    b["is_hq"] = [br in _hq(iss) for br, iss in zip(b.branch, b.issuer)]
    b["corp"] = b.branch.map(is_corp)
    return b


def _profiles(b, dates):
    """分點類型：大量買進後，幾天內在同一檔權證出現賣超（賣掉一半以上）"""
    idx = {d: i for i, d in enumerate(dates)}
    big = b[(b.side == "B") & ~b.is_hq & (b.net >= BIG_LOTS) & (b.pct >= BIG_PCT) & (b.amt >= BIG_AMT)]
    sells = b[(b.side == "S") & ~b.is_hq]
    sell_map = {}
    for r in sells.itertuples():
        sell_map.setdefault((r.code, r.branch), []).append((r.date, -r.net))
    seen = {(r.code, r.date) for r in b[["code", "date"]].drop_duplicates().itertuples()}
    out = []
    for r in big.itertuples():
        i0 = idx.get(r.date)
        if i0 is None:
            continue
        hold, observed = None, 0
        for k in range(1, 11):
            if i0 + k >= len(dates):
                break
            dk = dates[i0 + k]
            if (r.code, dk) not in seen:          # 那天沒抓到這檔權證的分點 → 不確定
                continue
            observed = k
            sold = sum(v for d_, v in sell_map.get((r.code, r.branch), []) if d_ == dk)
            if sold >= r.net * 0.5:
                hold = k
                break
        out.append({"date": r.date, "code": r.code, "branch": r.branch, "net": r.net, "amt": r.amt, "hold": hold, "observed": observed})
    E = pd.DataFrame(out)
    if E.empty:
        return E, []
    E["type"] = np.select([E.hold == 1, E.hold.between(2, 5), (E.hold > 5) | (E.hold.isna() & (E.observed >= 5))],
                          ["隔日沖", "短波段", "長波段"], "觀察中")
    prof = []
    for br, g in E.groupby("branch"):
        done = g[g.type != "觀察中"]
        if len(done) < 3:
            continue
        cnt = done.type.value_counts()
        share = {t: float(cnt.get(t, 0) / len(done) * 100) for t in ("隔日沖", "短波段", "長波段")}
        main = max(share, key=share.get)
        prof.append({"branch": br, "corp": is_corp(br), "n": int(len(g)), "n_done": int(len(done)), **share, "type": main if share[main] >= 50 else "混合",
                     "amt": float(g.amt.sum()), "avg_hold": float(done.hold.dropna().mean()) if done.hold.notna().any() else None})
    prof.sort(key=lambda x: -x["n"])
    return E, prof


def _no_nan(o):
    """NaN → None（瀏覽器的 JSON.parse 不接受 NaN）"""
    if isinstance(o, dict):
        return {k: _no_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_no_nan(v) for v in o]
    if isinstance(o, float) and o != o:
        return None
    return o


def report(date=None):
    con = connect()
    _init(con)
    stamp = con.execute("SELECT COUNT(*) FROM warrant_done").fetchone()[0]
    key = (date, stamp)
    if key in _cache:
        con.close()
        return _cache[key]
    dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM warrant_broker ORDER BY date")]
    if not dates:
        con.close()
        return {"error": "還沒有權證分點資料，請按「補抓歷史」"}
    date = date if date in dates else dates[-1]
    b = _events_all(con, dates[0])
    E, prof = _profiles(b, dates)
    ptype = {p["branch"]: p["type"] for p in prof}
    day = b[b.date == date]
    und_names = {c: n for c, n in con.execute("SELECT code, name FROM prices WHERE date=(SELECT MAX(date) FROM prices) AND length(code)=4")}
    wd = pd.read_sql("SELECT d.*, i.name, i.cp FROM warrant_daily d LEFT JOIN warrant_info i ON i.code=d.code WHERE d.date=?", con, params=(date,))
    con.close()
    # ① 單一分點大量進場（今天）
    big = day[(day.side == "B") & ~day.is_hq & (day.net >= BIG_LOTS) & (day.pct >= BIG_PCT) & (day.amt >= BIG_AMT)].copy()
    # 連續買進天數（同分點同權證）、之後有沒有賣
    bb = b[(b.side == "B") & (b.net > 0)]
    keyset = {(r.code, r.branch, r.date) for r in bb[["code", "branch", "date"]].itertuples(index=False)}
    di = {d: i for i, d in enumerate(dates)}

    def streak(code, br, d):
        n, i = 0, di[d]
        while i >= 0 and (code, br, dates[i]) in keyset:
            n += 1; i -= 1
        return n
    big["streak"] = [streak(r.code, r.branch, r.date) for r in big.itertuples()]
    big["ptype"] = big.branch.map(ptype).fillna("資料累積中")
    events = [{"code": r.code, "name": r.name, "und": r.und_code, "und_name": und_names.get(r.und_code, r.und_name), "cp": r.cp,
               "branch": r.branch, "bid": r.bid, "bhid": r.bhid, "net": float(r.net), "amt": float(r.amt), "pct": float(r.pct),
               "close": r.close, "chg": r.chg, "streak": int(r.streak), "ptype": r.ptype, "corp": bool(r.corp)} for r in big.sort_values("amt", ascending=False).itertuples()]
    # ② 依標的彙整
    wd["und_name"] = wd.und_code.map(und_names)
    g = wd.groupby("und_code")
    und = pd.DataFrame({"amt_c": wd[wd.cp == "C"].groupby("und_code").amount.sum(), "amt_p": wd[wd.cp == "P"].groupby("und_code").amount.sum(),
                        "n": g.size()}).fillna(0)
    bigu = big.groupby("und_code").agg(big_amt=("amt", "sum"), big_n=("code", "size"))
    und = und.join(bigu).fillna({"big_amt": 0, "big_n": 0})
    und["name"] = und.index.map(und_names)
    und = und[und.index != ""].sort_values(["big_amt", "amt_c"], ascending=False)
    unds = [{"code": c, "name": r["name"], "amt_c": float(r.amt_c / 1e4), "amt_p": float(r.amt_p / 1e4), "n": int(r.n),
             "big_amt": float(r.big_amt), "big_n": int(r.big_n)} for c, r in und.head(60).iterrows()]
    # ③ 各標的熱門權證的分點（前 60 個標的）
    detail = {}
    for c in [u["code"] for u in unds[:40]]:
        x = day[day.und_code == c]
        rows = []
        for w, gw in x.groupby("code"):
            top = gw.sort_values("net", ascending=False)
            buys = top[top.side == "B"].head(3)
            sells = top[top.side == "S"].sort_values("net").head(2)
            rows.append({"code": w, "name": gw.name.iloc[0], "cp": gw.cp.iloc[0], "close": gw.close.iloc[0], "amt": float(gw.amount.iloc[0] / 1e4),
                         "buys": [{"branch": r.branch, "bid": r.bid, "bhid": r.bhid, "net": float(r.net), "amt": float(r.amt), "hq": bool(r.is_hq)} for r in buys.itertuples()],
                         "sells": [{"branch": r.branch, "net": float(r.net), "amt": float(r.amt), "hq": bool(r.is_hq)} for r in sells.itertuples()]})
        detail[c] = sorted(rows, key=lambda r: -r["amt"])[:12]
    # ④ 分點類型
    cnt = E.type.value_counts().to_dict() if len(E) else {}
    out = {"date": date, "dates": dates[::-1][:120], "events": events, "unds": unds, "detail": detail, "profiles": prof[:80],
           "ev_count": {k: int(v) for k, v in cnt.items()}, "n_dates": len(dates),
           "rule": f"大量買進＝非發行商分點買超 ≥{BIG_LOTS} 張、佔該權證成交量 ≥{BIG_PCT:.0f}%、金額 ≥{BIG_AMT:.0f} 萬"}
    out = _no_nan(out)      # 新上市權證還沒有 warrant_info → name/cp 是 NaN，JSON 會壞掉
    _cache.clear()
    _cache[key] = out
    return out


def branch_history(branch, days=120):
    """某分點在權證的每日買賣（依標的、權證）"""
    con = connect()
    _init(con)
    since = (dt.date.today() - dt.timedelta(days=days * 1.5)).isoformat()
    b = _events_all(con, since)
    con.close()
    x = b[(b.branch == branch)]
    if x.empty:
        return {"branch": branch, "rows": []}
    rows = [{"date": r.date, "code": r.code, "name": r.name, "und": r.und_code, "und_name": r.und_name, "cp": r.cp, "net": float(r.net),
             "amt": float(r.amt), "pct": float(r.pct), "close": r.close} for r in x.sort_values(["date", "amt"], ascending=[False, False]).itertuples()]
    by_und = x.groupby("und_code").agg(und_name=("und_name", "first"), net_amt=("amt", "sum"), days=("date", "nunique")).sort_values("net_amt", ascending=False)
    return {"branch": branch, "rows": rows[:600],
            "by_und": [{"und": c, "und_name": r.und_name, "amt": float(r.net_amt), "days": int(r.days)} for c, r in by_und.head(30).iterrows()]}


# ---------------- 盤中 12:00 快照 ----------------
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def _mis(symbols):
    out = []
    sess = requests.Session()
    for i in range(0, len(symbols), 60):
        part = symbols[i:i + 60]
        for k in range(3):
            try:
                r = sess.get(MIS, params={"ex_ch": "|".join(part), "json": 1, "delay": 0}, headers=HEADERS, timeout=20)
                out += r.json().get("msgArray", [])
                break
            except Exception:
                time.sleep(2)
        time.sleep(0.5)
    return out


def snapshot(progress=None):
    """1. 抓全部普通股快照 → 挑熱門標的（漲 ≥3% 或成交金額前 30）2. 抓這些標的的所有權證快照"""
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    stocks = con.execute("SELECT code, market FROM prices WHERE date=(SELECT MAX(date) FROM prices) AND length(code)=4 AND substr(code,1,1)!='0'").fetchall()
    sym = [f"{'otc' if m == '上櫃' else 'tse'}_{c}.tw" for c, m in stocks]
    progress["msg"] = f"盤中快照：股票 {len(sym)} 檔"
    st = _mis(sym)
    S = []
    for x in st:
        z, y = _num(x.get("z")), _num(x.get("y"))
        if not z or not y:
            continue
        S.append({"code": x["c"], "chg": (z / y - 1) * 100, "amt": (_num(x.get("v")) or 0) * z * 1000})
    S = pd.DataFrame(S)
    if S.empty:
        con.close()
        return {"error": "抓不到即時報價（可能不是交易時間）"}
    hot = set(S[S.chg >= 3].code) | set(S.sort_values("amt", ascending=False).head(30).code)
    hot = list(S[S.code.isin(hot)].sort_values("amt", ascending=False).code)[:80]
    w = con.execute(f"SELECT code, market, und_code FROM warrant_info WHERE und_code IN ({','.join('?' * len(hot))})", hot).fetchall()
    progress["msg"] = f"盤中快照：熱門標的 {len(hot)} 檔、權證 {len(w)} 檔"
    ws = _mis([f"{'otc' if m == '上櫃' else 'tse'}_{c}.tw" for c, m, _ in w])
    und_of = {c: u for c, _, u in w}
    chg = dict(zip(S.code, S.chg))
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for x in ws:
        z = _num(x.get("z")) or _num((x.get("b") or "").split("_")[0]) or 0
        v = _num(x.get("v")) or 0
        if v <= 0:
            continue
        rows.append((ts, x["c"], und_of.get(x["c"], ""), z, _num(x.get("y")), v, v * z * 1000, chg.get(und_of.get(x["c"], ""))))
    with _lock:
        con.executemany("INSERT OR REPLACE INTO warrant_snap VALUES(?,?,?,?,?,?,?,?)", rows)
        con.commit()
    con.close()
    return {"ts": ts, "n_hot": len(hot), "n_warrants": len(rows)}


def snap_report(ts=None):
    con = connect()
    _init(con)
    ts = ts or con.execute("SELECT MAX(ts) FROM warrant_snap").fetchone()[0]
    if not ts:
        con.close()
        return {"error": "還沒有盤中快照（每天 12:00 自動抓）"}
    s = pd.read_sql("SELECT s.*, i.name, i.cp FROM warrant_snap s LEFT JOIN warrant_info i ON i.code=s.code WHERE s.ts=?", con, params=(ts,))
    prev = con.execute("SELECT MAX(date) FROM warrant_daily WHERE date < ?", (ts[:10],)).fetchone()[0]
    y = dict(con.execute("SELECT code, amount FROM warrant_daily WHERE date=?", (prev,)).fetchall()) if prev else {}
    names = {c: n for c, n in con.execute("SELECT code, name FROM prices WHERE date=(SELECT MAX(date) FROM prices) AND length(code)=4")}
    con.close()
    s["y_amt"] = s.code.map(y).fillna(0)
    s["x"] = s.amount / s.y_amt.replace(0, np.nan)
    s["wchg"] = (s.price / s.ref - 1) * 100
    s["big"] = (s.amount >= 3e6) & ((s.x >= 2) | (s.y_amt == 0))
    u = s.groupby("und_code").agg(amt_c=("amount", lambda v: v[s.loc[v.index, "cp"] == "C"].sum()), amt_p=("amount", lambda v: v[s.loc[v.index, "cp"] == "P"].sum()),
                                  n_big=("big", "sum"), und_chg=("und_chg", "first")).sort_values("amt_c", ascending=False)
    unds = [{"code": c, "name": names.get(c, c), "amt_c": float(r.amt_c / 1e4), "amt_p": float(r.amt_p / 1e4), "n_big": int(r.n_big),
             "chg": None if pd.isna(r.und_chg) else float(r.und_chg)} for c, r in u.head(40).iterrows()]
    tops = s[s.big].sort_values("amount", ascending=False).head(60)
    warr = [{"code": r.code, "name": r.name, "und": r.und_code, "und_name": names.get(r.und_code, r.und_code), "cp": r.cp, "price": r.price,
             "wchg": None if pd.isna(r.wchg) else float(r.wchg), "amt": float(r.amount / 1e4), "y_amt": float(r.y_amt / 1e4),
             "x": None if pd.isna(r.x) else float(r.x), "lots": float(r.volume)} for r in tops.itertuples()]
    return {"ts": ts, "prev": prev, "unds": unds, "warrants": warr,
            "rule": "大單進場＝到目前成交金額 ≥300 萬，而且是昨天全天的 2 倍以上（或昨天沒成交）"}
