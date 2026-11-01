"""
漲停隔日統計：「五天內第一根漲停」（收盤收在漲停價，前 4 個交易日沒有收漲停）的隔天走勢與當沖做多買法。
  日K：2015/6/1（漲跌幅改 10%）之後的全部歷史
  5分K：Yahoo Finance 近 60 天（存在資料庫 intraday 表，tf='5'）
當沖成本：手續費 0.1425% ×2 ＋ 當沖交易稅 0.15% ＝ 0.435%（未打折）
"""
import datetime as dt
import json
import os
import time

import numpy as np
import pandas as pd

from data import connect
from settings import BASE

CACHE = os.path.join(BASE, "data", "limitup_stats.json")
FEE = 0.001425 * 2 + 0.0015


def tick_arr(x):
    x = np.asarray(x, dtype=float)
    return np.select([x < 10, x < 50, x < 100, x < 500, x < 1000], [0.01, 0.05, 0.1, 0.5, 1.0], 5.0)


def limit_up(prev_close):
    """漲停價：前收 ×1.1 往下取到升降單位"""
    v = np.asarray(prev_close, dtype=float) * 1.1
    t = tick_arr(v)
    return np.round(np.floor(v / t + 1e-9) * t, 2)


# ---------------- 找出事件 ----------------
def events(since="2015-06-01"):
    con = connect()
    px = pd.read_sql("SELECT code, name, market, date, open, high, low, close, volume FROM prices "
                     "WHERE date >= ? AND length(code) = 4 AND substr(code, 1, 1) != '0' ORDER BY code, date",
                     con, params=((dt.date.fromisoformat(since) - dt.timedelta(days=20)).isoformat(),))
    con.close()
    g = px.groupby("code", sort=False)
    px["pc"] = g["close"].shift(1)
    px["lim"] = limit_up(px["pc"])
    px["lu"] = (px["close"] >= px["lim"] - 1e-6) & (px["date"] >= since) & (px["pc"] > 0)
    px["vol5"] = g["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())   # 前 5 天平均量
    prev4 = g["lu"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).max().fillna(0)).astype(bool)
    px["first"] = px["lu"] & ~prev4
    px["lu_type"] = np.select([(px["open"] >= px["lim"] - 1e-6) & (px["low"] >= px["lim"] - 1e-6),
                               px["open"] >= px["lim"] - 1e-6], ["一字鎖死", "開盤漲停打開又鎖"], "盤中拉上漲停")
    for c in ("open", "high", "low", "close", "volume", "date"):
        px["n_" + c] = g[c].shift(-1)
    ev = px[px["first"]].copy()
    ev["n_lim"] = limit_up(ev["close"])
    return ev


def _gap_bucket(gap):
    return pd.cut(gap, [-11, -3, 0, 2, 4, 6, 9.4, 11],
                  labels=["開低 >3%", "開低 0~3%", "開高 0~2%", "開高 2~4%", "開高 4~6%", "開高 6~9.4%", "開盤漲停"])


def _table(df, by, aggs):
    t = df.groupby(by, observed=True).agg(**aggs).reset_index()
    return json.loads(t.round(2).to_json(orient="records", force_ascii=False))


