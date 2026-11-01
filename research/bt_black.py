"""研究 5：今天出現什麼條件，隔天容易收黑K（收<開）？
價量＋MACD：2025-05 起；三大法人／融資／借券：2025-10-20 起；分點：2026-04-23 起（只有有抓分點的股票）。
用法：python research/bt_black.py"""
import numpy as np
import pandas as pd

from common import (DT_BRANCHES, P, _b, _con, _streak, combo_search, conditions, load_panel, save_out, show, tbl,
                    universe)
from indicators import indicator_cols

COLS = ["條件", "次數", "隔天黑K%", "lift", "前半段%", "後半段%", "實體黑K%", "隔天開盤%", "隔天收盤%"]


# ---------- 額外特徵（寬表算完再接到 panel） ----------
def extra_features(df):
    con = _con()
    px = pd.read_sql("SELECT code,date,open,high,low,close,volume FROM prices", con)
    px = px[px.code.str.fullmatch(r"[1-9]\d{3}")]
    W = {k: px.pivot(index="date", columns="code", values=k).sort_index() for k in ("open", "high", "low", "close", "volume")}
    o, h, l, c, v = (W[k] for k in ("open", "high", "low", "close", "volume"))
    vl = v / 1000
    ind = indicator_cols(W, P)
    pc = c.shift(1)
    F = {}
    for n in (5, 10, 20, 60):
        ma = ind[f"ma{n}"]
        F[f"d_ma{n}"] = (c / ma - 1) * 100
        F[f"fail_ma{n}"] = (pc < ma.shift(1)) & (h >= ma) & (c < ma)            # 從下面碰均線沒站上
        F[f"brk_ma{n}"] = (pc >= ma.shift(1)) & (c < ma)                         # 今天跌破均線
    F["ret10"] = (c / c.shift(10) - 1) * 100
    F["bb_touch"] = h >= ind["bb_up"]
    F["bb_close"] = c >= ind["bb_up"]
    for n in (20, 60):
        hi = h.shift(1).rolling(n).max()
        F[f"retest{n}"] = (h >= hi * 0.99) & (c < hi)                            # 碰前高（1% 內）沒收過
    # MACD 隔天關鍵價（以「隔天價格 = 今天收盤」來比）
    af, as_, ag = 2 / (P["macd_fast"] + 1), 2 / (P["macd_slow"] + 1), 2 / (P["macd_signal"] + 1)
    k = af - as_
    const = (1 - af) * ind["ema_fast"] - (1 - as_) * ind["ema_slow"]
    F["kp_cross"] = (ind["px_cross"] / c - 1) * 100       # >0：平盤就死叉／不會金叉
    F["kp_difup"] = (ind["px_difup"] / c - 1) * 100       # >0：平盤 DIF 就下彎
    F["kp_redsh"] = ((ind["hist"] / (1 - ag) + ind["dea"] - const) / k / c - 1) * 100   # >0：平盤紅柱就縮短
    F["dif_down"] = ind["dif"] < ind["dif"].shift(1)
    F["hist_peak"] = (ind["hist"] < ind["hist"].shift(1)) & (ind["hist"].shift(1) >= ind["hist"].shift(2))  # 紅/綠柱剛轉折
    F["dncnt"] = _streak(c < pc)
    # 自營自行、融資、融券、借券（張）
    inst = pd.read_sql("SELECT date,code,dp FROM inst", con)
    dp = inst.pivot(index="date", columns="code", values="dp").reindex(index=c.index, columns=c.columns)
    F["dp_pct"] = dp / vl * 100
    F["dp_streak"], F["dp_sstreak"] = _streak(dp > 0), _streak(dp < 0)
    mg = pd.read_sql("SELECT date,code,m_prev,m_bal,s_prev,s_bal FROM margin", con)
    mg["mchg"], mg["schg"] = mg.m_bal - mg.m_prev, mg.s_bal - mg.s_prev
    mok = c.index.isin(mg.date.unique())
    for kk in ("mchg", "schg"):
        x = mg.pivot(index="date", columns="code", values=kk).reindex(index=c.index, columns=c.columns)
        x[mok] = x[mok].fillna(0)
        F[f"{kk}_pct"] = x / vl * 100
        F[f"{kk}_streak"] = _streak(x > 0)
    mb = mg.pivot(index="date", columns="code", values="m_bal").reindex(index=c.index, columns=c.columns)
    F["m_use"] = mb / vl          # 融資餘額 / 當天量（倍）
    sb = pd.read_sql("SELECT date,code,sold FROM sbl", con)
    x = sb.pivot(index="date", columns="code", values="sold").reindex(index=c.index, columns=c.columns)
    sok = c.index.isin(sb.date.unique())
    x[sok] = x[sok].fillna(0)
    F["sbl_pct"] = x / vl * 100
    F["sbl_streak"] = _streak(x > 0)
    F["m_ok"] = pd.DataFrame(np.repeat(mok[:, None], c.shape[1], 1), index=c.index, columns=c.columns)
    con.close()
    idx = pd.MultiIndex.from_frame(df[["date", "code"]])
    E = pd.DataFrame({kk: f.stack().reindex(idx).values for kk, f in F.items()}, index=df.index)
    return pd.concat([df, E], axis=1)


