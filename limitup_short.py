"""
漲停隔天「放空」研究：五天內第一根漲停的隔天，用 5 分K 的價量、支撐壓力找放空時機。
  放空＝現股當沖先賣後買，成本同樣 0.435%（手續費 0.1425% ×2 ＋ 當沖稅 0.15%）
  若被軋到漲停，最多虧到漲停價（價格不會超過漲停）
  台股「平盤以下」放空可能受限 → 每筆標記進場價在平盤上或平盤下，另外統計
"""
import json

import numpy as np
import pandas as pd

from limitup import FEE, _gap_bucket, load_5m
from data import connect

ENTRIES = {
    "open": "開盤價放空",
    "rally2": "拉高到開盤價+2%放空",
    "rally3": "拉高到開盤價+3%放空",
    "black1": "第一根黑K收盤放空",
    "orl5": "跌破第一根5分K低點放空",
    "orl15": "跌破前15分鐘低點放空",
    "vwap": "跌破VWAP（均價線）放空",
    "failhi": "假突破（過第一根高點又跌回開盤價下）放空",
    "wick": "前30分鐘出現長上影爆量K棒放空",
    "limfail": "觸及漲停又打開（離漲停-2%）放空",
    "prevbreak": "開高後跌破平盤放空",
    "t0930": "9:30放空",
}
# 每種放空方法「進場當下已經知道」的條件（避免用到未來資訊）
BASE_C = ["gap_b", "dvol_b", "lu_type"]
FB_C = BASE_C + ["fb", "fb_wick"]
KNOWN = {"open": BASE_C, "rally2": BASE_C, "rally3": BASE_C, "wick": BASE_C, "limfail": BASE_C, "prevbreak": BASE_C,
         "black1": FB_C, "orl5": FB_C, "vwap": FB_C, "failhi": FB_C,
         "orl15": FB_C + ["early_b"], "t0930": FB_C + ["early_b", "open_vs_vwap30"]}
EXITS = {"close": "收盤回補", "tp2": "跌2%回補，沒到收盤補", "tp3": "跌3%回補，沒到收盤補", "tp5": "跌5%回補，沒到收盤補",
         "tp3sl2": "跌3%回補／漲2%停損"}


def _vwap(H, L, C, V):
    tp = (H + L + C) / 3
    cv = np.cumsum(V)
    return np.where(cv > 0, np.cumsum(tp * V) / np.where(cv > 0, cv, 1), C)


def _entry(kind, O, H, L, C, V, vw, c0, lim):
    """回傳 (放空價, 從第幾根開始算回補)；沒有機會回傳 None"""
    n = len(O)
    if kind == "open":
        return O[0], 0
    if kind in ("rally2", "rally3"):
        p = O[0] * (1.02 if kind == "rally2" else 1.03)
        if p >= lim:
            return None
        for i in range(n):
            if H[i] >= p:
                return max(O[i], p) if i else p, i + 1
        return None
    if kind == "black1":
        for i in range(n - 1):
            if C[i] < O[i]:
                return C[i], i + 1
        return None
    if kind in ("orl5", "orl15"):
        k = 1 if kind == "orl5" else 3
        low = L[:k].min()
        for i in range(k, n):
            if L[i] < low:
                return min(O[i], low * 0.999), i + 1
        return None
    if kind == "vwap":
        for i in range(2, n - 1):
            if C[i] < vw[i] and C[i - 1] >= vw[i - 1]:
                return C[i], i + 1
        return None
    if kind == "failhi":
        broke = False
        for i in range(1, n - 1):
            if H[i] > H[0]:
                broke = True
            if broke and C[i] < O[0]:
                return C[i], i + 1
        return None
    if kind == "wick":
        avgv = V[:6].mean() if V[:6].sum() else 0
        for i in range(min(6, n - 1)):
            body = abs(C[i] - O[i])
            up = H[i] - max(O[i], C[i])
            if up >= max(2 * body, O[i] * 0.01) and V[i] >= avgv:
                return C[i], i + 1
        return None
    if kind == "limfail":
        hit = False
        for i in range(n - 1):
            if H[i] >= lim - 1e-6:
                hit = True
            if hit and C[i] <= lim * 0.98:
                return C[i], i + 1
        return None
    if kind == "prevbreak":
        if O[0] <= c0 * 1.01:
            return None
        for i in range(n):
            if L[i] <= c0 * 0.999:
                return min(O[i], c0 * 0.999), i + 1
        return None
    if kind == "t0930":
        return (O[6], 6) if n > 6 else None
    return None