# ---------------- 日K統計 ----------------
def daily_stats(ev):
    e = ev[ev["n_close"].notna()].copy()
    C0 = e["close"]
    e["gap"] = (e["n_open"] / C0 - 1) * 100
    e["hi"] = (e["n_high"] / C0 - 1) * 100
    e["lo"] = (e["n_low"] / C0 - 1) * 100
    e["cl"] = (e["n_close"] / C0 - 1) * 100
    e["o2c"] = (e["n_close"] / e["n_open"] - 1) * 100
    e["o2h"] = (e["n_high"] / e["n_open"] - 1) * 100
    e["n_lu"] = e["n_close"] >= e["n_lim"] - 1e-6
    e["n_lock"] = e["n_lu"] & (e["n_open"] >= e["n_lim"] - 1e-6) & (e["n_low"] >= e["n_lim"] - 1e-6)
    e["pattern"] = np.select(
        [e["n_lock"], e["n_lu"], (e["gap"] > 0.3) & (e["o2c"] > 0.3), (e["gap"] > 0.3) & (e["o2c"] < -0.3), e["gap"] > 0.3,
         e["o2c"] > 0.3, e["o2c"] < -0.3],
        ["一字續漲停", "盤中拉上續漲停", "開高走高", "開高走低", "開高後平盤震盪", "開平／開低走高", "開平／開低走低"], "開平／開低後平盤震盪")
    N = len(e)
    pat = e.groupby("pattern").agg(n=("code", "size"), close=("cl", "mean"), gap=("gap", "mean"), high=("hi", "mean"),
                                   o2c=("o2c", "mean")).reset_index().sort_values("n", ascending=False)
    pat["pct"] = pat["n"] / N * 100
    e["gap_b"] = _gap_bucket(e["gap"])
    up = lambda s: (s > 0).mean() * 100
    return {
        "n": int(N), "stocks": int(e["code"].nunique()), "period": [e["date"].min(), e["date"].max()],
        "overall": {k: {"avg": round(float(e[c].mean()), 2), "med": round(float(e[c].median()), 2), "up": round(float((e[c] > 0).mean() * 100), 1)}
                    for k, c in (("開盤漲跌", "gap"), ("最高", "hi"), ("最低", "lo"), ("收盤漲跌", "cl"), ("開盤買→收盤", "o2c"), ("開盤買→最高", "o2h"))},
        "lu_next": round(float(e["n_lu"].mean() * 100), 1),
        "patterns": json.loads(pat.round(2).to_json(orient="records", force_ascii=False)),
        "by_type": _table(e, "lu_type", dict(n=("code", "size"), gap=("gap", "mean"), high=("hi", "mean"), close=("cl", "mean"),
                                             o2c=("o2c", "mean"), red=("cl", up), lu=("n_lu", lambda s: s.mean() * 100))),
        "by_gap": _table(e, "gap_b", dict(n=("code", "size"), o2c=("o2c", "mean"), win=("o2c", up), o2h=("o2h", "mean"),
                                          close=("cl", "mean"))),
        "open_tp": open_tp_daily(e),
        "by_year": _table(e.assign(year=e["date"].str[:4]), "year",
                          dict(n=("code", "size"), gap=("gap", "mean"), close=("cl", "mean"), o2c=("o2c", "mean"),
                               lu=("n_lu", lambda s: s.mean() * 100))),
    }


def open_tp_daily(e):
    """長期日K驗證：隔天開盤買 → 停利 +x%（用當天最高價判斷有沒有碰到），沒到收盤賣。開盤就鎖漲停的買不到，排除"""
    x = e[e["n_open"] < e["n_lim"] - 1e-6]
    out = []
    for gb, g in [("全部", x)] + list(x.groupby("gap_b", observed=True)):
        row = {"gap": str(gb), "n": int(len(g))}
        for tp in (None, 2, 3, 5):
            r = g["o2c"] if tp is None else np.where(g["o2h"] >= tp, tp, g["o2c"])
            r = pd.Series(r) - FEE * 100
            key = "close" if tp is None else f"tp{tp}"
            row[key] = {"avg": round(float(r.mean()), 2), "win": round(float((r > 0).mean() * 100), 1)}
        for t in (2, 3, 4, 5):
            row[f"reach{t}"] = round(float((g["o2h"] >= t).mean() * 100), 1)
        out.append(row)
    return out


# ---------------- 5分K：買法 × 賣法 ----------------
def load_5m(codes):
    con = connect()
    q = f"SELECT code, ts, open, high, low, close, volume FROM intraday WHERE tf='5' AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts"
    df = pd.read_sql(q, con, params=list(codes))
    con.close()
    df["day"] = pd.to_datetime(df["ts"], unit="s").dt.strftime("%Y-%m-%d")
    return {k: g for k, g in df.groupby(["code", "day"])}


ENTRIES = {
    "open": "開盤價買",
    "black1": "第一根黑K收盤買",
    "black_after": "開盤後第一根黑K買（不含9:00那根）",
    "pull_prev": "回檔到平盤（前收）買",
    "pull2": "從開盤價回檔2%買",
    "orb5": "突破第一根5分K高點買",
    "orb15": "突破前15分鐘高點買",
    "t0930": "9:30再買",
}
EXITS = {"close": "收盤賣", "tp2": "停利+2%，沒到收盤賣", "tp3": "停利+3%，沒到收盤賣", "tp5": "停利+5%，沒到收盤賣",
         "tp3sl2": "停利+3%／停損-2%"}