def dt_streaks(df):
    """隔日沖分點連買天數（以該股票的交易日連續計；沒分點資料那天算中斷）"""
    df = df.sort_values(["code", "date"])
    b = (df.dt_net > 0).astype(int)
    g = df.code
    cs = b.groupby(g).cumsum()
    reset = cs.where(b == 0).groupby(g).ffill().fillna(0)
    df["dt_streak"] = (cs - reset).where(df.has_br)
    return df.sort_index()


# ---------- 條件 ----------
def cond_price(d):
    C = {}
    r5, r10, r20 = d.ret5, d.ret10, d.ret20
    C["5日漲5~10%"] = ("x_r5", _b(5, 10, r5))
    C["10日漲>15%"] = ("x_r10", r10 > 15)
    C["10日漲8~15%"] = ("x_r10", _b(8, 15, r10))
    C["20日漲>30%"] = ("x_r20", r20 > 30)
    C["20日漲15~30%"] = ("x_r20", _b(15, 30, r20))
    rally = (r10 > 8) | (r20 > 15)
    kc, kd, kr = d.kp_cross, d.kp_difup, d.kp_redsh
    red = d["hist"] > 0
    C["紅柱＋收<DIF下彎價"] = ("k_d", red & (kd > 0))
    C["紅柱＋收<紅柱縮短價"] = ("k_r", red & (kr > 0))
    C["紅柱＋收<死叉價（必定也<DIF下彎價）"] = ("k_2", red & (kc > 0) & (kd > 0))
    C["漲一波＋收<兩個關鍵價"] = ("k_2r", rally & red & (kc > 0) & (kd > 0))
    C["漲一波＋收<DIF下彎價"] = ("k_dr", rally & red & (kd > 0))
    C["漲一波＋紅柱縮短"] = ("k_rs", rally & red & (d["hist"] < d.hist_prev))
    C["DIF下彎"] = ("k_dd", d.dif_down.astype(bool))
    C["漲一波＋DIF下彎"] = ("k_ddr", rally & d.dif_down.astype(bool))
    C["死亡交叉（紅轉綠）"] = ("m_x", (d.hist_prev > 0) & (d["hist"] <= 0))
    C["漲一波＋死亡交叉"] = ("k_dx", rally & (d.hist_prev > 0) & (d["hist"] <= 0))
    C["綠柱＋收<金叉價（還沒金叉）"] = ("k_g", (d["hist"] <= 0) & (d.px_cross_d > 0))
    C["綠柱＋收<綠柱縮短價"] = ("k_gs", (d["hist"] < 0) & (d.px_shrink_d > 0))
    C["漲一波＋綠柱＋收<金叉價、綠柱縮短價"] = ("k_g2", rally & (d["hist"] < 0) & (d.px_cross_d > 0) & (d.px_shrink_d > 0))
    vs = d.vr5
    C["爆量（≥2倍5日均量）＋長上影≥3%"] = ("x_vu", (vs >= 2) & (d.upsh >= 3))
    C["量增（≥1.5倍）＋上影≥2%"] = ("x_vu2", (vs >= 1.5) & (d.upsh >= 2))
    C["爆量（≥2倍）創20日新高"] = ("x_vh", (vs >= 2) & d.brk20.astype(bool))
    C["爆量（≥2倍）創60日新高"] = ("x_vh6", (vs >= 2) & d.brk60.astype(bool))
    C["開高≥2%走低（收<開）"] = ("x_gw", (d.gap >= 2) & (d.body < 0))
    C["開高≥2%收跌（收<昨收）"] = ("x_gd", (d.gap >= 2) & (d.chg < 0))
    C["開高≥3%"] = ("x_g3", d.gap >= 3)
    C["連漲4天以上"] = ("p_st", d.upstreak >= 4)
    C["連跌3天以上"] = ("x_dn", d.dncnt >= 3)
    for n, cuts in ((5, (3, 6)), (10, (5, 10)), (20, (10, 20)), (60, (20, 40))):
        x = d[f"d_ma{n}"]
        C[f"乖離MA{n} {cuts[0]}~{cuts[1]}%"] = (f"x_d{n}", _b(cuts[0], cuts[1], x))
        C[f"乖離MA{n} >{cuts[1]}%"] = (f"x_d{n}", x >= cuts[1])
        C[f"乖離MA{n} <-{cuts[0]}%"] = (f"x_d{n}", x <= -cuts[0])
        C[f"從下碰MA{n}沒站上"] = (f"x_f{n}", d[f"fail_ma{n}"].astype(bool))
        C[f"今天跌破MA{n}"] = (f"x_b{n}", d[f"brk_ma{n}"].astype(bool))
    C["漲一波後跌破MA20"] = ("x_rb20", rally & d.brk_ma20.astype(bool))
    C["漲一波後跌破MA10"] = ("x_rb10", rally & d.brk_ma10.astype(bool))
    C["碰布林上軌"] = ("x_bb", d.bb_touch.astype(bool) & ~d.bb_close.astype(bool))
    C["收在布林上軌外"] = ("x_bb", d.bb_close.astype(bool))
    C["碰20日高沒過"] = ("x_rt20", d.retest20.astype(bool))
    C["碰60日高沒過"] = ("x_rt60", d.retest60.astype(bool))
    return {k: (f, v.fillna(False).astype(bool).values) for k, (f, v) in C.items()}


