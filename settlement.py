"""
台指期月結算日統計（結算日＝每月第三個星期三，遇假日順延；用期交所各月合約的最後交易日）
  日K：加權指數（2015 年起，約 140 次）＋ 2025 年起（近期）
  盤中：加權指數 60 分K（Yahoo，約近 2 年）：09、10、11、12 點各一根，13:00~13:30 一根（＝結算價計算區間）
  比較基準：同期間「非結算日的星期三」與「所有交易日」
"""
import datetime as dt

import numpy as np
import pandas as pd

import intraday
from data import connect


def settle_dates(con, until=None):
    f = pd.read_sql("SELECT date, contract FROM fut_tx WHERE session='一般' AND volume > 0", con)
    f = f[f.contract.str.fullmatch(r"\d{6}")]
    last = f.groupby("contract").date.max()
    today = until or f.date.max()
    return sorted(d for d in last.values if d < today)          # 還沒到的（當月）不算


def _daily(con):
    t = pd.read_sql("SELECT date, open, high, low, close FROM taiex_k ORDER BY date", con).set_index("date")
    t["pc"] = t.close.shift(1)
    t["chg"] = (t.close / t.pc - 1) * 100
    t["gap"] = (t.open / t.pc - 1) * 100
    t["o2c"] = (t.close / t.open - 1) * 100
    t["rng"] = (t.high - t.low) / t.pc * 100
    t["clpos"] = (t.close - t.low) / (t.high - t.low).replace(0, np.nan)
    t["ma20"] = t.close.rolling(20).mean()
    t["wd"] = pd.to_datetime(t.index).weekday
    t["n_chg"] = t.chg.shift(-1)
    return t


def _intra(con):
    df, _ = intraday.get("TAIEX", "指數", "60")
    df["t"] = pd.to_datetime(df.date, unit="s")
    df["d"] = df.t.dt.strftime("%Y-%m-%d")
    df["h"] = df.t.dt.hour
    rows = []
    for d, g in df.groupby("d"):
        g = g.set_index("h")
        if not {9, 13}.issubset(g.index) or len(g) < 5:
            continue
        o = float(g.open[9])
        r = {"date": d, "open": o, "close": float(g.close[13])}
        for h in (9, 10, 11, 12, 13):
            if h in g.index:
                r[f"m{h}"] = (g.close[h] / g.open[h] - 1) * 100          # 該小時漲跌
        r["am"] = (g.close[10] / o - 1) * 100 if 10 in g.index else np.nan            # 09:00~11:00
        r["pm"] = (g.close[12] / g.close[10] - 1) * 100 if {10, 12}.issubset(g.index) else np.nan   # 11:00~13:00
        r["last"] = r.get("m13")                                                         # 13:00~13:30
        r["hi_h"] = int(g.high.idxmax())
        r["lo_h"] = int(g.low.idxmin())
        rows.append(r)
    return pd.DataFrame(rows).set_index("date")


def _cmp(sub, base, name, base_name):
    """settle vs 基準：平均、上漲機率"""
    def s(x):
        x = x.dropna()
        return {"n": int(len(x)), "avg": float(x.mean()) if len(x) else None, "up": float((x > 0).mean() * 100) if len(x) else None,
                "abs": float(x.abs().mean()) if len(x) else None}
    return {"name": name, "settle": s(sub), "base": s(base), "base_name": base_name}


