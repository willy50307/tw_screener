"""
選擇權大分頁 › 歷史資料：用期交所「每筆成交」把某一天的選擇權、台指期還原成 1 分K
  data/opt_ticks/OptionsDaily_YYYY_MM_DD.zip   選擇權逐筆（options.fetch_opt_ticks 每天存）
  data/fut_ticks/Daily_YYYY_MM_DD.zip          期貨逐筆（這裡下載後保留）
  data/opt_min/*.pkl                            解析後的 1 分K 快取
期交所只保留最近 30 個交易日的逐筆，所以本機有存的才能回看更早的日子。
同一天的檔案也含前一晚夜盤（日期是前一天 15:00 之後、當天 00:00~05:00）。
"""
import datetime as dt
import io
import os
import re
import threading
import zipfile

import numpy as np
import pandas as pd
import requests

from data import HEADERS, connect
from settings import BASE

D_OPT = os.path.join(BASE, "data", "opt_ticks")
D_FUT = os.path.join(BASE, "data", "fut_ticks")
D_MIN = os.path.join(BASE, "data", "opt_min")
URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/"
_lock = threading.Lock()
_mem = {}


def _get_zip(folder, kind, pre, d):
    fn = os.path.join(folder, f"{pre}_{d.replace('-', '_')}.zip")
    if os.path.exists(fn):
        return fn
    os.makedirs(folder, exist_ok=True)
    try:
        r = requests.get(f"{URL}{kind}/{pre}_{d.replace('-', '_')}.zip", headers=HEADERS, timeout=180)
    except Exception as e:
        print("逐筆下載失敗", pre, d, e)
        return None
    if r.content[:2] != b"PK":
        return None
    with open(fn, "wb") as f:
        f.write(r.content)
    return fn


def opt_zip(d):
    return _get_zip(D_OPT, "OptionsDailydownloadCSV", "OptionsDaily", d)


def fut_zip(d):
    return _get_zip(D_FUT, "DailydownloadCSV", "Daily", d)


def _read_csv(fn, names):
    z = zipfile.ZipFile(fn)
    raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), encoding="big5", encoding_errors="replace", header=None, skiprows=1, names=names,
                     dtype=str, skipinitialspace=True, on_bad_lines="skip")
    for c in df.columns:
        df[c] = df[c].str.strip()
    return df[df["date"].str.match(r"^\d{8}$", na=False)]