def cond_full(d):
    return {**conditions(d, chips=False), **cond_price(d)}


def cond_chips(d):
    C = {}
    p = d.dp_pct
    C["自營自行買超≥5%量"] = ("c_dp", p >= 5)
    C["自營自行賣超≥5%量"] = ("c_dp", p <= -5)
    C["自營自行連買3天以上"] = ("c_dps", d.dp_streak >= 3)
    C["自營自行連賣3天以上"] = ("c_dps", d.dp_sstreak >= 3)
    C["外資賣超≥10%量"] = ("c_fib", d.fi_pct <= -10)
    C["投信賣超≥5%量"] = ("c_itb", d.it_pct <= -5)
    C["外資賣、投信買"] = ("c_both", (d.fi < 0) & (d.it > 0))
    C["外資買、投信賣"] = ("c_both", (d.fi > 0) & (d.it < 0))
    C["外資連買5天以上"] = ("c_fis5", d.fi_streak >= 5)
    C["投信連買5天以上"] = ("c_its5", d.it_streak >= 5)
    s = d.fi_pct + d.it_pct + p.fillna(0)
    C["三大法人(外+投+自行)合計賣超≥5%量"] = ("c_sum", s <= -5)
    C["三大法人(外+投+自行)合計買超≥10%量"] = ("c_sum", s >= 10)
    m = d.m_ok.astype(bool)
    C["融資增≥5%量"] = ("c_m", m & (d.mchg_pct >= 5))
    C["融資增2~5%量"] = ("c_m", m & _b(2, 5, d.mchg_pct))
    C["融資減≥5%量"] = ("c_m", m & (d.mchg_pct <= -5))
    C["融資連增3天以上"] = ("c_ms", m & (d.mchg_streak >= 3))
    C["融資餘額≥當天量3倍"] = ("c_mu", m & (d.m_use >= 3))
    C["融券增≥2%量"] = ("c_s", m & (d.schg_pct >= 2))
    C["借券賣出≥5%量"] = ("c_sbl", m & (d.sbl_pct >= 5))
    C["借券賣出≥10%量"] = ("c_sblb", m & (d.sbl_pct >= 10))
    C["借券連賣3天以上"] = ("c_sbls", m & (d.sbl_streak >= 3))
    C = {k: (f, v.fillna(False).astype(bool).values) for k, (f, v) in C.items()}
    return {**conditions(d, chips=True, macd=False, price=False), **C}


