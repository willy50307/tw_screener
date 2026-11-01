"""回測研究共用：從 data/subset.db（唯讀）建出「每檔每天」的特徵表＋隔天結果，以及條件統計工具。
不會碰 stocks.db。用法：from common import load_panel, cond_table, combo_search
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from indicators import indicator_cols  # noqa: E402

DB = os.path.join(BASE, "data", "subset.db")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "panel.pkl")
P = {"macd_fast": 3, "macd_slow": 7, "macd_signal": 3, "price_source": "DI", "shrink_pct": 40, "max_dif_pct": 0}
START = "2025-05-01"
DT_BRANCHES = ["凱基-台北", "凱基-站前", "凱基-城中", "凱基-松山", "凱基-復興", "統一-城中", "國票-安和", "國票-敦北法人",
               "元大-土城永寧", "富邦-建國", "富邦-仁愛", "群益金鼎-大安", "康和-永和"]


def _tick(p):
    return np.select([p < 10, p < 50, p < 100, p < 500, p < 1000], [0.01, 0.05, 0.1, 0.5, 1.0], 5.0)


def limit_up_price(prev):
    raw = prev * 1.1
    t = _tick(raw)
    return np.floor(raw / t + 1e-6) * t


def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def load_panel(rebuild=False):
    if not rebuild and os.path.exists(CACHE) and os.path.getmtime(CACHE) > os.path.getmtime(DB):
        return pd.read_pickle(CACHE)
    con = _con()
    px = pd.read_sql("SELECT code,date,name,open,high,low,close,volume FROM prices", con)
    px = px[px.code.str.fullmatch(r"[1-9]\d{3}")]
    names = px.groupby("code").name.last()
    W = {k: px.pivot(index="date", columns="code", values=k).sort_index() for k in ("open", "high", "low", "close", "volume")}
    o, h, l, c, v = (W[k] for k in ("open", "high", "low", "close", "volume"))
    vl = v / 1000                                  # 張
    ind = indicator_cols(W, P)
    hist, dif = ind["hist"], ind["dif"]
    hp = hist.shift(1)
    pc = c.shift(1)
    lu_px = pd.DataFrame(limit_up_price(pc.values), index=c.index, columns=c.columns)
    lu = (c >= lu_px - 1e-6) & pc.notna()
    touch = (h >= lu_px - 1e-6) & ~lu & pc.notna()
    F = {}
    F["close"], F["vol_lots"] = c, vl
    F["is_lu"], F["touch_lu"] = lu, touch
    F["hist"], F["hist_prev"], F["dif"], F["dif_prev"] = hist, hp, dif, dif.shift(1)
    F["hist_pct"] = hist / c * 100
    F["px_cross_d"] = (ind["px_cross"] / c - 1) * 100
    F["px_shrink_d"] = (np.maximum(ind["px_shrink"], ind["px_difup"]) / c - 1) * 100
    F["chg"] = (c / pc - 1) * 100
    F["body"] = (c - o) / pc * 100
    F["upsh"] = (h - np.maximum(o, c)) / pc * 100
    F["losh"] = (np.minimum(o, c) - l) / pc * 100
    F["gap"] = (o / pc - 1) * 100
    F["pos"] = ((c - l) / (h - l)).where(h > l, 1.0)
    F["vr5"] = v / v.shift(1).rolling(5).mean()
    F["vr20"] = v / v.shift(1).rolling(20).mean()
    for n in (5, 20, 60):
        F[f"ab_ma{n}"] = c > ind[f"ma{n}"]
    F["brk20"] = c > h.shift(1).rolling(20).max()
    F["brk60"] = c > h.shift(1).rolling(60).max()
    F["upstreak"] = _streak(c > pc)
    F["ret5"] = (c / c.shift(5) - 1) * 100
    F["ret20"] = (c / c.shift(20) - 1) * 100
    F["lu_prev20"] = lu.shift(1).rolling(20, min_periods=1).sum()   # t-20..t-1 的漲停次數
    # 隔天、之後的結果
    o1, c1 = o.shift(-1), c.shift(-1)
    F["n_open"] = (o1 / c - 1) * 100
    F["n_close"] = (c1 / c - 1) * 100
    F["n_body"] = (c1 - o1) / c * 100
    F["n_lu"] = lu.shift(-1).astype(float).where(c1.notna())
    l3 = sum(lu.shift(-k).fillna(False).astype(int) for k in (1, 2, 3))
    l5 = sum(lu.shift(-k).fillna(False).astype(int) for k in (1, 2, 3, 4, 5))
    F["n_lu3"] = (l3 > 0).astype(float).where(c.shift(-3).notna())
    F["n_lu5"] = (l5 > 0).astype(float).where(c.shift(-5).notna())
    # 籌碼（inst 單位：張）
    # 2025-03~07 只有上市（約 700 檔/天）、8~9 月缺，2025-10-20 起才是全市場 → 只用「全市場」的日子
    inst = pd.read_sql("SELECT date,code,fi,it,dh FROM inst", con)
    full = inst.groupby("date").size().pipe(lambda s: s[s >= 1500].index)
    ok = c.index.isin(full)
    F["chips_ok"] = pd.DataFrame(np.repeat(ok[:, None], c.shape[1], 1), index=c.index, columns=c.columns)
    for k in ("fi", "it", "dh"):
        x = inst.pivot(index="date", columns="code", values=k).reindex(index=c.index, columns=c.columns)
        x[ok] = x[ok].fillna(0)
        x[~ok] = np.nan
        F[k] = x
        F[f"{k}_pct"] = x / vl * 100
        F[f"{k}_streak"] = _streak(x > 0)
        F[f"{k}_sstreak"] = _streak(x < 0)
        F[f"{k}_3d_pct"] = x.rolling(3).sum() / vl.rolling(3).sum() * 100
    # 隔日沖分點（只有有分點資料的日子）
    br = pd.read_sql("SELECT date,code,branch,buy,sell FROM broker", con)
    has = br.groupby(["date", "code"]).size().rename("n")
    dt = br[br.branch.isin(DT_BRANCHES)].assign(net=lambda d: d.buy - d.sell)
    dtn = dt.groupby(["date", "code"]).net.sum()
    dtb = dt[dt.net > 0].groupby(["date", "code"]).size()
    con.close()

    idx = c.stack().dropna().index
    df = pd.DataFrame({k: f.stack().reindex(idx) for k, f in F.items()})
    df.index.names = ["date", "code"]
    df = df.reset_index()
    df["name"] = df.code.map(names)
    key = pd.MultiIndex.from_frame(df[["date", "code"]])
    df["has_br"] = key.isin(has.index)
    df["dt_net"] = dtn.reindex(key).fillna(0).values
    df["dt_nbr"] = dtb.reindex(key).fillna(0).values
    df.loc[~df.has_br, ["dt_net", "dt_nbr"]] = np.nan
    df["dt_pct"] = df.dt_net / df.vol_lots * 100
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    df.to_pickle(CACHE)
    return df


def _streak(b):
    b = b.fillna(False).astype(int)
    cs = b.cumsum()
    return cs - cs.where(b == 0).ffill().fillna(0)


def universe(df, start=START, chips=False):
    """chips=True：只取三大法人資料是全市場的日子（2025-10-20 起）"""
    last = df.date.max()
    m = (df.close >= 10) & (df.vol_lots >= 500) & (df.date >= start) & (df.date < last) & df.n_close.notna()
    if chips:
        m &= df.chips_ok.astype(bool)
    d = df[m].copy()
    dates = np.sort(d.date.unique())
    d["half"] = np.where(d.date <= dates[len(dates) // 2], 1, 2)
    return d


def _b(lo, hi, s):
    return (s >= lo) & (s < hi)


def conditions(d, chips=True, macd=True, price=True, broker=False):
    """回傳 {名稱: (家族, bool Series)}；同一家族的不互相組合"""
    C = {}
    if macd:
        h, hp = d["hist"], d.hist_prev
        C["MACD 黃金交叉"] = ("m_x", (hp <= 0) & (h > 0))
        C["綠柱縮短40%＋DIF上升"] = ("m_x", (hp < 0) & (h < 0) & (h >= 0.6 * hp) & (d.dif > d.dif_prev))
        C["紅柱變長"] = ("m_x", (hp > 0) & (h > hp))
        C["紅柱縮短"] = ("m_x", (hp > 0) & (h > 0) & (h < hp))
        C["綠柱變長"] = ("m_x", (hp < 0) & (h < hp))
        for lo, hi, nm in ((-99, -2, "<-2%"), (-2, -1, "-2~-1%"), (-1, -0.5, "-1~-0.5%"), (-0.5, 0, "-0.5~0%")):
            C[f"綠柱長度 {nm}"] = ("m_len", _b(lo, hi, d.hist_pct))
        for lo, hi, nm in ((0, 0.5, "0~0.5%"), (0.5, 1, "0.5~1%"), (1, 99, ">1%")):
            C[f"紅柱長度 {nm}"] = ("m_len", (d["hist"] > 0) & _b(lo, hi, d.hist_pct))
        x = d.px_cross_d.where(d["hist"] <= 0)
        for lo, hi, nm in ((-99, 0, "≤0%（平盤就交叉）"), (0, 2, "0~2%"), (2, 4, "2~4%"), (4, 7, "4~7%"), (7, 99, ">7%")):
            C[f"距金叉價 {nm}"] = ("m_cx", _b(lo, hi, x))
        y = d.px_shrink_d.where(d["hist"] < 0)
        for lo, hi, nm in ((-99, 0, "≤0%"), (0, 2, "0~2%"), (2, 5, "2~5%"), (5, 99, ">5%")):
            C[f"距綠柱縮短價 {nm}"] = ("m_sx", _b(lo, hi, y))
        C["DIF>0"] = ("m_dif", d.dif > 0)
        C["DIF≤0"] = ("m_dif", d.dif <= 0)
    if price:
        for lo, hi, nm in ((-99, -5, "<-5%"), (-5, -2, "-5~-2%"), (-2, 0, "-2~0%"), (0, 2, "0~2%"), (2, 5, "2~5%"), (5, 7.5, "5~7.5%"), (7.5, 99, "≥7.5%")):
            C[f"漲跌 {nm}"] = ("p_chg", _b(lo, hi, d.chg))
        for lo, hi, nm in ((-99, -3, "黑K>3%"), (-3, -1, "黑K 1~3%"), (-1, 1, "小實體±1%"), (1, 3, "紅K 1~3%"), (3, 99, "紅K>3%")):
            C[f"實體 {nm}"] = ("p_body", _b(lo, hi, d.body))
        C["上影線≥2%"] = ("p_up", d.upsh >= 2)
        C["上影線<0.5%"] = ("p_up", d.upsh < 0.5)
        C["下影線≥2%"] = ("p_lo", d.losh >= 2)
        C["下影線<0.5%"] = ("p_lo", d.losh < 0.5)
        C["跳空開高≥2%"] = ("p_gap", d.gap >= 2)
        C["開平盤附近±0.5%"] = ("p_gap", d.gap.abs() < 0.5)
        C["跳空開低≤-2%"] = ("p_gap", d.gap <= -2)
        C["收在當日高檔（≥90%）"] = ("p_pos", d.pos >= 0.9)
        C["收在當日中段"] = ("p_pos", (d.pos >= 0.3) & (d.pos < 0.7))
        C["收在當日低檔（<30%）"] = ("p_pos", d.pos < 0.3)
        for lo, hi, nm in ((0, 0.7, "<0.7"), (0.7, 1.5, "0.7~1.5"), (1.5, 3, "1.5~3"), (3, 999, "≥3")):
            C[f"量/5日均量 {nm}"] = ("p_vr5", _b(lo, hi, d.vr5))
        C["量/20日均量≥2"] = ("p_vr20", d.vr20 >= 2)
        C["量/20日均量<0.8"] = ("p_vr20", d.vr20 < 0.8)
        C["站上MA5"] = ("p_ma5", d.ab_ma5.astype(bool))
        C["跌破MA5"] = ("p_ma5", ~d.ab_ma5.astype(bool))
        C["站上MA20"] = ("p_ma20", d.ab_ma20.astype(bool))
        C["跌破MA20"] = ("p_ma20", ~d.ab_ma20.astype(bool))
        C["站上MA60"] = ("p_ma60", d.ab_ma60.astype(bool))
        C["跌破MA60"] = ("p_ma60", ~d.ab_ma60.astype(bool))
        C["突破20日高"] = ("p_brk20", d.brk20.astype(bool))
        C["突破60日高"] = ("p_brk60", d.brk60.astype(bool))
        C["連漲1天"] = ("p_st", d.upstreak == 1)
        C["連漲2天"] = ("p_st", d.upstreak == 2)
        C["連漲3天以上"] = ("p_st", d.upstreak >= 3)
        C["5日報酬>10%"] = ("p_r5", d.ret5 > 10)
        C["5日報酬<-5%"] = ("p_r5", d.ret5 < -5)
        C["20日報酬>20%"] = ("p_r20", d.ret20 > 20)
        C["20日報酬<-10%"] = ("p_r20", d.ret20 < -10)
        C["今天漲停"] = ("p_lu", d.is_lu.astype(bool))
        C["盤中觸漲停沒鎖住"] = ("p_lu", d.touch_lu.astype(bool))
        C["近20日有漲停"] = ("p_lu20", d.lu_prev20 > 0)
    if chips:
        nm = {"fi": "外資", "it": "投信", "dh": "自營避險"}
        for k, z in nm.items():
            p = d[f"{k}_pct"]
            C[f"{z}買超≥5%量"] = (f"c_{k}", p >= 5)
            C[f"{z}買超≥10%量"] = (f"c_{k}b", p >= 10)
            C[f"{z}買超≥20%量"] = (f"c_{k}c", p >= 20)
            C[f"{z}賣超≥5%量"] = (f"c_{k}", p <= -5)
            C[f"{z}連買3天以上"] = (f"c_{k}s", d[f"{k}_streak"] >= 3)
            C[f"{z}連賣3天以上"] = (f"c_{k}s", d[f"{k}_sstreak"] >= 3)
            C[f"{z}3日買超≥5%量"] = (f"c_{k}3", d[f"{k}_3d_pct"] >= 5)
        C["外資投信同買"] = ("c_both", (d.fi > 0) & (d.it > 0))
        C["外資投信同賣"] = ("c_both", (d.fi < 0) & (d.it < 0))
    if broker:
        C["隔日沖分點買超"] = ("b_dt", d.dt_net > 0)
        C["隔日沖分點買超≥5%量"] = ("b_dt5", d.dt_pct >= 5)
        C["隔日沖分點賣超"] = ("b_dt", d.dt_net < 0)
        C["2家以上隔日沖買超"] = ("b_dtn", d.dt_nbr >= 2)
    return {k: (f, v.fillna(False).astype(bool).values) for k, (f, v) in C.items()}


def _stats(mask, d, y):
    n = int(mask.sum())
    if n == 0:
        return n, np.nan, np.nan, np.nan
    return n, y[mask].mean() * 100, d.n_open.values[mask].mean(), d.n_close.values[mask].mean()


def cond_table(d, y, C, min_n=30):
    """單一條件表：條件, 次數, 機率%, lift, 前半%, 後半%, 隔天開盤%, 隔天收盤%"""
    y = np.asarray(y, float)
    base = y.mean() * 100
    h1, h2 = (d.half == 1).values, (d.half == 2).values
    rows = []
    for k, (_, m) in C.items():
        n, r, no, nc = _stats(m, d, y)
        if n < min_n:
            continue
        r1 = y[m & h1].mean() * 100 if (m & h1).any() else np.nan
        r2 = y[m & h2].mean() * 100 if (m & h2).any() else np.nan
        rows.append([k, n] + [round(float(v), p) for v, p in ((r, 1), (r / base, 2), (r1, 1), (r2, 1), (no, 2), (nc, 2))])
    return base, rows


def combo_search(d, y, C, min_n=30, depth=3, top=12, min_lift=1.1, half_n=20, sort="lift"):
    """2~3 個條件的組合；要求 n≥min_n、前後半段各自 lift ≥ min_lift（相對各半段基準）"""
    y = np.asarray(y, float)
    names = list(C)
    fam = [C[k][0] for k in names]
    M = np.column_stack([C[k][1] for k in names]).astype(np.float32)
    h1 = (d.half == 1).values.astype(np.float32)
    h2 = 1 - h1
    b1, b2 = y[h1 > 0].mean(), y[h2 > 0].mean()
    base = y.mean()
    no, nc = np.nan_to_num(d.n_open.values).astype(np.float32), np.nan_to_num(d.n_close.values).astype(np.float32)
    out = {}

    def scan(W, prefix_idx):
        # W: 前綴條件的遮罩（float）；回傳每個 j 的統計
        A = M * W[:, None]
        n = A.sum(0)
        n1 = (A * h1[:, None]).sum(0)
        hit = A.T @ y.astype(np.float32)
        hit1 = A.T @ (y * h1).astype(np.float32)
        so, sc = A.T @ no, A.T @ nc
        for j in range(len(names)):
            if j in prefix_idx or fam[j] in {fam[i] for i in prefix_idx} or n[j] < min_n:
                continue
            n2 = n[j] - n1[j]
            if n1[j] < half_n or n2 < half_n:
                continue
            r1, r2 = hit1[j] / n1[j], (hit[j] - hit1[j]) / n2
            if r1 < b1 * min_lift or r2 < b2 * min_lift:
                continue
            key = tuple(sorted([names[i] for i in prefix_idx] + [names[j]]))
            if key in out:
                continue
            out[key] = [" ＋ ".join(key), int(n[j]), round(hit[j] / n[j] * 100, 1), round(hit[j] / n[j] / base, 2),
                        round(r1 * 100, 1), round(r2 * 100, 1), round(so[j] / n[j], 2), round(sc[j] / n[j], 2), min(r1 / b1, r2 / b2) if sort == "lift" else max(r1 / b1, r2 / b2)]

    for i in range(len(names)):
        scan(M[:, i], [i])
    if depth >= 3:
        pairs = sorted(out.values(), key=lambda r: -r[8] if sort == "lift" else r[8])[:40]
        for r in pairs:
            idx = [names.index(k) for k in r[0].split(" ＋ ")]
            scan(M[:, idx[0]] * M[:, idx[1]], idx)
    rows = list(out.values())
    rows.sort(key=lambda r: (-r[8] if sort == "lift" else r[8], -r[1]))   # 依「比較差的那半段」的 lift 排，避免只靠某一段
    return [[r[0], r[1]] + [round(float(v), 2) for v in r[2:8]] for r in _dedup(rows, top)]


def _dedup(rows, top):
    """避免同一組條件換個說法一直重複：已選的組合若是新組合的子集合且 lift 差不多就略過"""
    keep = []
    for r in rows:
        s = set(r[0].split(" ＋ "))
        if any(set(k[0].split(" ＋ ")) < s or set(k[0].split(" ＋ ")) > s for k in keep if abs(k[3] - r[3]) < 0.15):
            continue
        keep.append(r)
        if len(keep) >= top:
            break
    return keep


COLS = ["條件", "次數", "機率%", "lift", "前半段%", "後半段%", "隔天開盤%", "隔天收盤%"]


def show(title, base, rows, n=40):
    print(f"\n== {title}  基準 {base:.1f}% ==")
    for r in rows[:n]:
        print("  ", r)


def tbl(title, rows, note="", cols=None):
    return {"title": title, "columns": cols or COLS, "rows": rows, "note": note,
            "signed": ["隔天開盤%", "隔天收盤%"]}


def study_tables(label, d, y, dc, yc, cf, cc_, top_single=20, bottom=8, top_combo=12, min_lift=1.1, extra_note=""):
    """標準輸出：全期間單一條件（價量＋MACD）、法人期間單一條件（籌碼＋分點）、全期間組合、法人期間組合"""
    out = []
    C_full, C_chips = cf(d), cc_(dc)
    base, rows = cond_table(d, y, C_full)
    show(f"{label} 單一條件（全期間）", base, sorted(rows, key=lambda r: -r[3]))
    srt = sorted(rows, key=lambda r: -r[3])
    out.append(tbl(f"單一條件｜價量＋MACD｜{d.date.min()}~{d.date.max()}（{len(d):,} 筆，基準 {base:.1f}%）｜lift 最高 {top_single} 個",
                   srt[:top_single], f"lift = 機率 ÷ 基準；前半段／後半段 = 期間切兩半各自的機率{extra_note}"))
    out.append(tbl(f"單一條件｜lift 最低 {bottom} 個（要避開的）", srt[-bottom:][::-1]))
    bc, rc = cond_table(dc, yc, C_chips)
    rc = sorted(rc, key=lambda r: -r[3])
    show(f"{label} 籌碼單一條件", bc, rc)
    out.append(tbl(f"單一條件｜三大法人＋隔日沖分點｜{dc.date.min()}~{dc.date.max()}（{len(dc):,} 筆，基準 {bc:.1f}%）", rc,
                   "法人買賣超以「佔當天成交量 %」計；隔日沖分點只有 2026-04-23 起、且只有有抓分點的股票"))
    cb = combo_search(d, y, C_full, top=top_combo, min_lift=min_lift)
    show(f"{label} 組合（全期間）", base, cb)
    out.append(tbl(f"2~3 個條件組合｜價量＋MACD｜n≥30、前後半段 lift 都 ≥{min_lift}", cb))
    C_all = {**cf(dc), **C_chips}
    cc = combo_search(dc, yc, C_all, top=top_combo, min_lift=min_lift)
    show(f"{label} 組合（法人期間）", bc, cc)
    out.append(tbl(f"2~3 個條件組合｜含籌碼｜{dc.date.min()} 起（基準 {bc:.1f}%）｜n≥30、前後半段 lift 都 ≥{min_lift}", cc))
    return base, bc, out


def save_out(name, obj):
    import json
    p = os.path.join(os.path.dirname(CACHE), name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=float)