def night_effect(con, sd):
    """夜盤（算在隔天）大漲後，隔天日盤：開高／開平／開低 → 開後最低、收紅黑、突破夜盤高、跌回前日收"""
    f = pd.read_sql("SELECT date, session, contract, open, high, low, close, volume FROM fut_tx WHERE close IS NOT NULL AND volume > 0", con)
    f = f[f.contract.str.fullmatch(r"\d{6}")]
    last = f[f.session == "一般"].groupby("contract").date.max()
    day = f[f.session == "一般"].copy()
    day["last"] = day.contract.map(last)
    near = day[day.date <= day["last"]].sort_values(["date", "last"]).groupby("date").head(1).set_index("date")
    dayc = day.set_index(["date", "contract"])
    nt = f[f.session == "盤後"].set_index(["date", "contract"])
    dates = list(near.index)
    rows = []
    for k in range(1, len(dates)):
        d, p = dates[k], dates[k - 1]
        c = near.contract[d]
        if (d, c) not in nt.index or (p, c) not in dayc.index:
            continue
        n, t, pc = nt.loc[(d, c)], near.loc[d], dayc.loc[(p, c)].close
        rows.append({"date": d, "settle": d in sd, "n_ret": (n.close / pc - 1) * 100,
                     "n_pos": (n.close - n.low) / (n.high - n.low) if n.high > n.low else np.nan,
                     "gap_n": (t.open / n.close - 1) * 100, "gap_p": (t.open / pc - 1) * 100, "o2c": (t.close / t.open - 1) * 100,
                     "c_n": (t.close / n.close - 1) * 100, "c_p": (t.close / pc - 1) * 100, "dip": (t.low / t.open - 1) * 100,
                     "run": (t.high / t.open - 1) * 100, "brk": t.high > n.high, "back": t.low < pc,
                     "clpos": (t.close - t.low) / (t.high - t.low) if t.high > t.low else np.nan})
    D = pd.DataFrame(rows).set_index("date")

    def agg(x, name):
        return {"cond": name, "n": int(len(x)), "night": float(x.n_ret.mean()), "gap_n": float(x.gap_n.mean()), "gap_p": float(x.gap_p.mean()),
                "o2c": float(x.o2c.mean()), "red": float((x.o2c > 0).mean() * 100), "c_n": float(x.c_n.mean()), "c_p": float(x.c_p.mean()),
                "dip": float(x.dip.mean()), "dip05": float((x.dip <= -0.5).mean() * 100), "run": float(x.run.mean()),
                "brk": float(x.brk.mean() * 100), "back": float(x.back.mean() * 100), "clpos": float(x.clpos.mean() * 100)}
    big = (D.n_ret >= 0.8) & (D.n_pos >= 0.6)
    gap = pd.cut(D.gap_n, [-99, -0.25, 0.25, 99], labels=["開低（低於夜收 0.25% 以上）", "開平（夜收 ±0.25%）", "開高（高於夜收 0.25% 以上）"])
    allb = [agg(D[big], "全部")] + [agg(x, str(k)) for k, x in D[big].groupby(gap[big], observed=True)]
    S = D[D.settle]
    sb = big[S.index]
    setb = [agg(S[sb], "全部")] + [agg(x, str(k)) for k, x in S[sb].groupby(gap[S.index][sb], observed=True)]
    nb = pd.cut(S.n_ret, [-99, -0.8, -0.3, 0.3, 0.8, 99], labels=["夜盤跌 >0.8%", "夜盤跌 0.3~0.8%", "夜盤平盤", "夜盤漲 0.3~0.8%", "夜盤漲 >0.8%"])
    byn = [agg(x, str(k)) for k, x in S.groupby(nb, observed=True)]
    det = S[S.n_ret >= 0.5].sort_index(ascending=False)
    detail = [{"date": d, "night": float(r.n_ret), "n_pos": float(r.n_pos * 100), "gap_n": float(r.gap_n), "gap_p": float(r.gap_p), "o2c": float(r.o2c),
               "dip": float(r.dip), "run": float(r.run), "c_n": float(r.c_n), "c_p": float(r.c_p), "brk": bool(r.brk)} for d, r in det.iterrows()]
    return {"from": D.index.min(), "all": allb, "settle": setb, "settle_by_night": byn, "detail": detail,
            "n_settle": int(len(S)), "def": "夜盤大漲＝夜盤收盤比前一天日盤收盤漲 ≥0.8%，而且收在夜盤高低區間的上 40%（不一定是最高點）"}