def cond_dt(d):
    C = {}
    n, p, s = d.dt_net, d.dt_pct, d.dt_streak
    C["隔日沖分點買超"] = ("b_dt", n > 0)
    C["隔日沖分點賣超"] = ("b_dt", n < 0)
    C["隔日沖分點沒進出"] = ("b_dt", n == 0)
    C["隔日沖買超≥2%量"] = ("b_dtp", _b(2, 5, p))
    C["隔日沖買超≥5%量"] = ("b_dtp", _b(5, 10, p))
    C["隔日沖買超≥10%量"] = ("b_dtp", p >= 10)
    C["2家以上隔日沖買超"] = ("b_dtn", d.dt_nbr >= 2)
    C["3家以上隔日沖買超"] = ("b_dtn", d.dt_nbr >= 3)
    C["隔日沖連買第2天"] = ("b_dts", s == 2)
    C["隔日沖連買3天以上"] = ("b_dts", s >= 3)
    return {k: (f, v.fillna(False).astype(bool).values) for k, (f, v) in C.items()}


# ---------- 統計 ----------
def make_row(d, y, ys):
    h1 = (d.half == 1).values
    base = y.mean() * 100
    no, nc = d.n_open.values, d.n_close.values

    def row(nm, m):
        m = np.asarray(m, bool)
        n = int(m.sum())
        f = lambda mm: round(float(y[mm].mean() * 100), 1) if mm.sum() >= 10 else None
        return [nm, n, round(float(y[m].mean() * 100), 1), round(float(y[m].mean() * 100 / base), 2), f(m & h1), f(m & ~h1),
                round(float(ys[m].mean() * 100), 1), round(float(np.nanmean(no[m])), 2), round(float(np.nanmean(nc[m])), 2)]
    return base, row


def single(d, y, ys, C, min_n=30):
    base, row = make_row(d, y, ys)
    rows = [row(k, m) for k, (_, m) in C.items() if m.sum() >= min_n]
    return base, sorted(rows, key=lambda r: -r[2])


def combos(d, y, ys, C, top=15, min_lift=1.12):
    cb = combo_search(d, y, C, top=top, min_lift=min_lift)
    _, row = make_row(d, y, ys)
    out = []
    for r in cb:
        m = np.ones(len(d), bool)
        for k in r[0].split(" ＋ "):
            m &= C[k][1]
        out.append(row(r[0], m))
    return sorted(out, key=lambda r: -r[2])


def outcome(d):
    return (d.n_body < 0).astype(float).values, (d.n_body <= -1).astype(float).values


def branch_study(d):
    """個別分點：單日大買／大賣（≥2% 量）、連 2 天買／賣 → 隔天黑K"""
    con = _con()
    br = pd.read_sql("SELECT date,code,branch,buy,sell FROM broker", con)
    con.close()
    br = br.groupby(["date", "code", "branch"], as_index=False)[["buy", "sell"]].max()
    br["net"] = br.buy - br.sell
    cal = np.sort(d.date.unique())
    prev = dict(zip(cal[1:], cal[:-1]))
    vol = d.set_index(["date", "code"]).vol_lots
    br = br[br.set_index(["date", "code"]).index.isin(vol.index)].copy()
    br["pct"] = br.net / vol.reindex(pd.MultiIndex.from_frame(br[["date", "code"]])).values * 100
    key = br.set_index(["date", "code", "branch"]).net
    br["prev_net"] = key.reindex(pd.MultiIndex.from_arrays([br.date.map(prev), br.code, br.branch])).values
    y, ys = outcome(d)
    dd = d.assign(y=y, ys=ys).set_index(["date", "code"])[["y", "ys", "half", "n_open", "n_close"]]
    br = br.join(dd, on=["date", "code"])
    base = y.mean() * 100
    b1, b2 = y[d.half.values == 1].mean() * 100, y[d.half.values == 2].mean() * 100
    kinds = {"單日買超≥2%量": br.pct >= 2, "單日賣超≥2%量": br.pct <= -2,
             "連2天以上買超": (br.net > 0) & (br.prev_net > 0), "連2天以上賣超": (br.net < 0) & (br.prev_net < 0)}
    rows, ntest = [], 0
    for kind, m in kinds.items():
        e = br[m].drop_duplicates(["date", "code", "branch"])
        g = e.groupby("branch")
        st = pd.DataFrame({"n": g.size(), "r": g.y.mean() * 100, "rs": g.ys.mean() * 100,
                           "n1": g.half.apply(lambda s: (s == 1).sum()),
                           "r1": g.apply(lambda x: x.y[x.half == 1].mean() * 100),
                           "r2": g.apply(lambda x: x.y[x.half == 2].mean() * 100),
                           "no": g.n_open.mean(), "nc": g.n_close.mean(), "nstk": g.code.nunique()})
        st = st[st.n >= 30]
        ntest += len(st)
        st["z"] = (st.r / 100 - base / 100) / np.sqrt(base / 100 * (1 - base / 100) / st.n)
        ok = st[(st.n1 >= 10) & (st.n - st.n1 >= 10) & (st.r1 >= b1 * 1.1) & (st.r2 >= b2 * 1.1)]
        for b, r in ok.sort_values("r", ascending=False).head(10).iterrows():
            rows.append([f"{b}｜{kind}", int(r.n), round(r.r, 1), round(r.r / base, 2), round(r.r1, 1), round(r.r2, 1),
                         round(r.rs, 1), round(r.no, 2), round(r.nc, 2), int(r.nstk), round(r.z, 1)])
    return base, ntest, sorted(rows, key=lambda r: -r[2])