def _entry(kind, O, H, L, C, c0, lim):
    """回傳 (進場價, 從第幾根開始算出場)；買不到回傳 None"""
    n = len(O)
    if kind == "open":
        return (O[0], 0) if O[0] < lim - 1e-6 else None
    if kind in ("black1", "black_after"):
        for i in range(0 if kind == "black1" else 1, n - 1):
            if C[i] < O[i] and C[i] < lim - 1e-6:
                return C[i], i + 1
        return None
    if kind == "pull_prev":
        if O[0] <= c0:
            return None
        for i in range(n):
            if L[i] <= c0:
                return min(O[i], c0), i + 1
        return None
    if kind == "pull2":
        p = O[0] * 0.98
        for i in range(1, n):
            if L[i] <= p:
                return min(O[i], p), i + 1
        return None
    if kind in ("orb5", "orb15"):
        k = 1 if kind == "orb5" else 3
        top = H[:k].max()
        for i in range(k, n):
            if H[i] > top:
                p = max(O[i], top * 1.001)
                return (p, i) if p < lim - 1e-6 else None
        return None
    if kind == "t0930":
        return (O[6], 6) if n > 6 and O[6] < lim - 1e-6 else None
    return None


def _exit(kind, entry, start, H, L, close):
    if kind == "close":
        return close
    tp = {"tp2": 0.02, "tp3": 0.03, "tp5": 0.05, "tp3sl2": 0.03}[kind]
    for i in range(start, len(H)):
        if kind == "tp3sl2" and L[i] <= entry * 0.98:      # 同一根同時碰到停損和停利 → 保守當作先停損
            return entry * 0.98
        if H[i] >= entry * (1 + tp):
            return entry * (1 + tp)
    return close


def intraday_stats(ev):
    e = ev[ev["n_date"].notna()].copy()
    con = connect()
    have = con.execute("SELECT MIN(ts), MAX(ts) FROM intraday WHERE tf='5'").fetchone()
    con.close()
    if not have[0]:
        return None
    d0 = pd.to_datetime(have[0], unit="s").strftime("%Y-%m-%d")
    e = e[e["n_date"] > d0]
    bars = load_5m(e["code"].unique())
    rows, chk = [], []
    for r in e.itertuples():
        b = bars.get((r.code, r.n_date))
        if b is None or len(b) < 20:
            continue
        O, H, L, C = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        if abs(O[0] / r.n_open - 1) > 0.01:     # 5分K 開盤跟官方開盤差太多 → 資料有問題，略過
            continue
        c0, lim, close = r.close, r.n_lim, r.n_close
        gap = (O[0] / c0 - 1) * 100
        rec = {"code": r.code, "name": r.name, "date": r.n_date, "gap": gap}
        # 開盤買：30 分鐘內 / 全天 最高漲幅
        if O[0] < lim - 1e-6:
            rec["h30"] = (H[:6].max() / O[0] - 1) * 100
            rec["hday"] = (H.max() / O[0] - 1) * 100
            rec["l30"] = (L[:6].min() / O[0] - 1) * 100
        for ek in ENTRIES:
            en = _entry(ek, O, H, L, C, c0, lim)
            if en is None:
                continue
            p, s = en
            for xk in EXITS:
                out = _exit(xk, p, s, H, L, close)
                rec[f"{ek}|{xk}"] = (out / p - 1 - FEE) * 100
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    N = len(df)
    df["gap_b"] = _gap_bucket(df["gap"])

    def st(s):
        s = s.dropna()
        if not len(s):
            return None
        pf = s[s > 0].sum() / -s[s <= 0].sum() if (s <= 0).any() else None
        return {"n": int(len(s)), "fill": round(len(s) / N * 100, 1), "avg": round(float(s.mean()), 2),
                "med": round(float(s.median()), 2), "win": round(float((s > 0).mean() * 100), 1),
                "pf": round(float(pf), 2) if pf else None, "worst": round(float(s.min()), 2)}

    grid = []
    for ek, en in ENTRIES.items():
        for xk, xn in EXITS.items():
            k = f"{ek}|{xk}"
            if k in df:
                s = st(df[k])
                if s:
                    grid.append({"entry": ek, "entry_name": en, "exit": xk, "exit_name": xn, **s})
    reach = {}
    for t in (2, 3, 4, 5):
        reach[str(t)] = {"m30": round(float((df["h30"].dropna() >= t).mean() * 100), 1),
                         "day": round(float((df["hday"].dropna() >= t).mean() * 100), 1)}
    # 依開盤幅度：每種情況最好的買法
    by_gap = []
    for gb, gdf in df.groupby("gap_b", observed=True):
        best_win, best_avg = None, None
        for k in [c for c in df.columns if "|" in c]:
            s = gdf[k].dropna()
            if len(s) < max(15, len(gdf) * 0.25):
                continue
            win, avg = (s > 0).mean() * 100, s.mean()
            if best_win is None or win > best_win[1]:
                best_win = (k, win, avg, len(s))
            if best_avg is None or avg > best_avg[2]:
                best_avg = (k, win, avg, len(s))
        o = gdf.get("open|close", pd.Series(dtype=float)).dropna()
        h30 = gdf["h30"].dropna() if "h30" in gdf else pd.Series(dtype=float)
        nm = lambda k: f"{ENTRIES[k.split('|')[0]]} → {EXITS[k.split('|')[1]]}"
        by_gap.append({"gap": str(gb), "n": int(len(gdf)),
                       "open_close": round(float(o.mean()), 2) if len(o) else None,
                       "open_win": round(float((o > 0).mean() * 100), 1) if len(o) else None,
                       "h30_3": round(float((h30 >= 3).mean() * 100), 1) if len(h30) else None,
                       "best_win": best_win and {"name": nm(best_win[0]), "win": round(float(best_win[1]), 1), "avg": round(float(best_win[2]), 2), "n": int(best_win[3])},
                       "best_avg": best_avg and {"name": nm(best_avg[0]), "win": round(float(best_avg[1]), 1), "avg": round(float(best_avg[2]), 2), "n": int(best_avg[3])}})
    o = df["open|close"].dropna()
    return {"n": N, "period": [df["date"].min(), df["date"].max()], "stocks": int(df["code"].nunique()),
            "open_close": round(float(o.mean()), 2), "open_med": round(float(o.median()), 2),
            "open_win": round(float((o > 0).mean() * 100), 1),
            "l30_avg": round(float(df["l30"].dropna().mean()), 2),
            "reach": reach, "grid": grid, "by_gap": by_gap}


