"""
今日盤勢分析：把籌碼面所有資料整理成「概要＋詳細」
  ① 台指期走勢（夜盤、日盤 5 分K 波段）＋ 美股
  ② 為什麼這樣走：現貨法人、期貨大戶、選擇權部位、各履約價賣方、結算、基差 → 規則推論
  ③ 個股／族群：法人默默買進、持續賣出、投信新進場、外資轉向、土洋同步、融資券／借券、隔日沖
全部是規則推論（不是 AI），資料不齊的部分會標示「尚未公布」
"""
import datetime as dt

import numpy as np
import pandas as pd

import chips
import options
from data import connect

_cache = {}


def _f(x, d=0):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def _sign(v, d=0, unit=""):
    if v is None:
        return "–"
    return f"{'+' if v > 0 else ''}{v:,.{d}f}{unit}"


# ---------------- ① 台指期走勢 ----------------
def _zigzag(df, th):
    """5 分K 波段：轉折幅度 ≥ th 點才算一段"""
    pts, trend = [], 0
    hi_i = lo_i = 0
    for i in range(len(df)):
        if df.high.iloc[i] >= df.high.iloc[hi_i]:
            hi_i = i
        if df.low.iloc[i] <= df.low.iloc[lo_i]:
            lo_i = i
        if trend >= 0 and df.high.iloc[hi_i] - df.low.iloc[i] >= th and hi_i < i:
            pts.append(("H", hi_i)); trend = -1; lo_i = i
        elif trend <= 0 and df.high.iloc[i] - df.low.iloc[lo_i] >= th and lo_i < i:
            pts.append(("L", lo_i)); trend = 1; hi_i = i
    # 最後一段：轉折之後的最高／最低點如果離收盤夠遠，再切一段（例如尾盤從低點拉回）
    if pts:
        k0 = pts[-1][1]
        seg = df.iloc[k0 + 1:]
        if len(seg):
            if pts[-1][0] == "H" and float(df.close.iloc[-1]) - float(seg.low.min()) >= th * 0.6:
                pts.append(("L", int(seg.low.idxmin())))
            elif pts[-1][0] == "L" and float(seg.high.max()) - float(df.close.iloc[-1]) >= th * 0.6:
                pts.append(("H", int(seg.high.idxmax())))
    end_t = lambda i: (df.t.iloc[i] + pd.Timedelta(minutes=5)).strftime("%H:%M")     # K棒結束時間
    out, prev = [], (0, float(df.open.iloc[0]), df.t.iloc[0].strftime("%H:%M"))
    for kind, i in pts:
        p = float(df.high.iloc[i] if kind == "H" else df.low.iloc[i])
        out.append({"from": prev[2], "to": end_t(i), "a": prev[1], "b": p, "chg": p - prev[1]})
        prev = (i, p, end_t(i))
    last = float(df.close.iloc[-1])
    out.append({"from": prev[2], "to": end_t(len(df) - 1), "a": prev[1], "b": last, "chg": last - prev[1]})
    return [x for x in out if abs(x["chg"]) >= th * 0.5 or x is out[-1]]