def night_5m(con, sd):
    """近 30 個交易日（台指期 5 分K，含夜盤）：前一晚夜盤漲跌 → 隔天日盤的盤中路徑"""
    b = pd.read_sql("SELECT * FROM intraday WHERE code='TX' AND tf='5' ORDER BY ts", con)
    if b.empty:
        return None
    b["t"] = pd.to_datetime(b.ts, unit="s")
    b["hm"] = b.t.dt.strftime("%H:%M")
    days = sorted(b[(b.hm >= "08:45") & (b.hm < "13:45")].t.dt.strftime("%Y-%m-%d").unique())
    rows = []
    for k in range(1, len(days)):
        d, p = days[k], days[k - 1]
        D = b[(b.t >= pd.Timestamp(d) + pd.Timedelta(hours=8, minutes=45)) & (b.t < pd.Timestamp(d) + pd.Timedelta(hours=13, minutes=45))].reset_index(drop=True)
        P_ = b[(b.t >= pd.Timestamp(p) + pd.Timedelta(hours=8, minutes=45)) & (b.t < pd.Timestamp(p) + pd.Timedelta(hours=13, minutes=45))]
        N = b[(b.t >= pd.Timestamp(p) + pd.Timedelta(hours=15)) & (b.t < pd.Timestamp(d) + pd.Timedelta(hours=5, minutes=5))]
        if D.empty or P_.empty or N.empty:
            continue
        pc, o, nc, nh, nl = float(P_.close.iloc[-1]), float(D.open.iloc[0]), float(N.close.iloc[-1]), float(N.high.max()), float(N.low.min())
        lo_i, hi_i = int(D.low.idxmin()), int(D.high.idxmax())
        lo, o2c = (float(D.low.min()) / o - 1) * 100, (float(D.close.iloc[-1]) / o - 1) * 100
        rows.append({"date": d, "settle": d in sd, "night": (nc / pc - 1) * 100, "n_pos": (nc - nl) / (nh - nl) * 100 if nh > nl else None,
                     "gap_n": (o / nc - 1) * 100, "lo_t": D.hm[lo_i], "hi_t": D.hm[hi_i], "lo": lo, "hi": (float(D.high.max()) / o - 1) * 100,
                     "o2c": o2c, "c_n": (float(D.close.iloc[-1]) / nc - 1) * 100,
                     "pm": (float(D.close.iloc[-1]) / float(D[D.hm >= "11:00"].open.iloc[0]) - 1) * 100 if (D.hm >= "11:00").any() else None,
                     "path": "先低後高" if lo_i < hi_i else "先高後低", "v": bool(lo_i < hi_i and lo <= -0.3 and o2c > 0),
                     "curve": [round(float(x), 3) for x in (D.close / o - 1) * 100]})
    R = pd.DataFrame(rows)
    up = R[R.night >= 0.5]
    summ = {"n": int(len(R)), "from": R.date.min(), "to": R.date.max(), "n_up": int(len(up)),
            "low_first": int((up.path == "先低後高").sum()), "v": int(up.v.sum()), "dip": float(up.lo.mean()), "o2c": float(up.o2c.mean()),
            "red": float((up.o2c > 0).mean() * 100), "pm": float(up.pm.mean()), "all_low_first": float((R.path == "先低後高").mean() * 100)}
    return {"summary": summ, "days": R.sort_values("date", ascending=False).to_dict("records")}