# ---------------- 今天的候選（明天的漲停隔日） ----------------
def candidates(ev):
    con = connect()
    last = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    con.close()
    c = ev[ev["date"] == last].copy()
    c["lots"] = (c["volume"] / 1000).round().astype(int)
    c = c.sort_values("lots", ascending=False)
    return {"date": last, "rows": json.loads(c[["code", "name", "market", "close", "lots", "lu_type"]].to_json(orient="records", force_ascii=False))}


# ---------------- 對外：計算並快取 ----------------
def compute(progress=None):
    progress = progress if progress is not None else {}
    progress["msg"] = "找出歷年「五天內第一根漲停」…"
    ev = events()
    progress["msg"] = "統計隔天日K走勢…"
    res = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "daily": daily_stats(ev)}
    progress["msg"] = "用5分K統計隔天買法…"
    res["intraday"] = intraday_stats(ev)
    progress["msg"] = "研究隔天放空…"
    import limitup_short
    res["short"] = limitup_short.analyze(ev)
    res["candidates"] = candidates(ev)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    progress["msg"] = "完成"
    return res


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def fetch_5m(progress=None, days_back=62):
    """下載近 60 天漲停股的 5分K（Yahoo Finance），存進資料庫"""
    import yfinance as yf
    progress = progress if progress is not None else {}
    since = (dt.date.today() - dt.timedelta(days=days_back + 10)).isoformat()
    ev = events(since)
    codes = sorted(ev["code"].unique())
    mk = dict(zip(ev["code"], ev["market"]))
    tick = {c: f"{c}.{'TWO' if mk.get(c) == '上櫃' else 'TW'}" for c in codes}
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS intraday(code TEXT, tf TEXT, ts INTEGER, open REAL, high REAL, low REAL,
                   close REAL, volume REAL, PRIMARY KEY(code, tf, ts))""")
    for i in range(0, len(codes), 60):
        batch = codes[i:i + 60]
        progress["msg"] = f"下載5分K {i + len(batch)}/{len(codes)}"
        try:
            df = yf.download([tick[c] for c in batch], period="60d", interval="5m", group_by="ticker",
                             auto_adjust=False, threads=True, progress=False)
        except Exception:
            time.sleep(10)
            continue
        for c in batch:
            try:
                d = df[tick[c]].dropna(subset=["Close"])
            except Exception:
                continue
            idx = d.index.tz_convert("Asia/Taipei").tz_localize(None)
            ts = ((idx - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")).astype(int)
            con.executemany("INSERT OR REPLACE INTO intraday VALUES(?,?,?,?,?,?,?,?)",
                            [(c, "5", int(t), float(o), float(h), float(l), float(cl), float(v)) for t, o, h, l, cl, v in
                             zip(ts, d["Open"], d["High"], d["Low"], d["Close"], d["Volume"])])
        con.commit()
        time.sleep(2)
    con.close()
