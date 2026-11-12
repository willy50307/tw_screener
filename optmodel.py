"""
選擇權定價模型（選擇權大分頁左邊小框、🎰 結算日樂透回測）
  合理價：用加權指數過去的日報酬分佈（2015 起，保留肥尾）模擬到期時的指數，算每個履約價的平均到期價值。
          「近況」版本再把報酬放大／縮小到最近 20 天的實際波動，比較貼近現在的行情。
  貴／便宜：市價 ÷ 合理價；另外看價平隱含波動率（IV）跟最近 20 天實際波動（RV）的比值，對照過去同樣天數到期時的 IV。
  結算日樂透：期交所逐筆（9/4 起）還原結算日當天各時間點的價外 Call／Put 價格，持有到結算看賺賠；
              另外用資料庫每日收盤（opt_strike）回測「結算前一天收盤買」，樣本比較多。
  最後結算價：期交所 optIndxFSP 網頁（存 opt_fsp）。
"""
import datetime as dt
import math
import re

import numpy as np
import pandas as pd
import requests

from data import HEADERS, connect

_c = {}


# ---------- 最後結算價 ----------
def _fsp_init(con):
    con.execute("CREATE TABLE IF NOT EXISTS opt_fsp(date TEXT, contract TEXT PRIMARY KEY, price REAL)")


def update_fsp(since_year=None):
    """期交所「臺指選擇權最後結算價」：預設抓今年；since_year 可以往回補"""
    con = connect()
    _fsp_init(con)
    y0 = since_year or dt.date.today().year
    rows = []
    for y in range(y0, dt.date.today().year + 1):
        try:
            r = requests.post("https://www.taifex.com.tw/cht/5/optIndxFSP", headers=HEADERS, timeout=60,
                              data={"start_year": str(y), "start_month": "01", "end_year": str(y), "end_month": "12"})
        except Exception as e:
            print("最後結算價下載失敗", y, e)
            continue
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
        rows += [(a.replace("/", "-"), b, float(c)) for a, b, c in re.findall(r"(\d{4}/\d\d/\d\d) (\d{6}(?:[WF]\d)?) ([\d.]+)", txt)]
    if rows:
        con.executemany("INSERT OR REPLACE INTO opt_fsp VALUES(?,?,?)", rows)
        con.commit()
    con.close()
    return len(rows)


def fsp():
    con = connect()
    _fsp_init(con)
    d = {c: p for c, p in con.execute("SELECT contract, price FROM opt_fsp")}
    _c["fsp_date"] = {c: d_ for c, d_ in con.execute("SELECT contract, date FROM opt_fsp")}
    con.close()
    return d


# ---------- 報酬分佈、實際波動 ----------
def _returns():
    if "ret" in _c:
        return _c["ret"]
    con = connect()
    t = pd.read_sql("SELECT date, close FROM taiex_k WHERE date >= '2015-01-01' ORDER BY date", con)
    f = pd.read_sql("SELECT date, close, volume FROM fut_tx WHERE session='一般' AND length(contract)=6 AND date >= '2025-01-01'", con)
    con.close()
    r = np.log(t.close).diff().dropna().values
    f = f.sort_values("volume").groupby("date").tail(1).set_index("date").sort_index()
    rf = np.log(f.close).diff().dropna()     # 換月那天會跳一下，影響不大
    _c["ret"] = (r, rf)
    return _c["ret"]


def rv(days=20):
    """台指期近 days 天實際波動（年化 %）"""
    _, rf = _returns()
    x = rf.tail(days)
    return float(x.std() * math.sqrt(252) * 100) if len(x) > 5 else None

YEAR_MIN = 252 * 300      # 一年的日盤交易分鐘（08:45~13:45 = 300 分鐘）