def analyze():
    con = connect()
    sd = settle_dates(con)
    T = _daily(con)
    con2 = connect()
    I = _intra(con2)
    con.close(); con2.close()
    out = {"dates": sd}
    T["is_s"] = T.index.isin(sd)
    idx = list(T.index)
    pos = {d: i for i, d in enumerate(idx)}
    # 結算日前後
    for k, name in ((-2, "d_2"), (-1, "d_1"), (1, "d1")):
        T[name] = np.nan
    rows = []
    for d in sd:
        if d not in pos:
            continue
        i = pos[d]
        if i < 3 or i + 1 >= len(idx):
            continue
        r = T.iloc[i]
        rows.append({"date": d, "wd": int(r.wd), "chg": r.chg, "gap": r.gap, "o2c": r.o2c, "rng": r.rng, "clpos": r.clpos,
                     "above20": bool(r.pc > T.ma20.iloc[i - 1]) if pd.notna(T.ma20.iloc[i - 1]) else None,
                     "tue": T.chg.iloc[i - 1], "mon": T.chg.iloc[i - 2], "tue_o2c": T.o2c.iloc[i - 1], "next": T.chg.iloc[i + 1],
                     "week2": (T.close.iloc[i - 1] / T.close.iloc[i - 3] - 1) * 100})
    S = pd.DataFrame(rows).set_index("date")
    S["red"] = S.o2c > 0
    recent = S[S.index >= "2025-01-01"]
    long = S[S.index >= "2015-01-01"]
    wed = T[(T.wd == 2) & ~T.is_s]
    out["n"] = {"recent": len(recent), "long": len(long), "first_recent": recent.index.min(), "last": recent.index.max()}

    def daily_block(Sx, since):
        W = wed[wed.index >= since]
        A = T[T.index >= since]
        return {"chg": _cmp(Sx.chg, W.chg, "當天漲跌（收盤 vs 前一天）", "非結算的星期三"),
                "o2c": _cmp(Sx.o2c, W.o2c, "開盤 → 收盤", "非結算的星期三"),
                "gap": _cmp(Sx.gap, W.gap, "開盤跳空", "非結算的星期三"),
                "rng": {"settle": float(Sx.rng.mean()), "wed": float(W.rng.mean()), "all": float(A.rng.mean())},
                "clpos": {"settle": float(Sx.clpos.mean()), "wed": float(W.clpos.mean())},
                "next": _cmp(Sx["next"], A.n_chg, "結算隔天（星期四）漲跌", "所有交易日")}
    out["daily_recent"] = daily_block(recent, "2025-01-01")
    out["daily_long"] = daily_block(long, "2015-01-01")

    # 2. 星期二 → 結算日
    def cond(Sx, key, bins, labels):
        g = pd.cut(Sx[key], bins, labels=labels)
        res = []
        for lab, x in Sx.groupby(g, observed=True):
            res.append({"cond": str(lab), "n": int(len(x)), "chg": float(x.chg.mean()), "up": float((x.chg > 0).mean() * 100),
                        "o2c": float(x.o2c.mean()), "red": float(x.red.mean() * 100), "rng": float(x.rng.mean()), "next": float(x["next"].mean())})
        return res
    tb = [-99, -1, -0.3, 0.3, 1, 99]
    tl = ["跌 >1%", "跌 0.3~1%", "平盤 ±0.3%", "漲 0.3~1%", "漲 >1%"]
    out["tue"] = {"recent": cond(recent, "tue", tb, tl), "long": cond(long, "tue", tb, tl)}
    # 方向一致率
    def same(Sx, key):
        x = Sx.dropna(subset=[key])
        return {"same": float((np.sign(x[key]) == np.sign(x.chg)).mean() * 100), "n": int(len(x))}
    out["tue_same"] = {"recent": same(recent, "tue"), "long": same(long, "tue")}
    # 星期二的 K 棒（開→收）
    out["tue_k"] = {"recent": cond(recent, "tue_o2c", [-99, 0, 99], ["週二收黑K", "週二收紅K"]), "long": cond(long, "tue_o2c", [-99, 0, 99], ["週二收黑K", "週二收紅K"])}

    # 3. 週一＋週二
    def pat(Sx):
        p = np.where(Sx.mon > 0, "一漲", "一跌")
        p = pd.Series(p, index=Sx.index) + np.where(Sx.tue > 0, "二漲", "二跌")
        res = []
        for k, x in Sx.groupby(p):
            res.append({"cond": k, "n": int(len(x)), "chg": float(x.chg.mean()), "up": float((x.chg > 0).mean() * 100),
                        "o2c": float(x.o2c.mean()), "red": float(x.red.mean() * 100), "next": float(x["next"].mean())})
        return sorted(res, key=lambda r: ["一漲二漲", "一漲二跌", "一跌二漲", "一跌二跌"].index(r["cond"]))
    out["montue"] = {"recent": pat(recent), "long": pat(long)}
    out["week2"] = {"recent": cond(recent, "week2", [-99, -2, 0, 2, 99], ["週一二合計跌 >2%", "跌 0~2%", "漲 0~2%", "漲 >2%"]),
                    "long": cond(long, "week2", [-99, -2, 0, 2, 99], ["週一二合計跌 >2%", "跌 0~2%", "漲 0~2%", "漲 >2%"])}
    out["trend"] = {"long": cond(long.dropna(subset=["above20"]).assign(a=lambda x: x.above20.astype(int)), "a", [-1, 0.5, 2], ["前一天在月線下", "前一天在月線上"])}

    # 4. 盤中（60 分K）
    Iv = I[I.index >= "2025-01-01"]
    Is = Iv[Iv.index.isin(sd)]
    Iw = Iv[(pd.to_datetime(Iv.index).weekday == 2) & ~Iv.index.isin(sd)]
    hours = []
    for h, nm in ((9, "09:00~10:00"), (10, "10:00~11:00"), (11, "11:00~12:00"), (12, "12:00~13:00"), (13, "13:00~13:30（結算區間）")):
        c = f"m{h}"
        hours.append({"h": nm, "s_avg": float(Is[c].mean()), "s_up": float((Is[c] > 0).mean() * 100), "s_abs": float(Is[c].abs().mean()),
                      "w_avg": float(Iw[c].mean()), "w_up": float((Iw[c] > 0).mean() * 100), "w_abs": float(Iw[c].abs().mean()),
                      "a_abs": float(Iv[c].abs().mean())})
    out["intra"] = {"n": int(len(Is)), "n_w": int(len(Iw)), "hours": hours}
    # 尾盤：拉尾盤／殺尾盤 與早盤方向
    def tail(x):
        L = x["last"]
        big = L.abs() >= 0.15
        rev = np.sign(L) != np.sign(x.am + x.pm)
        return {"n": int(len(x)), "pull": float(((L >= 0.15)).mean() * 100), "kill": float(((L <= -0.15)).mean() * 100),
                "flat": float((~big).mean() * 100), "rev": float((rev & big).mean() * 100), "cont": float((~rev & big).mean() * 100),
                "abs": float(L.abs().mean())}
    out["tail"] = {"settle": tail(Is), "wed": tail(Iw), "all": tail(Iv)}
    out["hilo"] = {"settle_hi": Is.hi_h.value_counts().sort_index().to_dict(), "settle_lo": Is.lo_h.value_counts().sort_index().to_dict(),
                   "wed_hi": Iw.hi_h.value_counts().sort_index().to_dict(), "wed_lo": Iw.lo_h.value_counts().sort_index().to_dict()}
    # 每一次結算日明細
    det = []
    for d in Is.index:
        r, s = Is.loc[d], S.loc[d] if d in S.index else None
        det.append({"date": d, "mon": _r(s.mon) if s is not None else None, "tue": _r(s.tue) if s is not None else None,
                    "gap": _r(s.gap) if s is not None else None, "am": _r(r.am), "pm": _r(r.pm), "last": _r(r["last"]),
                    "chg": _r(s.chg) if s is not None else None, "next": _r(s["next"]) if s is not None else None,
                    "hi_h": int(r.hi_h), "lo_h": int(r.lo_h)})
    out["detail"] = det[::-1]
    con3 = connect()
    out["night"] = night_effect(con3, set(sd))
    out["night5"] = night_5m(con3, set(sd))
    con3.close()
    # 下一次結算日：本月第三個星期三（還沒過的話）
    today = T.index.max()
    d0 = dt.date.fromisoformat(today)
    first = d0.replace(day=1)
    third_wed = first + dt.timedelta(days=(2 - first.weekday()) % 7 + 14)
    if third_wed.isoformat() <= today:
        nm = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        third_wed = nm + dt.timedelta(days=(2 - nm.weekday()) % 7 + 14)
    i = len(idx) - 1
    out["next"] = {"date": third_wed.isoformat(), "today": today, "days": int(np.busday_count(d0, third_wed)),
                   "d_1": _r(T.chg.iloc[i]), "d_2": _r(T.chg.iloc[i - 1]), "d_1_o2c": _r(T.o2c.iloc[i]),
                   "w2": _r((T.close.iloc[i] / T.close.iloc[i - 2] - 1) * 100), "above20": bool(T.close.iloc[i] > T.ma20.iloc[i])}
    out["text"] = _conclude(out)
    return _clean(out)


