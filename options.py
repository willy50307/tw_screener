"""
選擇權未平倉（期交所官方資料，每天下午 3~4 點後公布）
  opt_inst   三大法人 臺指選擇權 買權/賣權 × 買方/賣方 未平倉（口、千元）
  fut_inst   三大法人 臺股期貨 多空未平倉
  large_tr   大額交易人（前五大／前十大，全部交易人 cls=0、特定法人 cls=1）臺指選擇權買權/賣權、臺股期貨
  pc_ratio   買賣權成交量／未平倉量比
  opt_strike 各履約價未平倉量（一般交易時段）
  fut_tx     台指期日K（日盤、夜盤）
"""
import csv
import re
import datetime as dt
import io
import time

import numpy as np
import pandas as pd
import requests

from data import HEADERS, connect

T = "https://www.taifex.com.tw/cht/3/"
WHO = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign", "外資": "foreign"}


def _init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS opt_inst(date TEXT, cp TEXT, who TEXT, b_vol REAL, s_vol REAL, b_oi REAL, b_amt REAL, s_oi REAL, s_amt REAL,
                                        PRIMARY KEY(date, cp, who));
    CREATE TABLE IF NOT EXISTS fut_inst(date TEXT, prod TEXT, who TEXT, l_oi REAL, l_amt REAL, s_oi REAL, s_amt REAL, PRIMARY KEY(date, prod, who));
    CREATE TABLE IF NOT EXISTS large_tr(date TEXT, prod TEXT, exp TEXT, cls INTEGER, t5b REAL, t5s REAL, t10b REAL, t10s REAL, total REAL,
                                        PRIMARY KEY(date, prod, exp, cls));
    CREATE TABLE IF NOT EXISTS pc_ratio(date TEXT PRIMARY KEY, put_vol REAL, call_vol REAL, put_oi REAL, call_oi REAL);
    CREATE TABLE IF NOT EXISTS opt_strike(date TEXT, contract TEXT, strike REAL, cp TEXT, close REAL, volume REAL, oi REAL, settle REAL,
                                          expire TEXT, PRIMARY KEY(date, contract, strike, cp));
    CREATE TABLE IF NOT EXISTS fut_tx(date TEXT, session TEXT, contract TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
                                      settle REAL, PRIMARY KEY(date, session, contract));
    """)


def _n(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def _down(name, data):
    for k in range(3):
        try:
            r = requests.post(T + name, data=data, headers=HEADERS, timeout=180)
            rows = [x for x in csv.reader(io.StringIO(r.content.decode("big5", errors="replace"))) if len(x) > 3]
            return [x for x in rows if x[0][:4].isdigit()]
        except Exception as e:
            print("期交所下載失敗", name, e)
            time.sleep(5 * (k + 1))
    return None


def _chunks(since, until, days=28):
    d = since
    while d <= until:
        e = min(d + dt.timedelta(days=days), until)
        yield d, e
        d = e + dt.timedelta(days=1)


def _ds(r):
    return r[0].strip().replace("/", "-")


def fetch_range(con, a, b, strikes=True):
    q = {"queryStartDate": a.strftime("%Y/%m/%d"), "queryEndDate": b.strftime("%Y/%m/%d")}
    rows = _down("callsAndPutsDateDown", {**q, "commodityId": "TXO"})
    if rows:
        con.executemany("INSERT OR REPLACE INTO opt_inst VALUES(?,?,?,?,?,?,?,?,?)",
                        [(_ds(r), r[2].strip(), WHO.get(r[3].strip(), r[3].strip()), _n(r[4]), _n(r[6]), _n(r[10]), _n(r[11]), _n(r[12]), _n(r[13]))
                         for r in rows if r[3].strip() in WHO])
    for cid, prod in (("TXF", "TX"), ("MXF", "MTX")):
        rows = _down("futContractsDateDown", {**q, "commodityId": cid})
        if rows:
            con.executemany("INSERT OR REPLACE INTO fut_inst VALUES(?,?,?,?,?,?,?)",
                            [(_ds(r), prod, WHO.get(r[2].strip(), r[2].strip()), _n(r[9]), _n(r[10]), _n(r[11]), _n(r[12])) for r in rows if r[2].strip() in WHO])
    for name, pick in (("largeTraderOptDown", lambda r: r[1].strip() == "TXO"), ("largeTraderFutDown", lambda r: r[1].strip() == "TX")):
        rows = []       # 大額交易人含全部商品，檔案很大，一次下載太多天會被截斷 → 每 5 天一段
        for x, y in _chunks(a, b, 4):
            part = _down(name, {"queryStartDate": x.strftime("%Y/%m/%d"), "queryEndDate": y.strftime("%Y/%m/%d")})
            rows += part or []
        if rows:
            out = []
            for r in rows:
                if not pick(r):
                    continue
                if name == "largeTraderOptDown":
                    prod, rest = "TXO_" + ("C" if r[3].strip() == "買權" else "P"), r[4:]
                else:
                    prod, rest = "TX", r[3:]
                out.append((_ds(r), prod, rest[0].strip(), int(rest[1]), _n(rest[2]), _n(rest[3]), _n(rest[4]), _n(rest[5]), _n(rest[6])))
            con.executemany("INSERT OR REPLACE INTO large_tr VALUES(?,?,?,?,?,?,?,?,?)", out)
    rows = _down("pcRatioDown", q)
    if rows:
        con.executemany("INSERT OR REPLACE INTO pc_ratio VALUES(?,?,?,?,?)", [(_ds(r), _n(r[1]), _n(r[2]), _n(r[4]), _n(r[5])) for r in rows])
    rows = _down("futDataDown", {"down_type": "1", "commodity_id": "TX", "commodity_id2": "", **q})
    if rows:
        con.executemany("INSERT OR REPLACE INTO fut_tx VALUES(?,?,?,?,?,?,?,?,?)",
                        [(_ds(r), r[17].strip(), r[2].strip(), _n(r[3]), _n(r[4]), _n(r[5]), _n(r[6]), _n(r[9]), _n(r[10]))
                         for r in rows if len(r) > 17 and "/" not in r[2] and "W" not in r[2]])
    if strikes:
        rows = _down("optDataDown", {"down_type": "1", "commodity_id": "TXO", **q})
        if rows:
            con.executemany("INSERT OR REPLACE INTO opt_strike VALUES(?,?,?,?,?,?,?,?,?)",
                            [(_ds(r), r[2].strip(), _n(r[3]), "C" if r[4].strip() == "買權" else "P", _n(r[8]), _n(r[9]), _n(r[11]), _n(r[10]), r[20].strip())
                             for r in rows if len(r) > 20 and r[17].strip() == "一般" and (_n(r[11]) or 0) > 0])
    con.commit()


def backfill_market(progress=None):
    """台指期日K從 1998/7 上市開始、加權指數從 1999/1 開始（已經有的不重抓）"""
    import ptt
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    first = con.execute("SELECT MIN(date) FROM fut_tx").fetchone()[0] or dt.date.today().isoformat()
    parts = list(_chunks(dt.date(1998, 7, 21), dt.date.fromisoformat(first)))
    for k, (a, b) in enumerate(parts, 1):
        progress["台指期歷史"] = [k, len(parts)]
        rows = _down("futDataDown", {"down_type": "1", "commodity_id": "TX", "commodity_id2": "",
                                     "queryStartDate": a.strftime("%Y/%m/%d"), "queryEndDate": b.strftime("%Y/%m/%d")})
        if rows:
            con.executemany("INSERT OR REPLACE INTO fut_tx VALUES(?,?,?,?,?,?,?,?,?)",
                            [(_ds(r), r[17].strip() or "一般", r[2].strip(), _n(r[3]), _n(r[4]), _n(r[5]), _n(r[6]), _n(r[9]), _n(r[10]))
                             for r in rows if len(r) > 17 and "/" not in r[2] and "W" not in r[2]])
            con.commit()
        time.sleep(1)
    have = con.execute("SELECT MIN(date) FROM taiex_k").fetchone()[0] if con.execute(
        "SELECT name FROM sqlite_master WHERE name='taiex_k'").fetchone() else None
    if not have or have > "1999-01-31":
        progress["加權指數歷史"] = "抓取中"
        ptt.update_taiex(con, dt.date(1999, 1, 1))
    con.close()


def _near_contracts(con):
    """每個交易日的近月合約（結算日當天仍是舊合約）"""
    f = pd.read_sql("SELECT date, contract FROM fut_tx WHERE session='一般' AND volume > 0 AND date >= '2025-01-01'", con)
    f = f[f["contract"].str.fullmatch(r"\d{6}")]
    last = f.groupby("contract")["date"].max()
    days = sorted(f["date"].unique())
    out = {}
    for d in days:
        live = last[last >= d]
        if len(live):
            out[d] = live.sort_values().index[0]
    return out, last


def fetch_ticks(progress=None, max_days=30):
    """期交所每日逐筆成交（近 30 個交易日）→ 台指期近月 5 分K、60 分K（含夜盤），存在 intraday（code='TX'）"""
    import zipfile
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    con.execute("""CREATE TABLE IF NOT EXISTS intraday(code TEXT, tf TEXT, ts INTEGER, open REAL, high REAL, low REAL,
                   close REAL, volume REAL, PRIMARY KEY(code, tf, ts))""")
    con.execute("CREATE TABLE IF NOT EXISTS tick_done(date TEXT PRIMARY KEY)")
    done = {r[0] for r in con.execute("SELECT date FROM tick_done")}
    near, last = _near_contracts(con)
    todo = [d for d in sorted(near)[-max_days:] if d not in done]
    for k, d in enumerate(todo, 1):
        progress["台指期分K"] = [k, len(todo)]
        try:
            r = requests.get(f"https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{d.replace('-', '_')}.zip",
                             headers=HEADERS, timeout=120)
            if r.content[:2] != b"PK":
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0]).decode("big5", errors="replace")
        except Exception as e:
            print("逐筆下載失敗", d, e)
            continue
        c = near[d]
        rows = [x.split(",") for x in raw.splitlines()[1:] if x.startswith("20") and ",TX " in x]
        t = pd.DataFrame([(x[0], x[3].strip().zfill(6), float(x[4]), float(x[5])) for x in rows if x[2].strip() == c and x[6].strip() == "-"],
                         columns=["d", "t", "p", "q"])
        if t.empty:
            continue
        ts = pd.to_datetime(t["d"] + t["t"], format="%Y%m%d%H%M%S")
        t["ts"] = ts
        for tf, rule in (("5", "5min"), ("60", "60min")):
            # 時間標在每根K棒的開始；日盤 08:45 起算、夜盤 15:00 起算
            g = t.set_index("ts").groupby(pd.Grouper(freq=rule, origin=ts.iloc[0].normalize() + pd.Timedelta(minutes=45)))
            b = pd.DataFrame({"open": g["p"].first(), "high": g["p"].max(), "low": g["p"].min(), "close": g["p"].last(), "volume": g["q"].sum() / 2})
            b = b.dropna()
            secs = ((b.index - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64")
            con.executemany("INSERT OR REPLACE INTO intraday VALUES('TX',?,?,?,?,?,?,?)",
                            [(tf, int(s_), r_.open, r_.high, r_.low, r_.close, r_.volume * 1000) for s_, r_ in zip(secs, b.itertuples())])
        con.execute("INSERT OR REPLACE INTO tick_done VALUES(?)", (d,))
        con.commit()
        time.sleep(0.5)
    con.close()


def fetch_opt_ticks(progress=None, max_days=30):
    """期交所「選擇權每筆成交」（只保留 30 個交易日）：原始檔存到 data/opt_ticks，
    臺指選擇權依「成交價跟前一筆比漲跌」判斷主動買／主動賣，統計到 opt_tick（每天、合約、履約價、買賣權）"""
    import os
    import zipfile
    from settings import BASE
    progress = {} if progress is None else progress
    folder = os.path.join(BASE, "data", "opt_ticks")
    os.makedirs(folder, exist_ok=True)
    con = connect()
    _init(con)
    con.execute("""CREATE TABLE IF NOT EXISTS opt_tick(date TEXT, contract TEXT, strike REAL, cp TEXT, buy REAL, sell REAL, unk REAL, n INTEGER,
                   PRIMARY KEY(date, contract, strike, cp))""")
    con.execute("CREATE TABLE IF NOT EXISTS opt_tick_done(date TEXT PRIMARY KEY)")
    done = {r[0] for r in con.execute("SELECT date FROM opt_tick_done")}
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM fut_tx WHERE session='一般' ORDER BY date DESC LIMIT ?", (max_days,))]
    todo = sorted(d for d in days if d not in done)
    for k, d in enumerate(todo, 1):
        progress["選擇權逐筆"] = [k, len(todo)]
        fn = os.path.join(folder, f"OptionsDaily_{d.replace('-', '_')}.zip")
        if not os.path.exists(fn):
            try:
                r = requests.get(f"https://www.taifex.com.tw/file/taifex/Dailydownload/OptionsDailydownloadCSV/OptionsDaily_{d.replace('-', '_')}.zip",
                                 headers=HEADERS, timeout=180)
            except Exception as e:
                print("選擇權逐筆下載失敗", d, e)
                continue
            if r.content[:2] != b"PK":
                continue
            open(fn, "wb").write(r.content)
            time.sleep(0.5)
        z = zipfile.ZipFile(fn)
        rows = []
        for line in z.read(z.namelist()[0]).decode("big5", errors="replace").splitlines():
            if ",    TXO" not in line and ", TXO" not in line:
                continue
            x = [v.strip() for v in line.split(",")]
            if len(x) < 8 or x[1] != "TXO":
                continue
            try:
                rows.append((x[3], float(x[2]), x[4], x[5].zfill(6), float(x[6]), float(x[7]) / 2, x[8] if len(x) > 8 else ""))   # 每筆成交買賣方各列一次 → 除以 2
            except ValueError:
                continue
        if not rows:
            continue
        t = pd.DataFrame(rows, columns=["contract", "strike", "cp", "time", "price", "qty", "auction"])
        t["seq"] = range(len(t))
        g = t.groupby(["contract", "strike", "cp"], sort=False)
        diff = g.price.diff()
        sign = np.sign(diff).replace(0, np.nan)
        sign = sign.groupby([t.contract, t.strike, t.cp]).ffill()          # 平盤成交沿用上一筆方向
        sign[t.auction != ""] = np.nan                                        # 開盤集合競價不判斷
        t["buy"] = np.where(sign > 0, t.qty, 0)
        t["sell"] = np.where(sign < 0, t.qty, 0)
        t["unk"] = np.where(sign.isna(), t.qty, 0)
        a = t.groupby(["contract", "strike", "cp"]).agg(buy=("buy", "sum"), sell=("sell", "sum"), unk=("unk", "sum"), n=("qty", "size")).reset_index()
        con.executemany("INSERT OR REPLACE INTO opt_tick VALUES(?,?,?,?,?,?,?,?)",
                        [(d, r.contract, r.strike, r.cp, r.buy, r.sell, r.unk, int(r.n)) for r in a.itertuples()])
        con.execute("INSERT OR REPLACE INTO opt_tick_done VALUES(?)", (d,))
        con.commit()
    con.close()


def update(since=None, strikes_since=None, progress=None):
    """預設只補最近幾天；第一次（資料庫沒有）從 2024 年開始，履約價明細從 2026/5 開始"""
    progress = {} if progress is None else progress
    con = connect()
    _init(con)
    today = dt.date.today()
    last = con.execute("SELECT MAX(date) FROM opt_inst").fetchone()[0]
    since = since or (dt.date.fromisoformat(last) - dt.timedelta(days=5) if last else dt.date(2024, 1, 1))
    slast = con.execute("SELECT MAX(date) FROM opt_strike").fetchone()[0]
    strikes_since = strikes_since or (dt.date.fromisoformat(slast) - dt.timedelta(days=5) if slast else dt.date(2026, 5, 1))
    parts = list(_chunks(min(since, strikes_since), today))
    for k, (a, b) in enumerate(parts, 1):
        progress["選擇權"] = [k, len(parts)]
        fetch_range(con, a, b, strikes=b >= strikes_since)
        time.sleep(1)
    try:                                   # 美股指數（判斷夜盤用）
        import yfinance as yf
        for sym in ("^GSPC", "^IXIC", "^SOX", "^DJI"):
            h = yf.download(sym, period="10d", progress=False, auto_adjust=False)
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.get_level_values(0)
            con.execute("CREATE TABLE IF NOT EXISTS us_idx(sym TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, PRIMARY KEY(sym, date))")
            con.executemany("INSERT OR REPLACE INTO us_idx VALUES(?,?,?,?,?,?)",
                            [(sym, i.date().isoformat(), float(r.Open), float(r.High), float(r.Low), float(r.Close)) for i, r in h.iterrows()])
        con.commit()
    except Exception as e:
        print("美股更新失敗", e)
    try:
        fetch_opt_ticks(progress)
    except Exception as e:
        print("選擇權逐筆更新失敗", e)
    try:                                   # 期貨逐筆也存下來（選擇權頁 › 歷史資料要用；期交所只留 30 個交易日）
        import optpage
        optpage.keep_fut_zips()
    except Exception as e:
        print("期貨逐筆保存失敗", e)
    try:                                   # 選擇權最後結算價（樂透回測要用）
        import optmodel
        optmodel.update_fsp()
    except Exception as e:
        print("最後結算價更新失敗", e)
    try:
        fetch_ticks(progress)
    except Exception as e:
        print("台指期分K更新失敗", e)
    try:                                   # 加權指數日K（每天補最近一個月）
        import ptt
        ptt.update_taiex(con, today - dt.timedelta(days=10))
    except Exception as e:
        print("加權指數更新失敗", e)
    con.close()
    _cache.clear()


def status():
    con = connect()
    _init(con)
    r = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM opt_inst").fetchone()
    s = con.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM opt_strike").fetchone()
    con.close()
    return {"inst": r, "strike": s}


# ---------------- 分析 ----------------
_cache = {}

GROUPS = [("foreign", "外資"), ("dealer", "自營商"), ("trust", "投信"), ("t10x", "十大交易人（非特定法人）"),
          ("t10s", "十大特定法人"), ("t10", "十大交易人"), ("t5", "五大交易人")]


def _series(con):
    """每天每個身份的：買Call、賣Call、買Put、賣Put 未平倉口數，台指期淨部位"""
    oi = pd.read_sql("SELECT * FROM opt_inst", con)
    fi = pd.read_sql("SELECT * FROM fut_inst", con)
    lt = pd.read_sql("SELECT * FROM large_tr WHERE exp IN ('999999', '666666')", con)
    cols = ["t5b", "t5s", "t10b", "t10s"]
    w = lt[lt.exp == "666666"].set_index(["date", "prod", "cls"])[cols]
    lt = lt[lt.exp == "999999"].set_index(["date", "prod", "cls"])
    lt[cols] = lt[cols].sub(w.reindex(lt.index).fillna(0))        # 扣掉週選（每週到期，數字跳動大）
    lt = lt.reset_index()
    out = {}
    for who in ("foreign", "dealer", "trust"):
        o = oi[oi.who == who]
        c, p = o[o.cp == "CALL"].set_index("date"), o[o.cp == "PUT"].set_index("date")
        f = fi[(fi.who == who) & (fi["prod"] == "TX")].set_index("date")
        m = fi[(fi.who == who) & (fi["prod"] == "MTX")].set_index("date")
        out[who] = pd.DataFrame({"bc": c.b_oi, "sc": c.s_oi, "bp": p.b_oi, "sp": p.s_oi,
                                 "bc_amt": c.b_amt, "sc_amt": c.s_amt, "bp_amt": p.b_amt, "sp_amt": p.s_amt,
                                 "fut": f.l_oi - f.s_oi + ((m.l_oi - m.s_oi) / 4).reindex(f.index).fillna(0)})
    for key, cls, top in (("t10", 0, "t10"), ("t5", 0, "t5"), ("t10s", 1, "t10")):
        d = {}
        for prod, (b, s) in (("TXO_C", ("bc", "sc")), ("TXO_P", ("bp", "sp")), ("TX", ("fl", "fs"))):
            x = lt[(lt["prod"] == prod) & (lt.cls == cls)].set_index("date")
            d[b], d[s] = x[top + "b"], x[top + "s"]
        df = pd.DataFrame(d)
        df["fut"] = df.pop("fl") - df.pop("fs")
        out[key] = df
    out["t10x"] = out["t10"][["bc", "sc", "bp", "sp", "fut"]] - out["t10s"][["bc", "sc", "bp", "sp", "fut"]]
    return {k: v.sort_index() for k, v in out.items()}


def _tx(con):
    f = pd.read_sql("SELECT * FROM fut_tx WHERE session='一般' AND close IS NOT NULL", con)
    f = f.sort_values("volume").groupby("date").tail(1).set_index("date").sort_index()   # 每天成交量最大的月份＝近月
    n = pd.read_sql("SELECT * FROM fut_tx WHERE session='盤後' AND close IS NOT NULL", con)
    n = n.sort_values("volume").groupby("date").tail(1).set_index("date").sort_index()
    return f, n


def _read(g, w, s, tx, settle=()):
    """一個身份在 w 天內的變化 → 白話解讀。主要看淨部位（買方 − 賣方），比較不受到期結算影響"""
    s = s.dropna(subset=["bc", "sc", "bp", "sp"])
    if len(s) <= w:
        return None
    a, b = s.iloc[-1 - w], s.iloc[-1]
    d = {k: float(b[k] - a[k]) for k in ("bc", "sc", "bp", "sp", "fut") if pd.notna(b.get(k)) and pd.notna(a.get(k))}
    nc0, nc1, np0, np1 = a.bc - a.sc, b.bc - b.sc, a.bp - a.sp, b.bp - b.sp
    dnc, dnp = float(nc1 - nc0), float(np1 - np0)
    thc = max(500, (a.bc + a.sc) * 0.08)
    thp = max(500, (a.bp + a.sp) * 0.08)
    px0, px1 = tx.get(s.index[-1 - w]), tx.get(s.index[-1])
    pch = (px1 / px0 - 1) * 100 if px0 and px1 else None
    crossed = [x for x in settle if s.index[-1 - w] < x <= s.index[-1]]
    notes, score = [], 0
    call_sell, call_cover = dnc < -thc, dnc > thc
    put_sell, put_cover = dnp < -thp, dnp > thp
    if call_sell and put_sell:
        notes.append("<b>雙賣</b>：淨賣 Call、淨賣 Put 同時增加 → 預期區間震盪，上下都不容易突破")
    else:
        if call_sell:
            notes.append("淨<b>賣 Call</b> 增加 → 認為漲不上去（上方壓力加重）"); score -= 1
        if call_cover:
            notes.append(("淨買 Call 增加（<b>賣 Call 回補</b>／加碼買 Call）" if d.get("sc", 0) < 0 else "淨<b>買 Call</b> 增加（押多）")
                         + ("，指數同步上漲，有軋空突破的味道" if pch and pch > 1 else "")); score += 1.5
        if put_sell:
            notes.append("淨<b>賣 Put</b> 增加 → 認為跌不下去（下方支撐）"); score += 1
        if put_cover:
            notes.append(("淨買 Put 增加（<b>賣 Put 回補</b>／加碼買 Put）" if d.get("sp", 0) < 0 else "淨<b>買 Put</b> 增加（避險或押空）")
                         + ("，指數同步下跌要小心" if pch and pch < -1 else "")); score -= 1.5
    if "fut" in d and abs(d["fut"]) >= max(800, abs(float(a["fut"])) * 0.05):
        notes.append(f"台指期淨部位{'增加' if d['fut'] > 0 else '減少'} {abs(d['fut']):,.0f} 口（{'偏多' if d['fut'] > 0 else '偏空'}）")
        score += 1 if d["fut"] > 0 else -1
    view = "區間震盪" if call_sell and put_sell else "偏多" if score >= 1.5 else "偏空" if score <= -1.5 else "中性"
    return {"group": g, "days": w, "chg": {k: round(v) for k, v in d.items()}, "dnc": round(dnc), "dnp": round(dnp),
            "nc": round(float(nc1)), "np": round(float(np1)), "notes": notes or ["部位變化不大"], "score": score, "view": view,
            "pch": None if pch is None else round(pch, 2), "settle": crossed}


def _ncdf(x):
    """標準常態累積分布（Abramowitz-Stegun 近似，誤差 < 1e-7）"""
    a = np.abs(x) / np.sqrt(2)
    t = 1 / (1 + 0.3275911 * a)
    erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return 0.5 * (1 + np.sign(x) * erf)


def _iv(F, K, T, P, call):
    """Black-76 隱含波動率（二分法，向量化）"""
    lo, hi = np.full(len(K), 0.01), np.full(len(K), 3.0)
    sq = np.sqrt(T)
    for _ in range(50):
        v = (lo + hi) / 2
        d1 = (np.log(F / K) + 0.5 * v * v * T) / (v * sq)
        d2 = d1 - v * sq
        price = np.where(call, F * _ncdf(d1) - K * _ncdf(d2), K * _ncdf(-d2) - F * _ncdf(-d1))
        up = price > P
        hi, lo = np.where(up, v, hi), np.where(up, lo, v)
    iv = (lo + hi) / 2
    intrinsic = np.where(call, np.maximum(F - K, 0), np.maximum(K - F, 0))
    return np.where((P > intrinsic + 0.5) & (iv > 0.015) & (iv < 2.9), iv, np.nan)


def _flow(s, fx):
    """每天每個履約價：未平倉變化 × 隱含波動率變化 → 推估是賣方還是買方新增
      未平倉增加＋IV 下降 → 賣方主動新增；未平倉增加＋IV 上升 → 買方追價
      未平倉減少＋IV 上升 → 賣方回補；未平倉減少＋IV 下降 → 買方平倉"""
    s = s.copy()
    s["prem"] = s["settle"].where(s["settle"] > 0, s["close"])
    s["F"] = s["date"].map(fx)
    exp = pd.to_datetime(s["expire"], format="%Y%m%d", errors="coerce")
    s["T"] = ((exp - pd.to_datetime(s["date"])).dt.days + 0.3).clip(lower=0.3) / 365
    ok = s["prem"].notna() & (s["prem"] >= 1.5) & s["F"].notna()
    s["iv"] = np.nan
    s.loc[ok, "iv"] = _iv(s.loc[ok, "F"].values, s.loc[ok, "strike"].values, s.loc[ok, "T"].values, s.loc[ok, "prem"].values,
                          (s.loc[ok, "cp"] == "C").values)
    s = s.sort_values("date")
    g = s.groupby(["contract", "strike", "cp"])
    s["doi"] = g["oi"].diff()
    s["div"] = g["iv"].diff()
    # 扣掉同一天、同一個合約整體的 IV 變化（大盤恐慌時全部 IV 一起上升，不代表每個履約價都是買方）
    s["div"] = s["div"] - s.groupby(["date", "contract"])["div"].transform("median")
    # 權利金太低（快到期或很價外）算不出 IV → 改用權利金漲跌判斷
    dprem = g["prem"].diff()
    fb = s["div"].isna() & dprem.notna() & (dprem != 0)
    s.loc[fb, "div"] = np.sign(dprem[fb]) * 1e-6
    new = g["oi"].cumcount() == 0
    s.loc[new, "doi"] = s.loc[new, "oi"]          # 新出現的履約價：全部算新增（IV 變化未知）
    d, v = s["doi"].fillna(0), s["div"]
    s["sell_add"] = np.where((d > 0) & (v < 0), d, 0)
    s["buy_add"] = np.where((d > 0) & (v > 0), d, 0)
    s["sell_cover"] = np.where((d < 0) & (v > 0), -d, 0)
    s["buy_exit"] = np.where((d < 0) & (v < 0), -d, 0)
    s["unk"] = np.where(v.isna() | (v == 0), d, 0)
    s["seller"] = s["sell_add"] - s["sell_cover"]          # 推估賣方淨新增
    return s


def _strikes(con, date, px, fx=None):
    """各履約價未平倉＋推估賣方。月選從「上個月結算日」累計到現在；週選從上市那天累計"""
    ymd = date.replace("-", "")
    allc = pd.read_sql("SELECT DISTINCT contract, expire FROM opt_strike WHERE date <= ?", con, params=(date,))
    mon = allc[allc.contract.str.fullmatch(r"\d{6}")].drop_duplicates("contract")
    live_m = mon[mon.expire >= ymd].sort_values("expire")
    if live_m.empty:
        return None
    near = live_m.iloc[0]
    prev_m = mon[mon.expire < near.expire].sort_values("expire")
    base = (f"{prev_m.expire.iloc[-1][:4]}-{prev_m.expire.iloc[-1][4:6]}-{prev_m.expire.iloc[-1][6:]}" if len(prev_m)
            else (dt.date.fromisoformat(date) - dt.timedelta(days=35)).isoformat())          # 上個月結算日
    s = pd.read_sql("SELECT contract, strike, cp, oi, close, settle, expire, date FROM opt_strike WHERE date >= ? AND date <= ?", con,
                    params=((dt.date.fromisoformat(base) - dt.timedelta(days=4)).isoformat(), date))
    if s.empty:
        return None
    days = sorted(s.date.unique())
    today = s[s.date == days[-1]]
    if today.empty:
        return None
    exp = today.groupby(["contract", "expire"]).oi.sum().reset_index()
    exp = exp[exp.expire >= ymd]
    is_m = exp.contract.str.fullmatch(r"\d{6}")
    monthly = exp[is_m].sort_values("expire")
    weekly = exp[~is_m & (exp.oi > 300)].sort_values("expire")
    expire_of = dict(zip(exp.contract, exp.expire))
    fl = _flow(s, fx) if fx is not None else None
    d_prev = days[-2] if len(days) >= 2 else days[0]
    fl1 = fl[fl.date == days[-1]] if fl is not None else None
    first_day = s.groupby("contract").date.min().to_dict()
    res = {"date": days[-1], "px": px, "base": base, "prev": d_prev, "contracts": [], "near": near.contract}

    def oi_at(d, sel, index):
        x = s[(s.date == d) & s.contract.isin(sel)].groupby(["strike", "cp"]).oi.sum().unstack(fill_value=0)
        return x.reindex(index=index, columns=["C", "P"], fill_value=0)

    def build(name, sel, kind):
        # 累計起點：月選＝上個月結算日；週選＝上市第一天之前（＝全部未平倉）
        if kind == "weekly":
            b0 = None
            bname = f"{first_day.get(sel[0], days[0])} 上市以來"
        else:
            b0 = max([d for d in days if d <= base] or [days[0]])
            bname = f"{base} 結算後累計" + ("（月選＋期間所有週選）" if kind == "month_all" else "")
        t = today[today.contract.isin(sel)].groupby(["strike", "cp"]).oi.sum().unstack(fill_value=0).reindex(columns=["C", "P"], fill_value=0)
        if kind == "month_all":     # 已到期的週選今天沒有未平倉，但履約價要列出來
            idx = s[s.contract.isin(sel)].strike.unique()
            t = t.reindex(sorted(set(t.index) | set(idx)), fill_value=0)
        cum = t - (oi_at(b0, sel, t.index) if b0 else 0)
        c1 = t - oi_at(d_prev, sel, t.index)
        win = fl[(fl.date > (b0 or "0000")) & fl.contract.isin(sel)] if fl is not None else None
        f = win.groupby(["strike", "cp"])[["seller", "sell_add", "sell_cover", "buy_add"]].sum() if win is not None and len(win) else None
        part = lambda cp: f.xs(cp, level="cp") if f is not None and cp in f.index.get_level_values("cp") else pd.DataFrame(columns=["seller", "sell_add", "sell_cover", "buy_add"])
        sel_c, sel_p = part("C"), part("P")
        g1 = fl1[fl1.contract.isin(sel)].groupby(["strike", "cp"]).seller.sum() if fl1 is not None else pd.Series(dtype=float)
        s1 = {(k, cp): int(v) for (k, cp), v in g1.items()}
        prem = {}
        if len(sel) == 1:
            prem = {(r.strike, r.cp): (r.settle if r.settle and r.settle > 0 else r.close) for r in today[today.contract == sel[0]].itertuples()}
        near_ = t[(t.index >= px * 0.9) & (t.index <= px * 1.1)]
        calls = near_[near_.index >= px].C.sort_values(ascending=False).head(3)
        puts = near_[near_.index <= px].P.sort_values(ascending=False).head(3)
        ks = t.index.values
        pain = [((np.maximum(k - ks, 0) * t.C.values).sum() + (np.maximum(ks - k, 0) * t.P.values).sum()) for k in ks]
        lv = lambda d, lo, hi, asc: [{"k": float(k), "seller": int(r.seller), "add": int(r.sell_add), "cover": int(r.sell_cover), "buy": int(r.buy_add),
                                      "oi": int((t.C if d is sel_c else t.P).get(k, 0))}
                                     for k, r in d[(d.index >= lo) & (d.index <= hi)].sort_values("seller", ascending=asc).head(3).iterrows() if r.seller > 0]
        cover = lambda d, lo, hi: [{"k": float(k), "cover": int(r.sell_cover)} for k, r in d[(d.index >= lo) & (d.index <= hi)]
                                   .sort_values("sell_cover", ascending=False).head(3).iterrows() if r.sell_cover > 300]
        sv = lambda d, k: int(d.seller.get(k, 0)) if len(d) else 0
        rng = t[(t.index >= px * 0.92) & (t.index <= px * 1.08)]
        cumC = cum.C if hasattr(cum, "C") else t.C
        cumP = cum.P if hasattr(cum, "P") else t.P
        return {"name": name, "contracts": sel, "kind": kind, "base_name": bname, "expire": expire_of.get(sel[0]) if len(sel) == 1 else None,
                "s_res": lv(sel_c, px, px * 1.1, False), "s_sup": lv(sel_p, px * 0.9, px, False),
                "c_cover": cover(sel_c, px * 0.98, px * 1.08), "p_cover": cover(sel_p, px * 0.92, px * 1.02),
                "res": [{"k": float(k), "oi": int(v), "ch5": int(cumC.get(k, 0))} for k, v in calls.items()],
                "sup": [{"k": float(k), "oi": int(v), "ch5": int(cumP.get(k, 0))} for k, v in puts.items()],
                "max_pain": float(ks[int(np.argmin(pain))]) if len(ks) else None,
                "add_c": [], "cut_c": [], "add_p": [], "cut_p": [],
                "dist": [{"k": float(k), "c": int(r.C), "p": int(r.P), "dc": int(cumC.get(k, 0)), "dp": int(cumP.get(k, 0)),
                          "sc": sv(sel_c, k), "sp": sv(sel_p, k), "c1": int(c1.C.get(k, 0)), "p1": int(c1.P.get(k, 0)),
                          "cw": int(cumC.get(k, 0)), "pw": int(cumP.get(k, 0)), "s1c": s1.get((k, "C"), 0), "s1p": s1.get((k, "P"), 0),
                          "swc": sv(sel_c, k), "swp": sv(sel_p, k), "cpx": prem.get((k, "C")), "ppx": prem.get((k, "P"))} for k, r in rng.iterrows()]}
    fmt_exp = lambda e: f"{e[4:6]}/{e[6:]}"
    # 最前面：近月月選＋上次結算後到現在的所有週選（含已到期）
    span = sorted(set(s[(s.date > base) & (s.expire <= near.expire)].contract))
    wk_span = [c for c in span if not re.fullmatch(r"\d{6}", c)]
    if wk_span:
        res["contracts"].append(build(f"{near.contract} 月選＋期間週選（{len(wk_span)} 檔，含已到期）", sorted(set(span) | {near.contract}), "month_all"))
    for _, r in monthly.iterrows():
        tag = "（月選，" + fmt_exp(r.expire) + " 結算" + ("，今天" if r.expire == ymd else "") + "）"
        res["contracts"].append(build(r.contract + tag, [r.contract], "monthly"))
    for _, r in weekly.iterrows():
        typ = "週三" if "W" in r.contract else "週五" if "F" in r.contract else "週選"
        res["contracts"].append(build(f"{r.contract}（{typ}週選，{fmt_exp(r.expire)} 到期）", [r.contract], "weekly"))
    allsel = list(monthly.contract) + list(weekly.contract)
    if len(allsel) > 1:
        res["contracts"].append(build("合計（全部未到期：" + "、".join(allsel) + "）", allsel, "all"))
    return res


def report(date=None):
    con = connect()
    _init(con)
    stamp = con.execute("SELECT MAX(date), COUNT(*) FROM opt_inst").fetchone()
    key = (date, stamp)
    if key in _cache:
        con.close()
        return _cache[key]
    ser = _series(con)
    tx, night = _tx(con)
    dates = list(ser["foreign"].dropna(subset=["bc"]).index)
    if not dates:
        con.close()
        return {"error": "還沒有選擇權資料"}
    date = date if date in dates else dates[-1]
    i = dates.index(date)
    ser = {k: v.loc[:date] for k, v in ser.items()}
    px = float(tx["close"].get(date) or tx["close"].iloc[-1])
    out = {"date": date, "dates": dates[-120:][::-1], "px": px}

    # ① 大戶分類日籌碼
    tab = []
    for g, nm in GROUPS:
        s = ser[g]
        if date not in s.index:
            continue
        row = {"g": g, "name": nm}
        for k in ("bc", "sc", "bp", "sp", "fut"):
            v = s[k]
            row[k] = None if pd.isna(v.get(date)) else float(v[date])
            for w in (1, 5, 10):
                row[f"{k}_{w}"] = float(v.iloc[-1] - v.iloc[-1 - w]) if len(v) > w and pd.notna(v.iloc[-1 - w]) else None
        if g in ("foreign", "dealer", "trust"):
            r = s.loc[date]
            row["bull_amt"] = round(float((r.bc_amt - r.sc_amt) - (r.bp_amt - r.sp_amt)) / 1e5, 2)   # 千元 → 億
        tab.append(row)
    out["table"] = tab
    pc = pd.read_sql("SELECT * FROM pc_ratio ORDER BY date", con).set_index("date").loc[:date]
    out["pc"] = [{"date": d, "oi": round(r.put_oi / r.call_oi * 100, 1), "vol": round(r.put_vol / r.call_vol * 100, 1)} for d, r in pc.tail(20).iterrows()]

    # ② ③ 一週、兩週變化 → 解讀
    settle = sorted({f"{e[:4]}-{e[4:6]}-{e[6:]}" for (e,) in con.execute(
        "SELECT DISTINCT expire FROM opt_strike WHERE length(contract)=6")})                  # 月選結算日
    reads = {}
    for w in (5, 10, 20):
        reads[w] = [x for x in (_read(nm, w, ser[g], tx["close"], settle) for g, nm in GROUPS if g in ("foreign", "dealer", "t10x", "t10s")) if x]
    out["settle"] = [x for x in settle if x >= dates[max(0, i - 30)]]
    out["reads"] = reads
    t = tx.loc[:date]
    out["tx"] = {"close": px, "chg5": round((px / float(t.close.iloc[-6]) - 1) * 100, 2) if len(t) > 5 else None,
                 "chg10": round((px / float(t.close.iloc[-11]) - 1) * 100, 2) if len(t) > 10 else None,
                 "hi20": float(t.high.tail(20).max()), "lo20": float(t.low.tail(20).min()),
                 "night": None}
    nx = night[night.index > date]
    if len(nx):
        out["tx"]["night"] = {"date": nx.index[0], "close": float(nx.close.iloc[0]), "chg": round((float(nx.close.iloc[0]) / px - 1) * 100, 2)}

    # 圖：台指期日K＋外資／十大 選擇權部位（近 90 天）
    t90 = t.tail(90)
    out["kbars"] = [[d, r.open, r.high, r.low, r.close, r.volume] for d, r in t90.iterrows()]
    out["lines"] = {g: {k: [[d, None if pd.isna(v) else float(v)] for d, v in ser[g][k].loc[t90.index[0]:].items()] for k in ("bc", "sc", "bp", "sp", "fut")}
                    for g in ("foreign", "t10s", "t10x", "dealer")}

    # ④ 支撐壓力
    out["strikes"] = _strikes(con, date, px, tx["close"])
    out["summary"] = _summary(out)
    con.close()
    _cache.clear()
    _cache[key] = out
    return out


def _summary(o):
    """綜合判斷：外資、十大特定法人、十大非特定法人 的一週／兩週／一個月變化"""
    W = {5: 1.0, 10: 0.7, 20: 0.4}
    score, ranges = 0, 0
    for w, k in W.items():
        for x in o["reads"].get(w, []):
            if x["group"] == "自營商":
                continue
            score += x["score"] * k
            ranges += (x["view"] == "區間震盪") * k
    view = "偏多" if score >= 2 else "偏空" if score <= -2 else ("區間震盪" if ranges >= 1 else "方向不明")
    st = o.get("strikes") or {}
    main = next((c for c in (st.get("contracts") or []) if c.get("kind") == "monthly"), None)     # 支撐壓力用「月選本身」（已到期週選不代表現在的部位）
    lines = []
    if main and (main.get("s_res") or main.get("s_sup")):
        f = lambda xs: "、".join(f"<b>{x['k']:,.0f}</b>（賣方淨新增 {x['seller']:,} 口）" for x in xs) or "無明顯新增"
        lines.append(f"<b>{main['name']}</b>｜{main['base_name']}")
        lines.append(f"🔴 壓力（<b>推估賣方累計新增最多的 Call</b>）：{f(main['s_res'])}")
        lines.append(f"🟢 支撐（<b>推估賣方累計新增最多的 Put</b>）：{f(main['s_sup'])}")
        if main["c_cover"]:
            lines.append("⚠ Call 賣方回補（壓力鬆動，偏多訊號）：" + "、".join(f"{x['k']:,.0f}（回補 {x['cover']:,} 口）" for x in main["c_cover"]))
        if main["p_cover"]:
            lines.append("⚠ Put 賣方回補（支撐鬆動，偏空訊號）：" + "、".join(f"{x['k']:,.0f}（回補 {x['cover']:,} 口）" for x in main["p_cover"]))
    # 月選今天／明天結算 → 另外列下一個月選
    nxt = [c for c in (st.get("contracts") or []) if c.get("kind") == "monthly" and c is not main]
    if main and main.get("expire") and nxt and main["expire"] <= (dt.date.fromisoformat(o["date"]) + dt.timedelta(days=2)).strftime("%Y%m%d"):
        c2 = nxt[0]
        lines.append(f"{main['contracts'][0]} 即將結算，下一個月選 {c2['contracts'][0]}：賣方集中在 Call "
                     + ("、".join(f"{x['k']:,.0f}" for x in c2["s_res"][:2]) or "–") + "／Put " + ("、".join(f"{x['k']:,.0f}" for x in c2["s_sup"][:2]) or "–"))
    if main and main["res"] and main["sup"]:
        lines.append(f"參考｜總未平倉最多：上方壓力 <b>{main['res'][0]['k']:,.0f}</b>（Call 未平倉 {main['res'][0]['oi']:,} 口）"
                     + (f"、次壓 {main['res'][1]['k']:,.0f}" if len(main["res"]) > 1 else "")
                     + f"；下方支撐 <b>{main['sup'][0]['k']:,.0f}</b>（Put 未平倉 {main['sup'][0]['oi']:,} 口）"
                     + (f"、次撐 {main['sup'][1]['k']:,.0f}" if len(main["sup"]) > 1 else "")
                     + f"；最大痛點 {main['max_pain']:,.0f}")
    nxt = [x for x in o.get("settle", []) if x >= o["date"]]
    if nxt:
        lines.append(f"下次月選結算：{nxt[0]}（結算前後未平倉會大量減少，數字變化不一定是主動進出）")
    return {"view": view, "score": round(score, 1), "lines": lines}