def _tx_section(con, date):
    import engine
    full = engine.load_special("TX").set_index("date")
    day = engine.load_special("TXD").set_index("date")
    if date not in day.index:
        return None
    i = list(day.index).index(date)
    prev = day.index[i - 1]
    d, p = day.loc[date], day.loc[prev]
    f = full.loc[date]
    closes = day["close"].iloc[:i + 1]
    ma = {n: float(closes.tail(n).mean()) for n in (5, 10, 20, 60)}
    ma_prev = {n: float(day["close"].iloc[:i].tail(n).mean()) for n in (20, 60)}
    b = pd.read_sql("SELECT * FROM intraday WHERE code='TX' AND tf='5' ORDER BY ts", con)
    b["t"] = pd.to_datetime(b.ts, unit="s")
    dd = dt.date.fromisoformat(date)
    pv = dt.date.fromisoformat(prev)
    nb = b[(b.t >= pd.Timestamp(pv) + pd.Timedelta(hours=15)) & (b.t < pd.Timestamp(dd) + pd.Timedelta(hours=5, minutes=5))].reset_index(drop=True)
    db = b[(b.t >= pd.Timestamp(dd) + pd.Timedelta(hours=8, minutes=45)) & (b.t < pd.Timestamp(dd) + pd.Timedelta(hours=13, minutes=45))].reset_index(drop=True)
    out = {"date": date, "prev": prev, "prev_close": float(p.close), "open": float(d.open), "high": float(d.high), "low": float(d.low),
           "close": float(d.close), "chg": float(d.close - p.close), "chg_pct": float((d.close / p.close - 1) * 100),
           "full": {"open": float(f.open), "high": float(f.high), "low": float(f.low)}, "ma": {k: round(v) for k, v in ma.items()},
           "vol": float(d.volume / 1000)}
    if len(nb):
        out["night"] = {"open": float(nb.open.iloc[0]), "high": float(nb.high.max()), "low": float(nb.low.min()), "close": float(nb.close.iloc[-1]),
                        "hi_t": nb.t[nb.high.idxmax()].strftime("%H:%M"), "lo_t": nb.t[nb.low.idxmin()].strftime("%H:%M")}
    if len(db):
        th = max(200.0, float(d.close) * 0.0055)
        out["intra"] = {"hi_t": db.t[db.high.idxmax()].strftime("%H:%M"), "lo_t": db.t[db.low.idxmin()].strftime("%H:%M"),
                        "waves": _zigzag(db, th), "vol_hour": {int(k): int(v / 1000) for k, v in db.groupby(db.t.dt.hour).volume.sum().items()},
                        "last15": float(db.close.iloc[-1] - db[db.t.dt.strftime("%H:%M") >= "13:30"].open.iloc[0]) if (db.t.dt.strftime("%H:%M") >= "13:30").any() else None}
    # 均線突破／跌破
    flags = []
    for n in (20, 60):
        if d.low < ma[n] <= p.close or (p.close >= ma_prev[n] and d.close < ma[n]):
            flags.append(f"{'跌破' if d.close < ma[n] else '盤中跌破後站回'} {n} 日線（{ma[n]:,.0f}）")
        elif d.high > ma[n] >= p.close or (p.close <= ma_prev[n] and d.close > ma[n]):
            flags.append(f"{'站上' if d.close > ma[n] else '盤中站上後跌回'} {n} 日線（{ma[n]:,.0f}）")
    out["flags"] = flags
    # 現貨與基差
    tk = pd.read_sql("SELECT date, close FROM taiex_k WHERE date <= ? ORDER BY date DESC LIMIT 2", con, params=(date,))
    if len(tk) and tk.date.iloc[0] == date:
        out["taiex"] = {"close": float(tk.close.iloc[0]), "chg_pct": float((tk.close.iloc[0] / tk.close.iloc[1] - 1) * 100) if len(tk) > 1 else None,
                        "basis": float(d.close - tk.close.iloc[0])}
    # 美股（台灣這天之前最後一個交易日）
    us = pd.read_sql("SELECT sym, date, open, high, low, close FROM us_idx WHERE date < ? ORDER BY date", con, params=(date,))
    u = {}
    for sym, g in us.groupby("sym"):
        if len(g) >= 2:
            a, z = g.iloc[-2], g.iloc[-1]
            u[sym] = {"date": z.date, "chg": float((z.close / a.close - 1) * 100), "o2c": float((z.close / z.open - 1) * 100),
                      "from_hi": float((z.close / z.high - 1) * 100)}
    out["us"] = u
    return out