def _r(x, d=2):
    return None if x is None or pd.isna(x) else round(float(x), d)


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


def _conclude(o):
    L = []
    dr, dl = o["daily_recent"], o["daily_long"]
    t = o["tail"]
    L.append(f"樣本：2025 年起 {o['n']['recent']} 次結算（最近一次 {o['n']['last']}）；日K 另看 2015 年起 {o['n']['long']} 次")
    L.append(f"結算日當天：近期平均 {dr['chg']['settle']['avg']:+.2f}%、上漲機率 {dr['chg']['settle']['up']:.0f}%（非結算週三 {dr['chg']['base']['avg']:+.2f}%／{dr['chg']['base']['up']:.0f}%）；"
             f"長期 {dl['chg']['settle']['avg']:+.2f}%／{dl['chg']['settle']['up']:.0f}%")
    L.append(f"振幅：結算日平均 {dr['rng']['settle']:.2f}%，非結算週三 {dr['rng']['wed']:.2f}%"
             + ("（結算日波動比較大）" if dr['rng']['settle'] > dr['rng']['wed'] * 1.1 else "（差不多）" if dr['rng']['settle'] > dr['rng']['wed'] * 0.9 else "（結算日反而比較小）"))
    L.append(f"尾盤 13:00~13:30（結算價計算區間）：拉尾盤 {t['settle']['pull']:.0f}%、殺尾盤 {t['settle']['kill']:.0f}%、波動不大 {t['settle']['flat']:.0f}%；"
             f"平均波動 {t['settle']['abs']:.2f}%（非結算週三 {t['wed']['abs']:.2f}%）；跟早盤方向相反（尾盤反轉）{t['settle']['rev']:.0f}%")
    h = {x["h"][:5]: x for x in o["intra"]["hours"]}
    L.append(f"<b>結算日盤中慣性</b>：09 點那一小時最常是高點（{o['hilo']['settle_hi'].get(9, 0)}/{o['intra']['n']} 次）；"
             f"<b>12:00~13:00 只有 {h['12:00']['s_up']:.0f}% 上漲</b>（平均 {h['12:00']['s_avg']:+.2f}%，非結算週三 {h['12:00']['w_up']:.0f}%）→ 結算前一小時容易殺；"
             f"<b>13:00~13:30 有 {h['13:00']['s_up']:.0f}% 上漲</b>（平均 {h['13:00']['s_avg']:+.2f}%）→ 結算區間容易拉")
    nx = o["daily_recent"]["next"]["settle"]; nl = o["daily_long"]["next"]["settle"]
    L.append(f"<b>結算隔天（週四）</b>：近期平均 {nx['avg']:+.2f}%、上漲 {nx['up']:.0f}%（所有交易日 {o['daily_recent']['next']['base']['avg']:+.2f}%／{o['daily_recent']['next']['base']['up']:.0f}%）；長期 {nl['avg']:+.2f}%／{nl['up']:.0f}%")
    ts = o["tue_same"]
    L.append(f"週二 → 結算日同方向的機率：近期 {ts['recent']['same']:.0f}%、長期 {ts['long']['same']:.0f}%（50% 代表沒有關聯）")
    return L
