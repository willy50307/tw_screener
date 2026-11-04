"""
結算日（週三、週五、月選）日盤 08:45~13:30 尾盤波動統計 ＋ 樂透單出場規則回測 ＋ 實單紀錄
  價格：台指期近月 1 分K（data/opt_min/fut_*.pkl，沒有就退回 intraday TX 5 分K）
  選擇權：當天到期合約 1 分K（data/opt_min/opt_*.pkl）
  只讀本機已存的檔案，不會去期交所下載；新的結算日（opt_strike 有資料、逐筆檔存好後）會自動納入
  加權指數：用買賣權平價 K+C−P 反推（台指期常比現貨高 100~300 點），結算價＝13:00~13:30 期貨均價−基差（估計）
"""
import datetime as dt
import json
import os
import re
import threading
import time

import numpy as np
import pandas as pd

import optpage
from data import connect
from settings import BASE

E0 = pd.Timestamp("1970-01-01")
TRADES = os.path.join(BASE, "data", "settle_trades.json")
SEGS = [("08:45", "09:30"), ("09:30", "10:30"), ("10:30", "11:30"), ("11:30", "12:00"),
        ("12:00", "12:30"), ("12:30", "13:00"), ("13:00", "13:25"), ("13:25", "13:31")]
BUCKETS = [("08:45", "09:30"), ("09:30", "10:30"), ("10:30", "11:30"), ("11:30", "12:00"),
           ("12:00", "12:30"), ("12:30", "13:00"), ("13:00", "13:31")]
RULES = [("a", "抱到結算"), ("b3", "3 倍全出"), ("b5", "5 倍全出"), ("c1325", "3 倍出一半，剩下 13:25 出"),
         ("cset", "3 倍出一半，剩下抱到結算"), ("d40", "3、5 倍各出 1/3，剩下從最高回落 40% 出"),
         ("d50", "3、5 倍各出 1/3，剩下從最高回落 50% 出"), ("e1320", "13:20 時間出場"), ("e1325", "13:25 時間出場")]
_lock = threading.Lock()
_cache = {"key": None, "data": None}


def _T(d, hm):
    h, m = map(int, hm.split(":"))
    return int((pd.Timestamp(d) + pd.Timedelta(hours=h, minutes=m) - E0).total_seconds())


def _hm(ts):
    return pd.Timestamp(int(ts), unit="s").strftime("%H:%M")


def _kind(c):
    return "月選" if re.fullmatch(r"\d{6}", c) else "週三" if "W" in c else "週五" if "F" in c else "週選"


def _bucket(t):
    for a, z in BUCKETS:
        if a <= t < z:
            return f"{a}-{z[:5] if z != '13:31' else '13:30'}"
    return None


def _blabel(a, z):
    return f"{a}-{'13:30' if z == '13:31' else z}"


def settle_days(con):
    """每個到期合約的最後交易日（遇休市順延）＝實際結算日"""
    x = pd.read_sql("SELECT contract, MAX(date) d, MAX(expire) e FROM opt_strike WHERE expire >= '20260901' GROUP BY contract", con)
    last = con.execute("SELECT MAX(date) FROM opt_strike").fetchone()[0]
    x = x[(x.d < last) | (x.e == last.replace("-", ""))]
    return {d: sorted(g.contract) for d, g in x.groupby("d")}


def _have(folder, name):
    return os.path.exists(os.path.join(folder, name))


def _fut(con, d, monthly):
    """當天日盤 08:45~13:30 台指期近月分K（月選結算日含 13:30 那一筆收盤）"""
    src = "1m"
    if _have(optpage.D_MIN, f"fut_{d}.pkl") or _have(optpage.D_FUT, f"Daily_{d.replace('-', '_')}.zip"):
        with optpage._lock:
            b = optpage.fut_min(d)
        src = "1m" if b.attrs.get("src", "1") == "1" else "5m"
    else:
        b = pd.read_sql("SELECT ts, open o, high h, low l, close c, volume/1000.0 v FROM intraday WHERE code='TX' AND tf='5' AND ts>=? AND ts<?",
                        con, params=(_T(d, "08:45"), _T(d, "13:30")))
        src = "5m"
    if b is None or b.empty:
        return pd.DataFrame(), src
    end = _T(d, "13:30") + (60 if monthly else 0)
    b = b[(b.ts >= _T(d, "08:45")) & (b.ts < end)].sort_values("ts").reset_index(drop=True)
    return b[["ts", "o", "h", "l", "c"]].astype({"ts": "int64"}), src