# ---------------- ② 為什麼 ----------------
def _why(tx, opt, ch):
    """規則推論：回傳 [(權重, 文字)]"""
    R = []
    if not tx:
        return R
    down = tx["chg"] < 0
    s = (ch or {}).get("summary", {})
    fi = s.get("fi", {}).get("official") if s else None
    if fi is None and s:
        fi = s.get("fi", {}).get("twse")
    t = {x["g"]: x for x in (opt or {}).get("table", [])}
    fx = t.get("foreign", {})
    fut_f = fx.get("fut_1")
    basis = tx.get("taiex", {}).get("basis")
    # 現貨
    if fi is not None:
        if down and fi <= -200:
            R.append((3 + min(abs(fi) / 300, 3), f"<b>外資現貨大賣 {fi:,.0f} 億</b>，是指數下跌的主要賣壓"))
        elif not down and fi >= 200:
            R.append((3 + min(fi / 300, 3), f"<b>外資現貨大買 {fi:,.0f} 億</b>，推升指數"))
        elif down and fi > 100:
            R.append((1, f"外資現貨買超 {fi:,.0f} 億，下跌不是外資現貨造成"))
    # 基差：期貨 vs 現貨
    if basis is not None:
        if down and basis >= 50:
            R.append((2, f"收盤期貨比現貨<b>高 {basis:,.0f} 點</b>（期貨比現貨強）→ 賣壓來自現貨權值股，期貨端有人承接"))
        elif not down and basis <= -50:
            R.append((2, f"收盤期貨比現貨<b>低 {abs(basis):,.0f} 點</b>（期貨比現貨弱）→ 期貨端有人在空，漲勢未必能延續"))
    # 期貨大戶
    if fut_f is not None:
        if down and fut_f <= -2000:
            R.append((3, f"<b>外資台指期加空 {abs(fut_f):,.0f} 口</b>，期貨同步賣壓"))
        elif down and fut_f >= 800:
            R.append((1, f"外資台指期反而回補 {fut_f:,.0f} 口，沒有在期貨加空"))
        elif not down and fut_f >= 2000:
            R.append((3, f"<b>外資台指期加多（回補）{fut_f:,.0f} 口</b>，期貨推升"))
    x10 = t.get("t10x", {})
    if x10.get("fut_1") is not None and abs(x10["fut_1"]) >= 1500:
        v = x10["fut_1"]
        R.append((2, f"<b>十大非特定法人（大戶）</b>台指期{'加空' if v < 0 else '加多'} {abs(v):,.0f} 口"
                     + ("，順勢助跌" if v < 0 and down else "，順勢助漲" if v > 0 and not down else "，逆勢佈局")))
    s10 = t.get("t10s", {})
    if s10.get("fut_1") is not None and abs(s10["fut_1"]) >= 2000:
        v = s10["fut_1"]
        R.append((1.5, f"十大特定法人台指期{'加多' if v > 0 else '加空'} {abs(v):,.0f} 口（淨部位 {s10.get('fut', 0):+,.0f}）"))
    # 選擇權大戶
    for g, nm in (("t10x", "十大非特定法人"), ("foreign", "外資"), ("dealer", "自營商")):
        r = t.get(g, {})
        bp, sc, bc, sp = (r.get(k + "_1") or 0 for k in ("bp", "sc", "bc", "sp"))
        if bp >= 2000 and sc >= 2000:
            R.append((2, f"{nm}選擇權<b>買 Put {bp:,.0f}＋賣 Call {sc:,.0f} 口</b>（作空／避險）"))
        elif bc >= 2000 and sp >= 2000:
            R.append((2, f"{nm}選擇權<b>買 Call {bc:,.0f}＋賣 Put {sp:,.0f} 口</b>（偏多）"))
        elif bp >= 3000:
            R.append((1.5, f"{nm}大買 Put {bp:,.0f} 口（避險）"))
        elif sp >= 5000:
            R.append((1.5, f"{nm}大賣 Put {sp:,.0f} 口（看不跌）"))
    # 選擇權價位：卡漲／承接
    st = (opt or {}).get("strikes") or {}
    day_c = st.get("today")
    if day_c:
        hi, lo = tx["high"], tx["low"]
        cw = [x for x in day_c["call_add"] if hi <= x["k"] <= hi * 1.02]
        pw = [x for x in day_c["put_add"] if lo * 0.98 <= x["k"] <= lo]
        if cw:
            R.append((2.2, f"上方 Call 賣方今天在 {'、'.join(f'{x[chr(107)]:,.0f}' for x in cw[:3])} 新增"
                                               f"（共約 {sum(x['n'] for x in cw):,} 口）→ <b>{'壓住漲勢' if hi >= cw[0]['k'] * 0.99 else '上方壓力'}</b>"))
        if pw:
            R.append((1.8, f"下方 Put 賣方今天在 {'、'.join(f'{x[chr(107)]:,.0f}' for x in pw[:3])} 新增（共約 {sum(x['n'] for x in pw):,} 口）→ <b>下方承接</b>"))
    sett = (opt or {}).get("settle_info")
    if sett and sett["days"] <= 2:
        R.append((2, f"<b>{sett['contract']} 月選 {sett['date']} 結算</b>（還有 {sett['days']} 個交易日）：最大痛點 {sett['max_pain']:,.0f}，"
                     f"Call 牆 {sett['call_wall']:,.0f}、Put 牆 {sett['put_wall']:,.0f} → 結算前大戶傾向把指數控制在這個區間"))
    # 美股／夜盤
    sox = tx.get("us", {}).get("^SOX")
    n = tx.get("night")
    if sox and n:
        txt = f"前一晚美股：費半 {sox['chg']:+.2f}%（開到收 {sox['o2c']:+.2f}%）；台指期夜盤 {n['open']:,.0f} → {n['close']:,.0f}"
        gap = tx["open"] - n["close"]
        if abs(gap) >= 100:
            txt += f"，日盤開盤再{'跳空開低' if gap < 0 else '跳空開高'} {abs(gap):,.0f} 點"
        R.append((1.2 if abs(sox["chg"]) < 2 else 2, txt))
    pcr = (opt or {}).get("pc") or []
    if len(pcr) >= 2 and pcr[-1]["vol"] >= 110:
        R.append((1, f"Put/Call 成交量比 {pcr[-1]['vol']:.0f}%（Put 交易很熱，避險／看空情緒高）"))
    return sorted(R, key=lambda x: -x[0])