def _cover(kind, entry, start, H, L, close, lim):
    if kind == "close":
        return close
    tp = {"tp2": 0.02, "tp3": 0.03, "tp5": 0.05, "tp3sl2": 0.03}[kind]
    for i in range(start, len(H)):
        if kind == "tp3sl2" and H[i] >= entry * 1.02:          # 同一根同時碰到 → 保守當作先停損
            return min(entry * 1.02, lim)
        if L[i] <= entry * (1 - tp):
            return entry * (1 - tp)
    return close


def _ret(entry, cover):
    return (entry / cover - 1 - FEE) * 100      # 放空報酬：賣價 / 買回價 - 1


# ---------------- 日K長期：開盤放空 ----------------
def daily_short(ev):
    e = ev[ev["n_close"].notna()].copy()
    C0 = e["close"]
    e["gap"] = (e["n_open"] / C0 - 1) * 100
    e["o2c"] = (e["n_close"] / e["n_open"] - 1) * 100
    e["o2l"] = (e["n_low"] / e["n_open"] - 1) * 100      # 開盤後最多跌多少
    e["o2h"] = (e["n_high"] / e["n_open"] - 1) * 100
    e["gap_b"] = _gap_bucket(e["gap"])
    out = []
    for gb, g in [("全部", e)] + list(e.groupby("gap_b", observed=True)):
        row = {"gap": str(gb), "n": int(len(g))}
        for tp in (None, 2, 3, 5):
            r = -g["o2c"] if tp is None else np.where(g["o2l"] <= -tp, tp, -g["o2c"])
            r = pd.Series(np.asarray(r, dtype=float)) - FEE * 100
            row["close" if tp is None else f"tp{tp}"] = {"avg": round(float(r.mean()), 2), "win": round(float((r > 0).mean() * 100), 1)}
        for t in (2, 3, 4, 5):
            row[f"drop{t}"] = round(float((g["o2l"] <= -t).mean() * 100), 1)
        row["squeeze"] = round(float((g["n_high"] >= g["n_lim"] - 1e-6).mean() * 100), 1)   # 被軋到漲停的機率
        out.append(row)
    # 長期驗證：開高 2% 以上時，依「漲停日量能」「漲停型態」細分（這些條件開盤前就知道）
    e["s_close"] = -e["o2c"] - FEE * 100
    e["s_tp3"] = np.where(e["o2l"] <= -3, 3, -e["o2c"]) - FEE * 100
    e["dvol_b"] = pd.cut(e["volume"] / e["vol5"], [-1, 2, 4, 1e9], labels=["量 <2倍均量", "量 2~4倍", "爆量 >4倍"]).astype(str)
    up = e[e["gap"] > 2]
    cross = []
    for col, nm in (("dvol_b", "漲停當天量能"), ("lu_type", "漲停型態")):
        for (gb, v), g in up.groupby(["gap_b", col], observed=True):
            if len(g) < 100 or v == "nan":
                continue
            cross.append({"gap": str(gb), "cond": nm, "val": v, "n": int(len(g)),
                          "close": round(float(g["s_close"].mean()), 2), "win": round(float((g["s_close"] > 0).mean() * 100), 1),
                          "tp3": round(float(g["s_tp3"].mean()), 2), "win3": round(float((g["s_tp3"] > 0).mean() * 100), 1)})
    e["year"] = e["date"].str[:4]
    x = e[e["gap"] >= 4]
    yr = x.groupby("year").agg(n=("code", "size"), avg=("o2c", lambda s: float((-s).mean() - FEE * 100)),
                               win=("o2c", lambda s: float(((-s - FEE * 100) > 0).mean() * 100))).reset_index()
    return {"open_tp": out, "cross": cross, "by_year_gap4": json.loads(yr.round(2).to_json(orient="records", force_ascii=False))}