def _bars(t, keys):
    """逐筆 → 1 分K（時間標在每分鐘開始，台北時間當成 UTC 存，跟 intraday 表一樣）"""
    t["m"] = (t["ts"] // 60) * 60
    g = t.groupby(keys + ["m"], sort=True)
    b = g.agg(o=("p", "first"), h=("p", "max"), l=("p", "min"), c=("p", "last"), v=("q", "sum")).reset_index()
    return b.rename(columns={"m": "ts"})


def _ts(t):
    x = pd.to_datetime(t["date"] + t["time"].str.zfill(6), format="%Y%m%d%H%M%S", errors="coerce")
    return ((x - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64")


def opt_min(d):
    """某個交易日（含前一晚夜盤）的臺指選擇權 1 分K：contract, strike, cp, ts, o, h, l, c, v"""
    key = ("o", d)
    if key in _mem:
        return _mem[key]
    pk = os.path.join(D_MIN, f"opt_{d}.pkl")
    if os.path.exists(pk):
        b = pd.read_pickle(pk)
    else:
        fn = opt_zip(d)
        if not fn:
            return None
        t = _read_csv(fn, ["date", "prod", "strike", "contract", "cp", "time", "p", "q", "auction"])
        t = t[t["prod"] == "TXO"].copy()
        t["strike"] = t["strike"].astype(float)
        t["p"] = t["p"].astype(float)
        t["q"] = t["q"].astype(float) / 2          # 買賣方各列一次
        t["ts"] = _ts(t)
        t = t.sort_values(["ts"], kind="stable")
        b = _bars(t, ["contract", "strike", "cp"])
        os.makedirs(D_MIN, exist_ok=True)
        b.to_pickle(pk)
    _mem[key] = b
    return b


def _near(con, d):
    """d 那天的台指期近月（結算日當天還是舊合約）"""
    r = con.execute("""SELECT contract FROM fut_tx WHERE session='一般' AND length(contract)=6 AND contract IN
                       (SELECT contract FROM fut_tx WHERE session='一般' GROUP BY contract HAVING MAX(date) >= ?)
                       AND date = ? ORDER BY contract LIMIT 1""", (d, d)).fetchone()
    return r[0] if r else None


def fut_min(d):
    """台指期近月 1 分K（含前一晚夜盤）。期交所已經沒有那天的逐筆 → 用資料庫裡的 5 分K"""
    key = ("f", d)
    if key in _mem:
        return _mem[key]
    pk = os.path.join(D_MIN, f"fut_{d}.pkl")
    src = "1"
    if os.path.exists(pk):
        b = pd.read_pickle(pk)
    else:
        con = connect()
        c = _near(con, d)
        fn = fut_zip(d)
        if fn and c:
            t = _read_csv(fn, ["date", "prod", "contract", "time", "p", "q", "near", "far", "auction"])
            t = t[(t["prod"] == "TX") & (t["contract"] == c)].copy()
            t["p"] = t["p"].astype(float)
            t["q"] = t["q"].astype(float) / 2
            t["ts"] = _ts(t)
            t = t.sort_values("ts", kind="stable")
            b = _bars(t, [])
            b["contract"] = c
            os.makedirs(D_MIN, exist_ok=True)
            b.to_pickle(pk)
        else:
            day0 = int((pd.Timestamp(d) - pd.Timedelta(hours=9) - pd.Timestamp("1970-01-01")).total_seconds())
            b = pd.read_sql("SELECT ts, open o, high h, low l, close c, volume/1000.0 v FROM intraday WHERE code='TX' AND tf='5' AND ts >= ? AND ts < ?",
                            con, params=(day0, day0 + 86400))
            b["contract"] = c
            src = "5"
        con.close()
    b.attrs["src"] = src
    _mem[key] = b
    return b


def _expire_map(con):
    return dict(con.execute("SELECT contract, MAX(expire) FROM opt_strike GROUP BY contract").fetchall())


def days():
    """可以回看的日子：本機有選擇權逐筆的 ＋ 期交所還能下載的（最近 30 個交易日）"""
    con = connect()
    trade = [r[0] for r in con.execute("SELECT DISTINCT date FROM fut_tx WHERE session='一般' ORDER BY date DESC LIMIT 45")]
    exp = _expire_map(con)
    con.close()
    have = {f[13:23].replace("_", "-") for f in os.listdir(D_OPT)} if os.path.isdir(D_OPT) else set()
    by_day = {}
    for c, e in exp.items():
        if e:
            by_day.setdefault(f"{e[:4]}-{e[4:6]}-{e[6:]}", []).append(c)
    ds = sorted(set(trade[:30]) | have, reverse=True)
    out = []
    for d in ds:
        s = sorted(by_day.get(d, []))
        out.append({"date": d, "wd": "一二三四五六日"[dt.date.fromisoformat(d).weekday()], "settle": s, "local": d in have})
    return {"days": out, "oldest_local": min(have) if have else None}


def _kind(c):
    return "月選" if re.fullmatch(r"\d{6}", c) else "週三" if "W" in c else "週五" if "F" in c else "週選"


def hist(d, contract=None, span=0.05, night=False):
    """d 那天：台指期 1 分K ＋ 某個到期的各履約價 Call／Put 1 分K（night = 連前一晚夜盤一起）"""
    with _lock:
        o = opt_min(d)
        f = fut_min(d)
    if o is None or o.empty:
        return {"error": f"{d} 沒有選擇權逐筆資料（期交所只保留最近 30 個交易日，本機也沒有存）"}
    con = connect()
    exp = _expire_map(con)
    con.close()
    ymd = d.replace("-", "")
    vol = o.groupby("contract").v.sum()
    cons = [{"c": c, "kind": _kind(c), "expire": exp.get(c), "v": int(vol[c]), "today": exp.get(c) == ymd}
            for c in vol.index if (exp.get(c) or "99999999") >= ymd]
    cons.sort(key=lambda x: (x["expire"] or "99999999", x["c"]))
    if not contract or contract not in vol.index:
        today = [x for x in cons if x["today"]]
        contract = (today or sorted(cons, key=lambda x: -x["v"]))[0]["c"]
    x = o[o.contract == contract]
    if not night:            # 只看當天日盤 08:45 起
        t0 = int((pd.Timestamp(d) + pd.Timedelta(hours=8, minutes=45) - pd.Timestamp("1970-01-01")).total_seconds())
        x = x[x.ts >= t0]
        f = f[f.ts >= t0] if f is not None else None
    fb = [[int(r[0])] + [float(v) for v in r[1:]] for r in f[["ts", "o", "h", "l", "c", "v"]].values] if f is not None and len(f) else []
    # 履約價範圍：當天台指期最高最低再往外 span
    px = [b[4] for b in fb] or [float(x.strike.median())]
    lo, hi = min(px) * (1 - span), max(px) * (1 + span)
    x = x[(x.strike >= lo) & (x.strike <= hi)]
    ser = {}
    for (k, cp), g in x.groupby(["strike", "cp"]):
        ser.setdefault(cp, {})[str(int(k))] = [[int(r[0]), r[1], r[2], r[3], r[4], int(r[5])] for r in g[["ts", "o", "h", "l", "c", "v"]].values]
    strikes = sorted({int(k) for k in x.strike.unique()})
    e = exp.get(contract)
    return {"date": d, "contract": contract, "kind": _kind(contract), "expire": e, "contracts": cons, "strikes": strikes,
            "fut": fb, "fut_contract": None if f is None or not len(f) else f["contract"].iloc[0],
            "fut_tf": (f.attrs.get("src") if f is not None else None) or "1", "C": ser.get("C", {}), "P": ser.get("P", {})}


def keep_fut_zips(n=30):
    """每天收盤後順便把期貨逐筆存下來（期交所 30 個交易日後就刪掉）"""
    con = connect()
    ds = [r[0] for r in con.execute("SELECT DISTINCT date FROM fut_tx WHERE session='一般' ORDER BY date DESC LIMIT ?", (n,))]
    con.close()
    for d in ds:
        fut_zip(d)