def _opt_extra(con, date, opt):
    """今天（單日）的履約價賣方動作、結算資訊、價平 IV"""
    tx, _ = options._tx(con)
    s = pd.read_sql("SELECT contract, strike, cp, oi, close, settle, expire, date FROM opt_strike WHERE date >= ? AND date <= ?", con,
                    params=((dt.date.fromisoformat(date) - dt.timedelta(days=14)).isoformat(), date))
    if s.empty or date not in set(s.date):
        return
    fl = options._flow(s, tx["close"])
    today = fl[fl.date == date]
    monthly = today[today.contract.str.fullmatch(r"\d{6}")]
    exps = sorted(monthly.expire.unique())
    exps = [e for e in exps if e >= date.replace("-", "")]
    if not exps:
        return
    near = exps[0]
    c = monthly[monthly.expire == near]
    oi = c.groupby(["strike", "cp"]).oi.sum().unstack(fill_value=0).reindex(columns=["C", "P"], fill_value=0)
    ks = oi.index.values
    pain = [((np.maximum(v - ks, 0) * oi.C.values).sum() + (np.maximum(ks - v, 0) * oi.P.values).sum()) for v in ks]
    px = float(tx.close.get(date))
    rng = oi[(oi.index >= px * 0.94) & (oi.index <= px * 1.06)]
    tdays = sorted(pd.read_sql("SELECT DISTINCT date FROM fut_tx WHERE date >= ? AND session='一般'", con, params=(date,)).date)
    ed = f"{near[:4]}-{near[4:6]}-{near[6:]}"
    # 交易日數（未來的交易日資料庫還沒有，用平日估）
    days = int(np.busday_count(dt.date.fromisoformat(date), dt.date.fromisoformat(ed)))
    opt["settle_info"] = {"contract": c.contract.iloc[0], "date": ed, "days": days, "max_pain": float(ks[int(np.argmin(pain))]),
                          "call_wall": float(rng[rng.index >= px].C.idxmax()) if (rng.index >= px).any() else None,
                          "put_wall": float(rng[rng.index <= px].P.idxmax()) if (rng.index <= px).any() else None}
    # 今天賣方新增（近月＋次月＋週選 合計）
    w = today[today.strike % 100 == 0]
    g = w.groupby(["strike", "cp"])[["sell_add", "sell_cover", "buy_add"]].sum()
    take = lambda cp, col, lo, hi: [{"k": float(k), "n": int(v)} for k, v in g.xs(cp, level="cp")[col][(lambda z: (z.index >= lo) & (z.index <= hi))(g.xs(cp, level="cp"))]
                                    .sort_values(ascending=False).head(4).items() if v >= 200]
    opt.setdefault("strikes", None)
    if opt["strikes"] is None:
        opt["strikes"] = {}
    opt["strikes"]["today"] = {"call_add": take("C", "sell_add", px * 0.99, px * 1.05), "call_cover": take("C", "sell_cover", px * 0.99, px * 1.06),
                               "put_add": take("P", "sell_add", px * 0.95, px * 1.01), "put_cover": take("P", "sell_cover", px * 0.94, px * 1.01)}
    # 價平 IV（下一個還沒要結算的月選）
    nxt = [e for e in exps if e > (dt.date.fromisoformat(date) + dt.timedelta(days=2)).strftime("%Y%m%d")]
    if nxt:
        a = fl[fl.expire == nxt[0]]
        a = a[a.contract.str.fullmatch(r"\d{6}")]
        ivs = {}
        for d_, gg in a.groupby("date"):
            p_ = tx.close.get(d_)
            if p_:
                ivs[d_] = float(gg.assign(dist=(gg.strike - p_).abs()).sort_values("dist").head(4).iv.mean() * 100)
        ks_ = sorted(ivs)
        if len(ks_) >= 2 and ks_[-1] == date:
            opt["atm_iv"] = {"now": round(ivs[ks_[-1]], 1), "prev": round(ivs[ks_[-2]], 1)}