# ---------------- 5分K：放空方法 × 回補方法、條件分析 ----------------
def intraday_short(ev):
    e = ev[ev["n_date"].notna()].copy()
    con = connect()
    have = con.execute("SELECT MIN(ts) FROM intraday WHERE tf='5'").fetchone()[0]
    con.close()
    if not have:
        return None
    d0 = pd.to_datetime(have, unit="s").strftime("%Y-%m-%d")
    e = e[e["n_date"] > d0]
    bars = load_5m(e["code"].unique())
    rows = []
    for r in e.itertuples():
        b = bars.get((r.code, r.n_date))
        if b is None or len(b) < 20:
            continue
        O, H, L, C, V = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        if abs(O[0] / r.n_open - 1) > 0.01:
            continue
        c0, lim, close = r.close, r.n_lim, r.n_close
        vw = _vwap(H, L, C, V)
        body0, up0 = abs(C[0] - O[0]), H[0] - max(O[0], C[0])
        rec = {"code": r.code, "name": r.name, "date": r.n_date,
               # ---- 條件（價量、支撐壓力）----
               "gap": (O[0] / c0 - 1) * 100,
               "fb": "第一根黑K" if C[0] < O[0] else ("第一根紅K" if C[0] > O[0] else "第一根平盤"),
               "fb_wick": "第一根長上影" if up0 >= max(body0, O[0] * 0.005) else "第一根無長上影",
               "early_vol": (V[:3].sum() / r.volume * 100) if r.volume else np.nan,    # 前15分鐘量 / 漲停當天總量
               "d_vol": (r.volume / r.vol5) if r.vol5 else np.nan,                       # 漲停當天量 / 前5日均量
               "lu_type": r.lu_type,
               "open_vs_vwap30": "9:30 在均價線下" if len(C) > 6 and C[5] < vw[5] else "9:30 在均價線上",
               "o2l30": (L[:6].min() / O[0] - 1) * 100, "o2lday": (L.min() / O[0] - 1) * 100}
        for ek in ENTRIES:
            en = _entry(ek, O, H, L, C, V, vw, c0, lim)
            if en is None:
                continue
            p, s = en
            rec[f"below|{ek}"] = p < c0          # 進場價在平盤下（可能不能放空）
            for xk in EXITS:
                rec[f"{ek}|{xk}"] = _ret(p, _cover(xk, p, s, H, L, close, lim))
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    N = len(df)
    df["gap_b"] = _gap_bucket(df["gap"]).astype(str)
    df["early_b"] = pd.cut(df["early_vol"], [-1, 15, 30, 1e9], labels=["前15分量 <15%", "前15分量 15~30%", "前15分量 >30%"]).astype(str)
    df["dvol_b"] = pd.cut(df["d_vol"], [-1, 2, 4, 1e9], labels=["漲停日量 <2倍均量", "漲停日量 2~4倍", "漲停日量 >4倍（爆量）"]).astype(str)
    half = df["date"] <= df["date"].sort_values().iloc[N // 2]

    def st(s):
        s = s.dropna()
        if len(s) < 5:
            return None
        pf = s[s > 0].sum() / -s[s <= 0].sum() if (s <= 0).any() else None
        return {"n": int(len(s)), "fill": round(len(s) / N * 100, 1), "avg": round(float(s.mean()), 2),
                "med": round(float(s.median()), 2), "win": round(float((s > 0).mean() * 100), 1),
                "pf": round(float(pf), 2) if pf else None, "worst": round(float(s.min()), 2)}

    keys = [c for c in df.columns if c.count("|") == 1 and not c.startswith("below|")]
    grid = []
    for k in keys:
        ek, xk = k.split("|")
        s = st(df[k])
        if not s:
            continue
        bel = df.loc[df[k].notna(), f"below|{ek}"].astype(bool)
        above = st(df.loc[df[k].notna() & ~df[f"below|{ek}"].fillna(False).astype(bool), k])
        grid.append({"key": k, "entry": ek, "entry_name": ENTRIES[ek], "exit": xk, "exit_name": EXITS[xk], **s,
                     "below_pct": round(float(bel.mean() * 100), 1), "above": above})
    grid.sort(key=lambda g: -g["avg"])

    # 條件分析：前 3 名策略 × 各條件
    conds = [("隔天開盤幅度", "gap_b"), ("第一根5分K", "fb"), ("第一根上影線", "fb_wick"), ("前15分鐘量能", "early_b"),
             ("漲停當天量能", "dvol_b"), ("漲停型態", "lu_type"), ("9:30 vs 均價線", "open_vs_vwap30")]
    top = [g["key"] for g in grid[:3]]
    cond_tables = []
    for k in top:
        tbl = []
        for cname, col in conds:
            if col not in KNOWN[k.split("|")[0]]:
                continue
            for val, g in df[df[k].notna()].groupby(col):
                s = g[k]
                if len(s) < 15 or val in ("nan", "None"):
                    continue
                tbl.append({"cond": cname, "val": val, "n": int(len(s)), "avg": round(float(s.mean()), 2),
                            "win": round(float((s > 0).mean() * 100), 1)})
        cond_tables.append({"key": k, "name": f"{ENTRIES[k.split('|')[0]]} → {EXITS[k.split('|')[1]]}", "rows": tbl})

    # 自動找「策略 × 兩個條件」組合，並用前後兩段時間檢查是否穩定
    combos = []
    for k in keys:
        cols = KNOWN[k.split("|")[0]]
        sub = df[df[k].notna()]
        for i, c1 in enumerate(cols):
            for c2 in cols[i + 1:]:
                for (v1, v2), g in sub.groupby([c1, c2]):
                    if len(g) < 30 or "nan" in (str(v1), str(v2)):
                        continue
                    s = g[k]
                    a, b = s[half.loc[g.index]], s[~half.loc[g.index]]
                    if len(a) < 10 or len(b) < 10:
                        continue
                    combos.append({"name": f"{ENTRIES[k.split('|')[0]]} → {EXITS[k.split('|')[1]]}", "cond": f"{v1}＋{v2}",
                                   "n": int(len(s)), "avg": round(float(s.mean()), 2), "win": round(float((s > 0).mean() * 100), 1),
                                   "avg1": round(float(a.mean()), 2), "avg2": round(float(b.mean()), 2)})
    stable = [c for c in combos if c["avg1"] > 0 and c["avg2"] > 0]
    best_avg = sorted(stable, key=lambda c: -c["avg"])[:12]
    best_win = sorted([c for c in stable if c["n"] >= 40], key=lambda c: -c["win"])[:12]

    o = df["open|close"].dropna()
    return {"n": N, "period": [df["date"].min(), df["date"].max()], "stocks": int(df["code"].nunique()),
            "open_close": round(float(o.mean()), 2), "open_win": round(float((o > 0).mean() * 100), 1),
            "drop": {str(t): {"m30": round(float((df["o2l30"] <= -t).mean() * 100), 1),
                              "day": round(float((df["o2lday"] <= -t).mean() * 100), 1)} for t in (2, 3, 4, 5)},
            "grid": grid, "conds": cond_tables, "best_avg": best_avg, "best_win": best_win,
            "split": [df["date"].min(), df.loc[half, "date"].max(), df["date"].max()]}


def analyze(ev):
    return {"daily": daily_short(ev), "intraday": intraday_short(ev)}