# ---------- 主程式 ----------
df = load_panel()
df = dt_streaks(extra_features(df))
tables, R = [], {}

d = universe(df)
y, ys = outcome(d)
base, rows = single(d, y, ys, cond_full(d))
R["base"] = [len(d), base, ys.mean() * 100, d.n_open.mean(), d.n_close.mean(), d.date.min(), d.date.max()]
show("全期間 單一", base, rows, 60)
tables.append(tbl(f"基準｜{d.date.min()}~{d.date.max()}", [["全部", len(d), round(base, 1), 1.0, round(y[d.half.values == 1].mean() * 100, 1),
                  round(y[d.half.values == 2].mean() * 100, 1), round(ys.mean() * 100, 1), round(d.n_open.mean(), 2), round(d.n_close.mean(), 2)]],
                  "黑K = 隔天收盤 < 隔天開盤；實體黑K = (隔天開 − 隔天收) ≥ 今天收盤的 1%", COLS))
tables.append(tbl(f"單一條件｜價量＋均線＋MACD｜{len(d):,} 筆，黑K 基準 {base:.1f}%｜黑K 率最高 30 個", rows[:30],
                  "lift = 黑K率 ÷ 基準；「漲一波」= 10 日漲 >8% 或 20 日漲 >15%；關鍵價以「隔天收平盤」來比", COLS))
tables.append(tbl("單一條件｜黑K 率最低 10 個（隔天比較不會黑K）", rows[-10:][::-1], cols=COLS))
key_names = [r for r in rows if any(s in r[0] for s in ("關鍵價", "死叉", "DIF下彎", "紅柱", "金叉價", "綠柱縮短價", "死亡交叉"))]
tables.append(tbl("MACD 3/7/3 關鍵價與狀態（使用者想法：漲一波後跌破關鍵價）", key_names, cols=COLS))
cb = combos(d, y, ys, cond_full(d))
show("全期間 組合", base, cb)
tables.append(tbl("2~3 個條件組合｜價量＋MACD｜n≥30、前後半段 lift 都 ≥1.12，依黑K率排", cb, cols=COLS))

dc = universe(df, chips=True)
yc, ysc = outcome(dc)
Cc = cond_chips(dc)
bc, rc = single(dc, yc, ysc, Cc)
show("法人期間 單一", bc, rc, 60)
tables.append(tbl(f"單一條件｜三大法人＋融資券＋借券｜{dc.date.min()}~{dc.date.max()}（{len(dc):,} 筆，黑K 基準 {bc:.1f}%）", rc,
                  "買賣超以佔當天成交量 % 計；融資、借券資料到 2026-10-22", COLS))
cc = combos(dc, yc, ysc, {**cond_full(dc), **Cc})
show("法人期間 組合", bc, cc)
tables.append(tbl(f"2~3 個條件組合｜含籌碼｜{dc.date.min()} 起（基準 {bc:.1f}%）", cc, cols=COLS))