# ---------------- ③ 個股／族群 ----------------
def _stocks(con, date):
    dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM inst WHERE date <= ? ORDER BY date DESC LIMIT 25", (date,))]
    if not dates or dates[0] != date:
        return None
    inst = pd.read_sql("SELECT * FROM inst WHERE date IN (%s)" % ",".join("?" * len(dates)), con, params=dates)
    inst = inst[inst.code.str.fullmatch(r"[1-9]\d{3}")]
    px = pd.read_sql("SELECT code, name, date, close, volume FROM prices WHERE date >= ? AND date <= ? AND length(code)=4",
                     con, params=((dt.date.fromisoformat(dates[-1]) - dt.timedelta(days=40)).isoformat(), date))
    C = px.pivot(index="date", columns="code", values="close")
    V = px.pivot(index="date", columns="code", values="volume") / 1000
    name = px.groupby("code").name.last()
    ind = chips._industry()
    win = sorted(dates)
    last = C.index[-1]
    r5 = (C.iloc[-1] / C.iloc[-6] - 1) * 100 if len(C) > 6 else None
    r20 = (C.iloc[-1] / C.iloc[-21] - 1) * 100 if len(C) > 21 else None
    r1 = (C.iloc[-1] / C.iloc[-2] - 1) * 100
    avgv = V.tail(20).mean()
    liquid = (avgv >= 800) & (C.iloc[-1] >= 10)
    out = {}
    for who, nm in (("fi", "外資"), ("it", "投信")):
        p = inst.pivot_table(index="date", columns="code", values=who, aggfunc="sum").reindex(win).fillna(0)
        amt = p * C.reindex(index=win, columns=p.columns) / 1e5      # 億
        sgn = np.sign(p)
        # 連買／連賣天數（從今天往回）
        streak = pd.Series(0, index=p.columns)
        for k in range(len(win) - 1, -1, -1):
            row = sgn.iloc[k]
            cur = np.sign(streak)
            same = (row == sgn.iloc[-1]) & (row != 0)
            if k == len(win) - 1:
                streak = sgn.iloc[-1].astype(int)
                alive = row != 0
            else:
                alive = alive & same
                streak = streak + np.where(alive, sgn.iloc[-1], 0)
        a5, a20 = amt.tail(5).sum(), amt.tail(20).sum()
        lots20 = p.tail(20).sum()
        pct20 = lots20 / V.tail(20).sum().reindex(p.columns) * 100        # 20 日買超佔成交量
        df = pd.DataFrame({"name": name.reindex(p.columns), "ind": [ind.get(c, "其他") for c in p.columns], "streak": streak,
                           "today": amt.iloc[-1], "a5": a5, "a20": a20, "pct20": pct20, "r1": r1.reindex(p.columns),
                           "r5": r5.reindex(p.columns) if r5 is not None else np.nan, "r20": r20.reindex(p.columns) if r20 is not None else np.nan,
                           "liq": liquid.reindex(p.columns).fillna(False)})
        df = df[df.liq]
        rec = lambda d_: [{"code": c, "name": r["name"], "ind": r["ind"], "streak": int(r["streak"]), "today": _f(r["today"], 2), "a5": _f(r["a5"], 2),
                           "a20": _f(r["a20"], 2), "pct20": _f(r["pct20"], 1), "r1": _f(r["r1"], 2), "r5": _f(r["r5"], 2), "r20": _f(r["r20"], 2)}
                          for c, r in d_.iterrows()]
        quiet = df[(df.streak >= 4) & (df.a20 > 0) & (df.r20.between(-6, 8))].sort_values("a20", ascending=False).head(15)
        sell = df[(df.streak <= -4) & (df.a20 < 0)].sort_values("a20").head(15)
        turn_b = df[(df.today > 0) & (df.a5 - df.today < 0) & (df.streak == 1)]
        prev_sell_days = (sgn.iloc[-6:-1] < 0).sum().reindex(turn_b.index)
        turn_b = turn_b[prev_sell_days >= 4].sort_values("today", ascending=False).head(10)
        turn_s = df[(df.today < 0) & (df.streak == -1)]
        prev_buy_days = (sgn.iloc[-6:-1] > 0).sum().reindex(turn_s.index)
        turn_s = turn_s[prev_buy_days >= 4].sort_values("today").head(10)
        out[who] = {"name": nm, "quiet": rec(quiet), "sell": rec(sell), "turn_buy": rec(turn_b), "turn_sell": rec(turn_s),
                    "top_today": rec(df.sort_values("today", ascending=False).head(10)), "top_sell_today": rec(df.sort_values("today").head(10))}
        if who == "it":
            prev10 = (p.iloc[-11:-1] > 0).sum()
            new = df[(df.today > 0.3) & (prev10.reindex(df.index) == 0)].sort_values("today", ascending=False).head(10)
            out[who]["new"] = rec(new)
        # 族群
        g = df.groupby("ind")[["today", "a5", "a20"]].sum()
        g["n_buy"] = df[df.today > 0].groupby("ind").size()
        g["n"] = df.groupby("ind").size()
        g = g.fillna(0)
        out[who]["ind"] = [{"ind": i, "today": _f(r.today, 2), "a5": _f(r.a5, 2), "a20": _f(r.a20, 2), "n_buy": int(r.n_buy), "n": int(r.n)}
                           for i, r in g.sort_values("a5", ascending=False).iterrows()]
        # 族群轉向：近 5 日買、但 20 日是賣（或反過來）
        out[who]["ind_turn_in"] = [x for x in out[who]["ind"] if x["a5"] > 3 and x["a20"] - x["a5"] < -3][:5]
        out[who]["ind_turn_out"] = [x for x in out[who]["ind"][::-1] if x["a5"] < -3 and x["a20"] - x["a5"] > 3][:5]
    # 外資＋投信 同時默默買
    q = {x["code"]: x for x in out["fi"]["quiet"]}
    out["both_quiet"] = [dict(x, fi_a20=q[x["code"]]["a20"]) for x in out["it"]["quiet"] if x["code"] in q]
    return out