def rv_intraday(now=None):
    """今天台指期盤中實際波動（群益 TX00 逐筆 → 5 分K 收盤報酬的標準差，年化 %）。
    日盤開了就只算今天日盤；還沒開就算目前有的（夜盤）。用 5 分K 而不是 1 分K，避免買賣價跳動把波動灌大。"""
    try:
        import capital
        if not capital.ready():
            return None
        b = capital.bars_1m("TX00")
    except Exception:
        return None
    if b is None or not len(b):
        return None
    now = now or dt.datetime.now()
    t0 = int((dt.datetime.combine(now.date(), dt.time(8, 45)) - dt.datetime(1970, 1, 1)).total_seconds())
    day = b[(b["date"] >= t0) & (b["date"] < t0 + 300 * 60)]
    sess = "日盤"
    if len(day) < 10:
        day, sess = b, "夜盤"
    c = day.groupby(day["date"] // 300)["close"].last()
    r = np.diff(np.log(c.values.astype(float)))
    if len(r) < 6:
        return None
    return {"rv": round(float(r.std() * math.sqrt(YEAR_MIN / 5) * 100), 1), "n": int(len(r)), "sess": sess,
            "hi": float(day["high"].max()), "lo": float(day["low"].min())}


def rv_minute_hist():
    """過去日盤（data/opt_min 存的台指期 1 分K）平均實際波動，年化 %；結算日模式的合理價就是用這些分鐘漲跌模擬"""
    r = minute_returns()
    return round(float(r.std() * math.sqrt(YEAR_MIN) * 100), 1) if len(r) > 1000 else None


def rv_pack():
    """選擇權即時頁「實際波動」：今天盤中、近 5 天、近 20 天、過去日盤平均"""
    out = {"today": rv_intraday(), "rv5": rv(5), "rv20": rv(20)}
    for k in ("rv5", "rv20"):
        out[k] = None if out[k] is None else round(out[k], 1)
    try:
        out["min_hist"] = rv_minute_hist()
    except Exception:
        out["min_hist"] = None
    return out


def judge_settle(atm_iv_tt, rvp):
    """結算日：價平 IV（交易時間算）÷ 實際波動。今天盤中有 1 小時以上就用今天的，否則用過去日盤平均"""
    t = (rvp or {}).get("today") or {}
    ref, src = (t["rv"], f"今天{t['sess']}") if t.get("n", 0) >= 12 and t.get("sess") == "日盤" else ((rvp or {}).get("min_hist"), "過去日盤平均")
    if not atm_iv_tt or not ref:
        return {"ref": ref, "ref_src": src}
    ratio = atm_iv_tt / ref
    view = "偏貴" if ratio > 1.2 else "偏便宜" if ratio < 0.85 else "正常"
    return {"ref": ref, "ref_src": src, "ratio": round(float(ratio), 2), "view": view}


def trading_days(expire, now=None):
    """到結算還有幾個「收盤到收盤」：週末、國定假日不算（假日只算週末，夠用）；盤中算今天剩下的比例"""
    now = now or dt.datetime.now()
    e = dt.datetime.strptime(expire, "%Y%m%d").date()
    d0 = now.date()
    full = int(np.busday_count(d0 + dt.timedelta(days=1), e))          # 明天 ~ 結算前一天
    t = now.hour * 60 + now.minute
    today = 0.0
    if d0.weekday() < 5 and d0 < e:
        today = 1.0 if t < 8 * 60 + 45 else max(0.0, (13 * 60 + 45 - t) / 300) + 0.0
    last = (13 * 60 + 30 - max(t, 8 * 60 + 45)) / 300 if d0 == e else 0.95     # 結算日 13:30 結束
    if d0 == e:
        return max(last, 1 / 300)
    return full + today + max(last, 0)


def fair(F, strikes, h, scale_now=True, n=40000):
    """到期合理價：抽樣過去日報酬加總到剩餘交易日 h，去掉平均漂移"""
    r, _ = _returns()
    h = max(h, 1 / 300)                       # 最少 1 分鐘
    long_vol = r.std() * math.sqrt(252)
    rng = np.random.default_rng(7)
    k, frac = int(h), h - int(h)
    R = rng.choice(r, size=(n, k)).sum(axis=1) if k else np.zeros(n)
    R = R + rng.choice(r, size=n) * math.sqrt(frac)
    R = R - R.mean()
    out = {}
    for tag, sc in (("long", 1.0), ("now", (rv() or long_vol * 100) / 100 / long_vol)):
        if tag == "now" and not scale_now:
            continue
        S = F * np.exp(R * sc)
        out[tag] = {int(K): (float(np.maximum(S - K, 0).mean()), float(np.maximum(K - S, 0).mean())) for K in strikes}
    out["long_vol"] = round(long_vol * 100, 1)
    out["rv20"] = rv()
    return out


# ---------- 過去的隱含波動率（每天收盤，opt_strike） ----------
def _bs(F, K, T, v, call):
    s = v * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return F * N(d1) - K * N(d2) if call else K * N(-d2) - F * N(-d1)


def _iv(F, K, T, P, call):
    intr = max(F - K, 0) if call else max(K - F, 0)
    if not P or T <= 0 or P <= intr + 0.05:
        return None
    lo, hi = 0.01, 4.0
    for _ in range(50):
        m = (lo + hi) / 2
        if _bs(F, K, T, m, call) > P:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def iv_hist():
    """每天、每個到期：平價反推的遠期價、價平 IV（用結算價）、剩幾天"""
    con = connect()
    key = con.execute("SELECT MAX(date), COUNT(*) FROM opt_strike").fetchone()
    if _c.get("ivk") == key:
        con.close()
        return _c["iv"]
    s = pd.read_sql("SELECT date, contract, strike, cp, close, settle, expire FROM opt_strike", con)
    con.close()
    s["p"] = s.settle.where(s.settle > 0, s.close)
    rows = []
    for (d, c), g in s.groupby(["date", "contract"]):
        e = g.expire.iloc[0]
        T = (dt.datetime.strptime(e, "%Y%m%d").replace(hour=13, minute=30) - dt.datetime.fromisoformat(d).replace(hour=13, minute=45)).total_seconds() / (365 * 86400)
        if T <= 0 or T > 0.25:
            continue
        w = g.pivot_table(index="strike", columns="cp", values="p").dropna()
        if len(w) < 3 or "C" not in w or "P" not in w:
            continue
        w["diff"] = (w.C - w.P).abs()
        near = w.nsmallest(3, "diff")
        F = float(np.median(near.index + near.C - near.P))
        K = float(w.index[np.argmin(np.abs(w.index - F))])
        v = [x for x in (_iv(F, K, T, w.C[K], True), _iv(F, K, T, w.P[K], False)) if x]
        if v:
            rows.append({"date": d, "contract": c, "kind": "月選" if re.fullmatch(r"\d{6}", c) else "週三" if "W" in c else "週五",
                         "T": T * 365, "F": F, "iv": float(np.mean(v)) * 100})
    h = pd.DataFrame(rows)
    _c["ivk"], _c["iv"] = key, h
    return h


def _bucket(days):
    return 0 if days < 1 else 1 if days < 3 else 2 if days < 7 else 3 if days < 14 else 4


BUCKET_NAME = ["1 天內", "1~3 天", "3~7 天", "7~14 天", "14 天以上"]


def judge(kind, T_days, atm_iv):
    """現在的價平 IV 跟過去同樣剩餘天數的比：百分位、平均；IV／RV"""
    h = iv_hist()
    r20 = rv()
    out = {"rv20": None if r20 is None else round(r20, 1), "bucket": BUCKET_NAME[_bucket(T_days)]}
    if not len(h) or atm_iv is None:
        return out
    h = h.assign(b=h["T"].map(_bucket))
    same = h[h.b == _bucket(T_days)]
    out.update(n=int(len(same)), avg=round(float(same.iv.mean()), 1) if len(same) else None,
               pct=round(float((same.iv < atm_iv).mean() * 100)) if len(same) else None,
               ratio=round(atm_iv / r20, 2) if r20 else None)
    # 過去同樣天數時：IV ÷ 當時的 RV20 平均是多少（正常的「保險費」）
    _, rf = _returns()
    rvs = (rf.rolling(20).std() * math.sqrt(252) * 100).to_dict()
    rr = [x.iv / rvs[x.date] for x in same.itertuples() if rvs.get(x.date)]
    out["ratio_avg"] = round(float(np.median(rr)), 2) if rr else None
    if out.get("pct") is not None:
        p, ra, rr0 = out["pct"], out.get("ratio"), out.get("ratio_avg")
        hot = p >= 75 or (ra and rr0 and ra > rr0 * 1.2)
        cold = p <= 25 or (ra and rr0 and ra < rr0 * 0.85)
        out["view"] = "偏貴" if hot and not cold else "偏便宜" if cold and not hot else "正常"
    return out


# ---------- 結算日樂透回測 ----------
TIMES = ["08:50", "09:30", "10:30", "11:30", "12:00", "12:30", "13:00", "13:15", "13:25"]
TIERS = [(0.1, 3), (3, 8), (8, 15), (15, 25), (25, 40), (40, 80)]


def _parity_F(x, t):
    """t 那一分鐘為止、10 分鐘內有成交的 C、P → 平價反推遠期價"""
    w = x[(x.ts <= t) & (x.ts > t - 600)].sort_values("ts").groupby(["strike", "cp"]).c.last().unstack()
    if "C" not in w or "P" not in w:
        return None
    w = w.dropna()
    if len(w) < 2:
        return None
    w["d"] = (w.C - w.P).abs()
    near = w.nsmallest(3, "d")
    return float(np.median(near.index + near.C - near.P))


def lottery():
    import os
    import optpage
    fs = fsp()
    con = connect()
    exp = dict(con.execute("SELECT contract, MAX(expire) FROM opt_strike GROUP BY contract").fetchall())
    con.close()
    have = sorted(f[13:23].replace("_", "-") for f in os.listdir(optpage.D_OPT)) if os.path.isdir(optpage.D_OPT) else []
    key = (tuple(have), len(fs))
    if _c.get("lotk") == key:
        return _c["lot"]
    trades = []
    for d in have:
        ymd = d.replace("-", "")
        cs = [c for c, e in _c["fsp_date"].items() if e == d]
        if not cs:
            continue
        o = optpage.opt_min(d)
        if o is None:
            continue
        for c in cs:
            x = o[o.contract == c]
            S = fs[c]
            for hm in TIMES:
                t = int((pd.Timestamp(d + " " + hm) - pd.Timestamp("1970-01-01")).total_seconds())
                F = _parity_F(x, t)
                if not F:
                    continue
                last = x[(x.ts <= t) & (x.ts > t - 600)].sort_values("ts").groupby(["strike", "cp"]).c.last()
                for (K, cp), p in last.items():
                    otm = K - F if cp == "C" else F - K
                    if otm <= 0 or p <= 0 or p > 80:
                        continue
                    pay = max(S - K, 0) if cp == "C" else max(K - S, 0)
                    trades.append((d, c, hm, cp, K, otm, p, pay, S, F))
    T = pd.DataFrame(trades, columns=["date", "contract", "time", "cp", "k", "otm", "cost", "pay", "S", "F"])
    res = {"days": sorted(T.date.unique().tolist()) if len(T) else [], "n_trades": int(len(T))}
    if len(T):
        T["tier"] = pd.cut(T.cost, [a for a, _ in TIERS] + [TIERS[-1][1]], labels=[f"{a:g}~{b:g} 點" for a, b in TIERS], include_lowest=True)
        T["dist"] = pd.cut(T.otm, [0, 100, 200, 300, 500, 800, 5000], labels=["價外 0~100", "100~200", "200~300", "300~500", "500~800", "800 以上"])

        def agg(g):
            return {"n": int(len(g)), "days": int(g.date.nunique()), "cost": round(float(g.cost.mean()), 2), "pay": round(float(g.pay.mean()), 2),
                    "ret": round(float(g.pay.sum() / g.cost.sum()), 2) if g.cost.sum() else None,
                    "win": round(float((g.pay > g.cost).mean() * 100), 1), "x10": round(float((g.pay >= g.cost * 10).mean() * 100), 1),
                    "best": round(float((g.pay / g.cost).max()), 1)}
        res["by_time_tier"] = [{"time": hm, "tier": str(tr), **agg(g)} for (hm, tr), g in T.groupby(["time", "tier"], observed=True) if len(g) >= 5]
        res["by_time_dist"] = [{"time": hm, "dist": str(ds), "cp": cp, **agg(g)} for (hm, ds, cp), g in T.groupby(["time", "dist", "cp"], observed=True) if len(g) >= 5]
        res["by_time"] = [{"time": hm, **agg(g)} for hm, g in T.groupby("time")]
        # 每一次結算：當天收盤 vs 結算價的方向、最好的一筆
        det = []
        for (d, c), g in T.groupby(["date", "contract"]):
            b = g.assign(m=g.pay / g.cost).sort_values("m", ascending=False).iloc[0]
            f0 = g[g.time == TIMES[0]].F
            det.append({"date": d, "contract": c, "fsp": float(b.S), "open_F": round(float(f0.iloc[0])) if len(f0) else None,
                        "best": f"{b.time} {b.cp} {int(b.k)} @{b.cost:g} → {b.pay:g}（{b.m:.0f}×）" if b.m > 1 else "沒有賺錢的價外單"})
        res["detail"] = sorted(det, key=lambda x: x["date"], reverse=True)
    res["prev_close"] = _prev_close_lottery(fs, exp)
    _c["lotk"], _c["lot"] = key, res
    return res


def _prev_close_lottery(fs, exp):
    """結算前一個交易日收盤買價外單、放到結算（資料庫每日收盤，樣本比較多）"""
    con = connect()
    s = pd.read_sql("SELECT date, contract, strike, cp, close, settle FROM opt_strike WHERE close > 0", con)
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM opt_strike ORDER BY date")]
    con.close()
    rows = []
    for c, ed in _c["fsp_date"].items():
        prev = [d for d in days if d < ed]
        if not prev or ed not in days:
            continue
        g = s[(s.contract == c) & (s.date == prev[-1])]
        if g.empty:
            continue
        w = g.pivot_table(index="strike", columns="cp", values="close")
        F = None
        if "C" in w and "P" in w:
            w2 = w.dropna()
            if len(w2):
                w2 = w2.assign(d=(w2.C - w2.P).abs()).nsmallest(3, "d")
                F = float(np.median(w2.index + w2.C - w2.P))
        if not F:
            continue
        S = fs[c]
        for r in g[g.close <= 80].itertuples():
            otm = r.strike - F if r.cp == "C" else F - r.strike
            if otm <= 0:
                continue
            pay = max(S - r.strike, 0) if r.cp == "C" else max(r.strike - S, 0)
            rows.append((ed, c, r.cp, otm, r.close, pay))
    T = pd.DataFrame(rows, columns=["date", "contract", "cp", "otm", "cost", "pay"])
    if T.empty:
        return None
    T["tier"] = pd.cut(T.cost, [a for a, _ in TIERS] + [TIERS[-1][1]], labels=[f"{a:g}~{b:g} 點" for a, b in TIERS], include_lowest=True)
    out = []
    for (tr, cp), g in T.groupby(["tier", "cp"], observed=True):
        if len(g) < 5:
            continue
        out.append({"tier": str(tr), "cp": cp, "n": int(len(g)), "exps": int(g.contract.nunique()), "cost": round(float(g.cost.mean()), 2),
                    "pay": round(float(g.pay.mean()), 2), "ret": round(float(g.pay.sum() / g.cost.sum()), 2),
                    "win": round(float((g.pay > g.cost).mean() * 100), 1), "x10": round(float((g.pay >= g.cost * 10).mean() * 100), 1)})
    return {"from": T.date.min(), "to": T.date.max(), "n_exp": int(T.contract.nunique()), "rows": out}


# ---------- 結算日模式（週三、週五、月選結算當天的日盤；結算價 = 13:00~13:30 加權指數平均）----------
def is_settle_session(expire, now=None):
    now = now or dt.datetime.now()
    t = now.hour * 60 + now.minute
    return now.strftime("%Y%m%d") == expire and now.weekday() < 5 and 8 * 60 + 45 <= t < 13 * 60 + 30


def settle_minutes(now=None):
    """離結算還有幾分鐘的「有效波動時間」：13:00 前照算；13:00~13:30 是取平均，波動只算 1/3，已經過去的部分固定了"""
    now = now or dt.datetime.now()
    t = max(now.hour * 60 + now.minute + now.second / 60, 8 * 60 + 45)
    before = max(0.0, 13 * 60 - t)
    left = min(30.0, max(0.0, 13 * 60 + 30 - t))       # 平均區間還剩幾分鐘
    return before + (left / 30) ** 2 * left / 3, before, left


def minute_returns():
    """本機存的台指期日盤 1 分K（data/opt_min/fut_*.pkl）→ 每分鐘報酬"""
    import glob
    import os
    import optpage
    fs = sorted(glob.glob(os.path.join(optpage.D_MIN, "fut_*.pkl")))
    if _c.get("mrk") == len(fs):
        return _c["mr"]
    out = []
    for f in fs:
        b = pd.read_pickle(f)
        if b.empty:
            continue
        d = os.path.basename(f)[4:14]
        t0 = int((pd.Timestamp(d) + pd.Timedelta(hours=8, minutes=46) - pd.Timestamp("1970-01-01")).total_seconds())
        x = b[(b.ts >= t0) & (b.ts < t0 + 284 * 60)].c.values
        if len(x) > 100:
            out.append(np.diff(np.log(x)))
    r = np.concatenate(out) if out else np.array([])
    _c["mrk"], _c["mr"] = len(fs), r
    return r


def fair_settle(F, strikes, now=None, n=20000):
    """結算日：抽樣過去日盤的 1 分鐘漲跌，加總到「有效剩餘分鐘」，模擬結算價"""
    r = minute_returns()
    m, before, left = settle_minutes(now)
    if len(r) < 1000:
        return None
    k = int(m)
    rng = np.random.default_rng(11)
    R = np.zeros(n)
    for a in range(0, k, 50):                     # 分批加，避免一次吃太多記憶體
        R += rng.choice(r, size=(n, min(50, k - a))).sum(axis=1)
    R += rng.choice(r, size=n) * math.sqrt(m - k)
    R -= R.mean()
    S = F * np.exp(R)
    return {"fair": {int(K): (float(np.maximum(S - K, 0).mean()), float(np.maximum(K - S, 0).mean())) for K in strikes},
            "eff_min": round(m, 1), "to_13": round(before), "win_left": round(left), "n_min": int(len(r)),
            "sd": round(float(F * R.std()))}