db = dc[dc.has_br.astype(bool)].copy()
dates = np.sort(db.date.unique())
db["half"] = np.where(db.date <= dates[len(dates) // 2], 1, 2)
yb, ysb = outcome(db)
Cd = cond_dt(db)
bb, rb = single(db, yb, ysb, Cd, min_n=20)
show("隔日沖", bb, rb)
tables.append(tbl(f"隔日沖分點｜{db.date.min()}~{db.date.max()}，只有有抓分點的股票（{len(db):,} 筆，黑K 基準 {bb:.1f}%）", rb,
                  "隔日沖分點：" + "、".join(DT_BRANCHES) + "；分點資料只有每檔買賣各前 15 名", COLS))
_, rowb = make_row(db, yb, ysb)
Cf = cond_full(db)
dtx = []
for dn, dm in (("隔日沖買超≥5%量", Cd["隔日沖買超≥5%量"][1] | Cd["隔日沖買超≥10%量"][1]), ("隔日沖連買2天以上", (db.dt_streak >= 2).values)):
    dtx.append(rowb(dn, dm))
    for k in ("今天漲停", "盤中觸漲停沒鎖住", "實體 紅K>3%", "上影線≥2%", "漲一波＋收<兩個關鍵價", "紅柱縮短", "5日漲5~10%",
              "20日漲15~30%", "收在布林上軌外", "爆量（≥2倍5日均量）＋長上影≥3%", "跌破MA5"):
        m = dm & Cf[k][1]
        if m.sum() >= 20:
            dtx.append(rowb(f"　{dn}＋{k}", m))
show("隔日沖 × 價量", bb, dtx)
tables.append(tbl("隔日沖分點買超 × 價量／MACD（n≥20 才列）", dtx,
                  "組合搜尋時，加入隔日沖條件的組合沒有一個能在前後半段都穩定提高黑K率", COLS))

# 使用者想法：漲一波（不同幅度）× MACD 關鍵價狀態
_, row = make_row(d, y, ys)
Cm = cond_full(d)
red = (d["hist"] > 0).values
kc, kd = (d.kp_cross > 0).values, (d.kp_difup > 0).values
states = {"紅柱、收在兩個關鍵價之上": red & ~kd, "紅柱、收<DIF下彎價但>死叉價": red & kd & ~kc, "紅柱、收<死叉價（平盤就死叉）": red & kc,
          "今天死亡交叉": Cm["死亡交叉（紅轉綠）"][1], "綠柱、收<金叉價＋綠柱縮短價": Cm["綠柱＋收<綠柱縮短價"][1] & Cm["綠柱＋收<金叉價（還沒金叉）"][1]}
kx = []
for rn, rm in (("5日漲5~10%", Cm["5日漲5~10%"][1]), ("5日漲>10%", Cm["5日報酬>10%"][1]), ("10日漲>15%", Cm["10日漲>15%"][1]),
               ("20日漲>30%", Cm["20日漲>30%"][1])):
    for sn, sm in states.items():
        if (rm & sm).sum() >= 30:
            kx.append(row(f"{rn}｜{sn}", rm & sm))
show("漲一波 × 關鍵價", base, kx)
fx = []
for ma in (10, 20, 60):
    fm = Cm[f"從下碰MA{ma}沒站上"][1]
    fx.append(row(f"從下碰MA{ma}沒站上", fm))
    for rn, rm in (("5日漲0~5%", (d.ret5 >= 0).values & (d.ret5 < 5).values), ("5日漲5~10%", Cm["5日漲5~10%"][1]),
                   ("5日漲>10%", Cm["5日報酬>10%"][1]), ("今天紅K>3%", Cm["實體 紅K>3%"][1]), ("上影線≥2%", Cm["上影線≥2%"][1])):
        if (fm & rm).sum() >= 30:
            fx.append(row(f"　從下碰MA{ma}沒站上＋{rn}", fm & rm))
show("反彈碰均線沒站上", base, fx)
tables.append(tbl("反彈碰均線沒站上（昨收在均線下、今天最高碰到均線、收盤還在均線下）", fx, cols=COLS))
tables.append(tbl("使用者想法｜漲一波 × MACD 3/7/3 關鍵價（以隔天收平盤來比）", kx,
                  "紅柱時：收<DIF下彎價 = 隔天平盤 DIF 就往下；收<死叉價 = 隔天平盤就死叉（一定也<DIF下彎價）", COLS))

bbase, ntest, brows = branch_study(db)
show(f"個別分點（測了 {ntest} 組）", bbase, brows)
tables.append(tbl(f"個別分點｜買／賣後隔天黑K 偏高（n≥30、前後半段都 ≥ 基準 1.1 倍；共測 {ntest} 組 分點×行為）", brows,
                  "z = 跟基準比的標準分數；測了這麼多組，z<3 的很可能只是運氣", COLS + ["股票數", "z"]))
R["chips_base"], R["br_base"], R["ntest"] = bc, bb, ntest
save_out("study5", {"R": R, "tables": tables})