def _sectors_summary(st):
    lines = []
    for who in ("fi", "it"):
        s = st[who]
        nm = s["name"]
        inn = [x for x in s["ind"] if x["a5"] > 0][:3]
        outt = [x for x in s["ind"][::-1] if x["a5"] < 0][:3]
        lines.append(f"<b>{nm}</b>近 5 日資金流入：" + ("、".join(f"{x['ind']}（{x['a5']:+.1f}億）" for x in inn) or "無")
                     + "；流出：" + ("、".join(f"{x['ind']}（{x['a5']:+.1f}億）" for x in outt) or "無"))
        if s["ind_turn_in"]:
            lines.append(f"{nm}<b>轉向買進</b>的族群（20 日還是賣、近 5 日開始買）：" + "、".join(x["ind"] for x in s["ind_turn_in"]))
        if s["ind_turn_out"]:
            lines.append(f"{nm}<b>轉向賣出</b>的族群（20 日還在買、近 5 日開始賣）：" + "、".join(x["ind"] for x in s["ind_turn_out"]))
    return lines


# ---------------- 組合 ----------------
def report(date=None):
    con = connect()
    stamp = con.execute("SELECT (SELECT MAX(date) FROM fut_tx), (SELECT COUNT(*) FROM chips_fetched), (SELECT MAX(date) FROM opt_inst)").fetchone()
    con.close()
    key = (date, stamp)
    if key in _cache:
        return _cache[key]
    con = connect()
    try:
        opt = options.report(date)
    except Exception as e:
        opt = {"error": str(e)}
    date = date or (opt.get("date") if not opt.get("error") else None)
    if not date:
        con.close()
        return {"error": "還沒有資料"}
    try:
        _opt_extra(con, date, opt)
    except Exception as e:
        print("opt_extra", e)
    try:
        ch = chips.report(date)
        if ch.get("date") != date:
            ch = {"error": f"{date} 的三大法人資料還沒公布（約下午 4~5 點）"}
    except Exception as e:
        ch = {"error": str(e)}
    tx = _tx_section(con, date)
    try:
        st = _stocks(con, date) if not ch.get("error") else None
    except Exception as e:
        print("stocks", e)
        st = None
    con.close()
    why = _why(tx, opt if not opt.get("error") else None, ch if not ch.get("error") else None)
    out = {"date": date, "tx": tx, "why": [w for _, w in why], "opt": _opt_view(opt), "spot": _spot_view(ch), "stocks": st,
           "margin": (ch.get("margin") if not ch.get("error") else None), "daytrade": _dt_view(ch)}
    out["summary"] = _summary(out, st)
    out = chips._clean(out)
    _cache.clear()
    _cache[key] = out
    return out