def _opt(d):
    if _have(optpage.D_MIN, f"opt_{d}.pkl") or _have(optpage.D_OPT, f"OptionsDaily_{d.replace('-', '_')}.zip"):
        with optpage._lock:
            return optpage.opt_min(d)
    return None


def _basis(o, cons, f):
    """每分鐘 期貨 − (K+C−P)，只取期貨上下 150 點內的履約價"""
    oo = o[o.contract.isin(cons) & (o.ts >= f.ts.min()) & (o.ts < f.ts.max() + 300)]
    c = oo[oo.cp == "C"].set_index(["ts", "strike"]).c
    p = oo[oo.cp == "P"].set_index(["ts", "strike"]).c
    j = pd.concat([c, p], axis=1, keys=["C", "P"]).dropna().reset_index()
    if j.empty:
        return j
    j["F"] = f.set_index("ts").c.reindex(j.ts, method="ffill").values
    j = j[(j.strike - j.F).abs() <= 150]
    j["B"] = j.F - (j.strike + j.C - j.P)
    return j[["ts", "B"]]


def _bwin(j, a, z):
    if j is None or j.empty:
        return 0.0
    w = j[(j.ts >= a) & (j.ts < z)]
    return float((w if len(w) >= 5 else j).B.median())


def _maxmove(b, minutes):
    """任一 minutes 分鐘視窗內最大漲／跌點數與起點時間"""
    step = max(1, int(np.median(np.diff(b.ts))) // 60) if len(b) > 1 else 1
    n = max(1, minutes // step)
    L, H, ts = b.l.values, b.h.values, b.ts.values
    up, dn = (0.0, None), (0.0, None)
    for j in range(len(b)):
        i0 = max(0, j - n + 1)
        il = i0 + int(np.argmin(L[i0:j + 1])); ih = i0 + int(np.argmax(H[i0:j + 1]))
        if H[j] - L[il] > up[0]:
            up = (float(H[j] - L[il]), int(ts[il]))
        if H[ih] - L[j] > dn[0]:
            dn = (float(H[ih] - L[j]), int(ts[ih]))
    return up, dn


def _ext(g):
    if g.empty:
        return None, None, None
    return float((g.h - g.l.cummin()).max()), float((g.h.cummax() - g.l).max()), float(g.h.max() - g.l.min())


def _simulate(path, px, sv):
    """path：進場後每分鐘收盤（index＝HH:MM）；回傳各出場規則的回收倍數"""
    c = path.values; t = list(path.index)
    def at(x):
        k = [i for i, v in enumerate(t) if v <= x]
        return c[k[-1]] if k else px
    out = {"a": sv / px}
    for m in (3, 5):
        hit = np.where(c >= m * px)[0]
        out[f"b{m}"] = c[hit[0]] / px if len(hit) else sv / px
    h3 = np.where(c >= 3 * px)[0]
    if len(h3):
        out["c1325"] = (c[h3[0]] / 2 + at("13:25") / 2) / px
        out["cset"] = (c[h3[0]] / 2 + sv / 2) / px
    else:
        out["c1325"] = at("13:25") / px; out["cset"] = sv / px
    for tr in (40, 50):
        if not len(h3):
            out[f"d{tr}"] = sv / px; continue
        i3 = h3[0]; val = c[i3] / 3; left = 2 / 3; sold5 = False; peak = c[i3]
        for i in range(i3, len(c)):
            if not sold5 and c[i] >= 5 * px:
                val += c[i] / 3; left -= 1 / 3; sold5 = True
            peak = max(peak, c[i])
            if i > i3 and c[i] <= peak * (1 - tr / 100):
                val += left * c[i]; left = 0; break
        out[f"d{tr}"] = (val + left * sv) / px
    out["e1320"] = at("13:20") / px; out["e1325"] = at("13:25") / px
    return out


def _day(con, d, cons):
    monthly = any(re.fullmatch(r"\d{6}", c) for c in cons)
    f, src = _fut(con, d, monthly)
    if f.empty:
        return None, [], [], []
    o = _opt(d)
    J = _basis(o, cons, f) if o is not None else None
    op, cl = float(f.o.iloc[0]), float(f.c.iloc[-1])
    r = {"date": d, "wd": "一二三四五六日"[dt.date.fromisoformat(d).weekday()], "kind": "／".join(sorted({_kind(c) for c in cons})),
         "contracts": ",".join(cons), "src": src, "opt": o is not None, "open": op, "close": cl, "chg": cl - op,
         "high": float(f.h.max()), "low": float(f.l.min()), "high_t": _hm(f.ts[f.h.idxmax()]), "low_t": _hm(f.ts[f.l.idxmin()])}
    r["range"] = r["high"] - r["low"]
    prev, segs = op, []
    for a, z in SEGS:
        g = f[(f.ts >= _T(d, a)) & (f.ts < _T(d, z))]
        if g.empty:
            segs.append(None); continue
        segs.append({"chg": float(g.c.iloc[-1]) - prev, "rng": float(g.h.max() - g.l.min())}); prev = float(g.c.iloc[-1])
    r["segs"] = segs
    for W in (15, 30):
        (u, ut), (dn, dt_) = _maxmove(f, W)
        big = (u, ut, "漲") if u >= dn else (dn, dt_, "跌")
        r[f"mx{W}"] = big[0]; r[f"mx{W}_t"] = _hm(big[1]) if big[1] else None; r[f"mx{W}_dir"] = big[2]
    pre, post = f[f.ts < _T(d, "12:30")], f[f.ts >= _T(d, "12:30")]
    r["pre_up"], r["pre_dn"], r["pre_rng"] = _ext(pre)
    r["post_up"], r["post_dn"], r["post_rng"] = _ext(post)
    for k, g in (("pre", pre), ("post", post)):
        (u, _), (dn, _) = _maxmove(g, 15) if len(g) else ((0.0, None), (0.0, None))
        r[f"{k}_mx15"] = max(u, dn)
    r["tail_hi"] = bool(len(post) and post.h.max() > pre.h.max())
    r["tail_lo"] = bool(len(post) and post.l.min() < pre.l.min())
    r["from"] = {}
    for k in ("12:00", "12:30", "13:00"):
        b0, a0 = f[f.ts < _T(d, k)], f[f.ts >= _T(d, k)]
        if b0.empty or a0.empty:
            continue
        p0 = float(b0.c.iloc[-1]); up = float(a0.h.max() - p0); dn = float(p0 - a0.l.min())
        morning_up = p0 >= op
        r["from"][k] = {"net": cl - p0, "up": up, "dn": dn, "big": max(up, dn), "same": up if morning_up else dn, "rev": dn if morning_up else up}
    last30 = f[(f.ts >= _T(d, "13:00")) & (f.ts < _T(d, "13:30"))]
    S_set = float(last30.c.mean()) - _bwin(J, _T(d, "13:00"), _T(d, "13:30"))
    r["settle_est"] = S_set
    r["basis"] = _bwin(J, 0, 1 << 40) if J is not None else None
    mins = [[d, _hm(x.ts), x.o, x.h, x.l, x.c] for x in f.itertuples()]
    lotto, trades = [], []
    if o is None or J is None or J.empty:
        return r, mins, lotto, trades
    oc = o[o.contract.isin(cons) & (o.ts >= _T(d, "08:45"))]
    grid = pd.date_range(pd.Timestamp(d) + pd.Timedelta(hours=8, minutes=45), pd.Timestamp(d) + pd.Timedelta(hours=13, minutes=29), freq="1min")
    gts = ((grid - E0) // pd.Timedelta(seconds=1)).astype("int64")
    gl = grid.strftime("%H:%M")
    # 樂透單：價外 100/200/300 點
    for k in ("12:00", "12:30", "13:00"):
        te = _T(d, k)
        S = float(f[f.ts < te].c.iloc[-1]) - _bwin(J, te - 1800, te)
        for cp in ("C", "P"):
            for dist in (100, 200, 300):
                K = np.ceil((S + dist) / 50) * 50 if cp == "C" else np.floor((S - dist) / 50) * 50
                q = oc[(oc.strike == K) & (oc.cp == cp)]
                pb, pa = q[q.ts < te], q[q.ts >= te]
                if pb.empty:
                    continue
                px = float(pb.c.iloc[-1]); hi = float(pa.h.max()) if len(pa) else px
                sv = max(0.0, S_set - K) if cp == "C" else max(0.0, K - S_set)
                lotto.append({"date": d, "t": k, "cp": cp, "otm": dist, "strike": float(K), "px": px, "hi": hi,
                              "hi_t": _hm(pa.ts[pa.h.idxmax()]) if len(pa) else None, "hi_x": hi / px if px > 0 else None,
                              "settle_val": sv, "settle_x": sv / px if px > 0 else None})
    # 出場規則回測：跟早盤反向、權利金 5~20 點裡最價外的那檔（價格優先）
    for et in ("12:00", "12:15", "12:30"):
        te = _T(d, et)
        F0 = float(f[f.ts < te].c.iloc[-1]); S = F0 - _bwin(J, te - 1800, te)
        cp = "P" if F0 > op else "C"
        cand = []
        for K, q in oc[oc.cp == cp].groupby("strike"):
            dist = (K - S) if cp == "C" else (S - K)
            pb = q[q.ts < te]
            if dist < 150 or pb.empty or te - int(pb.ts.iloc[-1]) > 600:
                continue
            cand.append((dist, float(K), float(pb.c.iloc[-1]), q))
        strict = any(300 <= z[0] <= 500 and 5 <= z[2] <= 20 for z in cand)
        far = [z[2] for z in cand if 300 <= z[0] <= 500]
        far_px = float(np.median(far)) if far else None
        ok = [z for z in cand if 5 <= z[2] <= 20]
        if not ok:
            trades.append({"date": d, "entry": et, "cp": cp, "strict": strict, "far_px": far_px, "none": True}); continue
        dist, K, px, q = max(ok, key=lambda z: z[0])
        s = q.set_index("ts").c.reindex(gts).ffill(); s.index = gl
        path = s[s.index >= et].fillna(px)
        sv = max(0.0, S_set - K) if cp == "C" else max(0.0, K - S_set)
        t_ = {"date": d, "wd": r["wd"], "entry": et, "cp": cp, "strict": strict, "morning": F0 - op, "strike": K, "otm": dist, "px": px,
              "max": float(path.max()), "max_t": path.idxmax(), "max_x": float(path.max()) / px, "settle_val": sv, "far_px": far_px}
        t_.update(_simulate(path, px, sv))
        trades.append(t_)
    return r, mins, lotto, trades


def _stat(s):
    s = pd.Series([x for x in s if x is not None and x == x], dtype=float)
    return {"avg": float(s.mean()) if len(s) else None, "med": float(s.median()) if len(s) else None, "max": float(s.max()) if len(s) else None}


def _rules(g):
    out = []
    for k, lab in RULES:
        s = g[k]
        out.append({"key": k, "name": lab, "n": int(len(s)), "avg": float(s.mean()), "win": float((s > 1).mean() * 100),
                    "best": float(s.max()), "pnl": float((s - 1).sum())})
    return out


def _summarize(D, L, X):
    n = len(D)
    out = {"n": n, "d_from": D[0]["date"], "d_to": D[-1]["date"], "dates": [{"date": r["date"], "wd": r["wd"], "kind": r["kind"], "src": r["src"]} for r in D],
           "n_wed": sum(r["wd"] == "三" for r in D), "n_fri": sum(r["wd"] != "三" for r in D), "n_5m": sum(r["src"] == "5m" for r in D)}
    seg = []
    for i, (a, z) in enumerate(SEGS):
        x = [r["segs"][i] for r in D if r["segs"][i]]
        mn = (_T("2000-01-01", z if z != "13:31" else "13:30") - _T("2000-01-01", a)) // 60
        rng = _stat([v["rng"] for v in x])
        seg.append({"seg": _blabel(a, z), "min": int(mn), "abs_chg": _stat([abs(v["chg"]) for v in x])["avg"], "rng": rng["avg"],
                    "rng30": rng["avg"] / mn * 30 if rng["avg"] else None, "rng_max": rng["max"]})
    out["segs"] = seg
    out["prepost"] = {k: {"up": _stat([r[f"{k}_up"] for r in D]), "dn": _stat([r[f"{k}_dn"] for r in D]), "rng": _stat([r[f"{k}_rng"] for r in D]),
                          "mx15": _stat([r[f"{k}_mx15"] for r in D])} for k in ("pre", "post")}
    out["post_bigger"] = sum((r["post_mx15"] or 0) > (r["pre_mx15"] or 0) for r in D)
    out["tail"] = {"hi": sum(r["tail_hi"] for r in D), "lo": sum(r["tail_lo"] for r in D), "any": sum(r["tail_hi"] or r["tail_lo"] for r in D)}
    bl = [_blabel(a, z) for a, z in BUCKETS]
    out["hilo"] = [{"b": b, "hi": sum(_bucket(r["high_t"]) == b for r in D), "lo": sum(_bucket(r["low_t"]) == b for r in D)} for b in bl]
    out["mx"] = {str(W): {"avg": _stat([r[f"mx{W}"] for r in D])["avg"], "after1230": sum((r[f"mx{W}_t"] or "") >= "12:30" for r in D),
                          "dist": [{"b": b, "n": sum(_bucket(r[f"mx{W}_t"] or "") == b for r in D)} for b in bl]} for W in (15, 30)}
    fr = []
    for k in ("12:00", "12:30", "13:00"):
        x = [r["from"][k] for r in D if k in r["from"]]
        fr.append({"t": k, "net": _stat([abs(v["net"]) for v in x])["avg"], "up": _stat([v["up"] for v in x])["avg"], "dn": _stat([v["dn"] for v in x])["avg"],
                   "big": _stat([v["big"] for v in x])["avg"], "same": _stat([v["same"] for v in x])["avg"], "rev": _stat([v["rev"] for v in x])["avg"],
                   "n": len(x), "ge100": sum(v["big"] >= 100 for v in x), "ge150": sum(v["big"] >= 150 for v in x), "ge200": sum(v["big"] >= 200 for v in x)})
    out["from_t"] = fr
    wk = []
    for lab, m in (("週三（含月選）", lambda r: r["wd"] == "三"), ("週五（含順延）", lambda r: r["wd"] != "三")):
        x = [r for r in D if m(r)]
        if x:
            wk.append({"name": lab, "n": len(x), "range": _stat([r["range"] for r in x])["avg"], "pre_rng": _stat([r["pre_rng"] for r in x])["avg"],
                       "post_rng": _stat([r["post_rng"] for r in x])["avg"], "big1300": _stat([r["from"].get("13:00", {}).get("big") for r in x])["avg"],
                       "tail": sum(r["tail_hi"] or r["tail_lo"] for r in x)})
    out["week"] = wk
    lt = []
    if L:
        Ld = pd.DataFrame(L)
        for (t, cp, od), g in Ld.groupby(["t", "cp", "otm"]):
            lt.append({"t": t, "cp": cp, "otm": int(od), "n": int(len(g)), "px": float(g.px.median()), "settle_ok": int((g.settle_val > 0).sum()),
                       "x2": int((g.hi_x >= 2).sum()), "x3": int((g.hi_x >= 3).sum()), "x5": int((g.hi_x >= 5).sum()),
                       "settle_x": float(g.settle_x.mean())})
    out["lotto"] = lt
    Xd = pd.DataFrame([t for t in X if not t.get("none")])
    ex = {"n_days": len({t["date"] for t in X}), "strict": sum(bool(t["strict"]) for t in X), "slots": len(X), "by_entry": [], "all": [],
          "far_px": _stat([t.get("far_px") for t in X])["med"]}
    if len(Xd):
        for et, g in Xd.groupby("entry"):
            ex["by_entry"].append({"entry": et, "n": int(len(g)), "otm": float(g.otm.median()), "px": float(g.px.median()), "rules": _rules(g)})
        ex["all"] = _rules(Xd)
        ex["n"] = int(len(Xd))
        ex["settle_ok"] = int((Xd.settle_val > 0).sum())
    out["exit"] = ex
    return out


def _conclude(S):
    """各子頁的重點結論（數字都從統計結果代入）"""
    n = S["n"]; seg = {x["seg"]: x for x in S["segs"]}; fr = {x["t"]: x for x in S["from_t"]}
    mx = S["mx"]["15"]; first = max(mx["dist"], key=lambda x: x["n"])
    quiet = min([x for x in S["segs"] if "11:30" <= x["seg"] < "13:00"], key=lambda x: x["rng30"] or 1e9)
    pm = max([x for x in S["segs"] if x["seg"] >= "12:00" and x["seg"] != "13:25-13:30"], key=lambda x: x["rng30"] or 0)
    never = [h["b"] for h in S["hilo"] if h["hi"] == 0 and h["lo"] == 0]
    pp = S["prepost"]
    tail = [
        f"樣本 {n} 個結算日（{S['d_from']} ~ {S['d_to']}），台指期近月日盤。",
        f"全天最大一段 15 分鐘急漲急跌最常從 {first['b']} 開始（{first['n']}/{n} 天）；從 12:30 之後開始的只有 {mx['after1230']}/{n} 天。"
        f"12:30 前最大 15 分鐘波動平均 {pp['pre']['mx15']['avg']:.0f} 點，12:30 後 {pp['post']['mx15']['avg']:.0f} 點。",
        f"但 12:30 後仍有像樣的尾盤：12:30 到收盤單邊最大走勢平均 {fr['12:30']['big']:.0f} 點，≥150 點有 {fr['12:30']['ge150']}/{n} 天、≥200 點 {fr['12:30']['ge200']}/{n} 天；"
        f"13:00 起平均 {fr['13:00']['big']:.0f} 點。",
        f"每 30 分鐘換算，午盤最安靜是 {quiet['seg']}（{quiet['rng30']:.0f} 點）" + (f"，全天高低點從沒出現在 {'、'.join(never)}" if never else "")
        + f"；下午波動最大是 {pm['seg']}（{pm['rng30']:.0f} 點／30 分）。",
        f"尾盤多跟早盤反向：12:30 起反向平均 {fr['12:30']['rev']:.0f} 點、同方向 {fr['12:30']['same']:.0f} 點；13:00 起 {fr['13:00']['rev']:.0f} vs {fr['13:00']['same']:.0f}。"
        f"12:30 後創當日新高 {S['tail']['hi']} 次、新低 {S['tail']['lo']} 次。",
    ]
    lt = {(x["t"], x["cp"], x["otm"]): x for x in S["lotto"]}
    def ok(t):
        xs = [lt[k] for k in lt if k[0] == t]
        return sum(x["settle_ok"] for x in xs), sum(x["n"] for x in xs)
    ex = S["exit"]
    lotto = [f"13:00 以後買價外 100~300 點、抱到結算：{ok('13:00')[0]}/{ok('13:00')[1]} 筆還有價值；12:00 買是 {ok('12:00')[0]}/{ok('12:00')[1]} 筆。要賺得靠盤中賣出。"]
    if ex.get("all"):
        R = {x["key"]: x for x in ex["all"]}
        per = []
        for e in ex["by_entry"]:
            b = max(e["rules"], key=lambda r: r["pnl"])
            per.append(f"{e['entry']} 進場（{e['n']} 筆）" + ("每條規則都賠" if b["pnl"] < 0 else f"最好是「{b['name']}」{b['pnl']:+.1f} 單位")
                       + ("（樣本少、不穩）" if e["n"] < 8 else ""))
        best_rule = max(ex["all"], key=lambda r: r["pnl"])
        lotto += [
            f"原本想買的「價外 300~500 點、權利金 5~20 點」在 {ex['n_days']} 天 × 3 個進場時間裡只找到 {ex['strict']} 筆（這段期間 12 點後價外 300~500 點的權利金中位數只有 {ex['far_px']:.1f} 點），"
            f"所以回測改用「跟早盤反向、權利金 5~20 點裡最價外的那檔」（價外中位約 {np.median([e['otm'] for e in ex['by_entry']]):.0f} 點），共 {ex['n']} 筆。",
            f"抱到結算：平均 {R['a']['avg']:.2f} 倍、勝率 {R['a']['win']:.0f}%、總損益 {R['a']['pnl']:+.1f} 單位；"
            f"最好的是「{best_rule['name']}」{best_rule['pnl']:+.1f} 單位（勝率 {best_rule['win']:.0f}%）；分批加移動停利（回落 40%）{R['d40']['pnl']:+.1f}。",
            "；".join(per) + "。每組只有幾筆，倍數門檻只能當方向參考。",
        ]
    adv = [f"進場：12:00~12:30（全天高低點 {S['hilo'][4]['hi'] + S['hilo'][4]['lo']} 次出現在 12:00-12:30，最安靜、權利金還沒被尾盤炒高）；"
           + (f"回測 12:00 進場總損益 {min(r['pnl'] for r in ex['by_entry'][0]['rules']):+.1f}~{max(r['pnl'] for r in ex['by_entry'][0]['rules']):+.1f}，偏晚一點（12:15 後）比較好。" if ex.get("by_entry") else ""),
           f"方向：押跟早盤（開盤到進場時）相反——尾盤反向平均 {fr['12:30']['rev']:.0f} 點 > 同方向 {fr['12:30']['same']:.0f} 點。",
           f"選單：價外距離用選擇權反推的加權指數算（台指期比現貨高約 {S.get('basis_med') or 0:.0f} 點），權利金 5~20 點裡挑最價外的；300 點以外的通常太便宜、勝率太低。",
           f"出場：13:00~13:25 分批——到 3 倍先出一部分（或 1/3），5 倍再出，剩下用最高價回落 40% 移動停利，13:25 前出清；"
           + (f"回測「5 倍全出」{R['b5']['pnl']:+.1f}、「分批加回落 40%」{R['d40']['pnl']:+.1f}、「抱到結算」{R['a']['pnl']:+.1f} 單位。" if ex.get("all") else ""),
           f"預算：13:00 以後買的價外單抱到結算 {ok('13:00')[0]}/{ok('13:00')[1]} 有價值，不要抱；每筆只用樂透預算 1/4~1/3，同方向最多試兩次。"]
    return {"tail": tail, "lotto": lotto, "advice": adv}


def _key():
    con = connect()
    k = con.execute("SELECT MAX(date) FROM opt_strike").fetchone()[0]
    con.close()
    fs = []
    for folder in (optpage.D_MIN, optpage.D_FUT, optpage.D_OPT):
        if os.path.isdir(folder):
            fs += sorted(os.listdir(folder))
    return (k, hash(tuple(fs)))


def analyze():
    key = _key()
    if _cache["key"] == key:
        return _cache["data"]
    con = connect()
    sd = settle_days(con)
    D, M, L, X, miss = [], [], [], [], []
    for d, cons in sorted(sd.items()):
        r, mins, lotto, trades = _day(con, d, cons)
        if r is None:
            miss.append(d); continue
        D.append(r); M += mins; L += lotto; X += trades
    con.close()
    S = _summarize(D, L, X)
    S["basis_med"] = _stat([r["basis"] for r in D if r["basis"] and abs(r["basis"]) > 20])["med"]
    S["text"] = _conclude(S)
    S["missing"] = miss
    S["days"] = D[::-1]
    S["trades"] = [t for t in X if not t.get("none")][::-1]
    S["rules"] = [{"key": k, "name": n} for k, n in RULES]
    S["made"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    S = _clean(S)
    _cache.update(key=key, data=S)
    return S


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 2)
    return o


# ---------- 實單紀錄 ----------
def trades_load():
    try:
        with open(TRADES, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def _save(items):
    tmp = TRADES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TRADES)


FIELDS = ("date", "kind", "entry_t", "cp", "strike", "idx_entry", "cost", "exit", "exit_t", "peak", "idx_peak", "result", "review")


def trades_add(body):
    items = trades_load()
    rec = {k: body.get(k) for k in FIELDS if body.get(k) not in (None, "")}
    if not rec.get("date"):
        raise ValueError("要填日期")
    for k in ("strike", "idx_entry", "cost", "exit", "peak", "idx_peak"):
        if k in rec:
            rec[k] = float(rec[k])
    rec["id"] = int(time.time() * 1000)
    items.append(rec)
    _save(sorted(items, key=lambda r: (r["date"], r.get("entry_t") or "")))
    return rec


def trades_delete(rid):
    items = trades_load()
    _save([r for r in items if str(r.get("id")) != str(rid)])