def _opt_view(opt):
    if not opt or opt.get("error"):
        return None
    t = opt.get("table", [])
    return {"table": [{k: x.get(k) for k in ("name", "g", "bc", "sc", "bp", "sp", "fut", "bc_1", "sc_1", "bp_1", "sp_1", "fut_1", "bull_amt")} for x in t],
            "pc": opt.get("pc", [])[-5:], "settle": opt.get("settle_info"), "iv": opt.get("atm_iv"),
            "today": (opt.get("strikes") or {}).get("today"), "levels": opt.get("summary", {}).get("lines", []),
            "reads": opt.get("reads", {}).get(5, [])}


def _spot_view(ch):
    if not ch or ch.get("error"):
        return {"error": (ch or {}).get("error")}
    return {"summary": ch["summary"], "all": ch.get("summary_all"),
            "fi_buy": ch["inst"]["fi"]["buy"][:10], "fi_sell": ch["inst"]["fi"]["sell"][:10],
            "it_buy": ch["inst"]["it"]["buy"][:10], "it_sell": ch["inst"]["it"]["sell"][:10],
            "tuyang_buy": ch["tuyang"]["buy"][:10], "tuyang_sell": ch["tuyang"]["sell"][:10],
            "n_tuyang": [ch["tuyang"]["n_buy"], ch["tuyang"]["n_sell"]]}


def _dt_view(ch):
    d = (ch or {}).get("daytrade") or {}
    if not d or d.get("error"):
        return None
    heavy = [x for x in d.get("today", []) if (x.get("dt_pct") or 0) >= 10]
    return {"n": len(d.get("today", [])), "heavy": heavy[:15], "rank": d.get("rank_today", [])[:8]}


def _summary(o, st):
    S = {"tx": [], "why": o["why"][:8], "stocks": [], "watch": []}
    tx = o["tx"]
    if tx:
        n = tx.get("night")
        line = f"台指期近月日盤收 <b>{tx['close']:,.0f}</b>（{tx['chg']:+,.0f}，{tx['chg_pct']:+.2f}%），開 {tx['open']:,.0f}、高 {tx['high']:,.0f}、低 {tx['low']:,.0f}"
        if tx.get("intra"):
            line += f"；最高在 {tx['intra']['hi_t']}、最低在 {tx['intra']['lo_t']}"
        S["tx"].append(line)
        if n:
            S["tx"].append(f"前一晚夜盤 {n['open']:,.0f} → {n['close']:,.0f}（高 {n['high']:,.0f}、低 {n['low']:,.0f}）")
        if tx.get("intra"):
            w = tx["intra"]["waves"]
            S["tx"].append("盤中波段：" + " → ".join(f"{x['from']}~{x['to']} {'漲' if x['chg'] > 0 else '跌'}{abs(x['chg']):,.0f}" for x in w))
        if tx.get("flags"):
            S["tx"].append("均線：" + "、".join(tx["flags"]))
        if tx.get("taiex"):
            S["tx"].append(f"加權指數收 {tx['taiex']['close']:,.2f}（{tx['taiex']['chg_pct']:+.2f}%），期現貨價差 {tx['taiex']['basis']:+,.0f} 點")
    if st:
        S["stocks"] = _sectors_summary(st)
        for who, nm in (("fi", "外資"), ("it", "投信")):
            q = st[who]["quiet"][:5]
            if q:
                S["stocks"].append(f"{nm}<b>默默買進</b>（連買 ≥4 天、股價 20 日漲幅還不大）：" + "、".join(f"{x['name']}（連{x['streak']}天）" for x in q))
            s_ = st[who]["sell"][:5]
            if s_:
                S["stocks"].append(f"{nm}<b>持續賣出</b>（連賣 ≥4 天）：" + "、".join(f"{x['name']}（連{-x['streak']}天）" for x in s_))
        if st["it"].get("new"):
            S["stocks"].append("<b>投信新進場</b>（前 10 天沒買、今天開始買）：" + "、".join(x["name"] for x in st["it"]["new"][:6]))
        if st["both_quiet"]:
            S["stocks"].append("<b>外資＋投信都在默默買</b>：" + "、".join(x["name"] for x in st["both_quiet"][:6]))
    sett = (o.get("opt") or {}).get("settle")
    if sett and sett["days"] <= 3:
        S["watch"].append(f"{sett['date']} 月選結算：最大痛點 {sett['max_pain']:,.0f}，Call 牆 {sett['call_wall']:,.0f}、Put 牆 {sett['put_wall']:,.0f}")
    if tx:
        S["watch"].append(f"60 日線 {tx['ma'][60]:,.0f}、20 日線 {tx['ma'][20]:,.0f}：收盤{'在 60 日線上' if tx['close'] >= tx['ma'][60] else '跌破 60 日線'}")
    lv = (o.get("opt") or {}).get("levels") or []
    S["watch"] += [l for l in lv if "壓力" in l or "支撐" in l][:2]
    dtv = o.get("daytrade")
    if dtv and dtv["heavy"]:
        S["watch"].append(f"隔日沖買超佔量 ≥10% 的漲停股 {len(dtv['heavy'])} 檔（明天開高容易被倒）：" + "、".join(x["name"] for x in dtv["heavy"][:6]))
    return S
