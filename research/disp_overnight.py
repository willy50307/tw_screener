"""處置股隔日沖研究：各進場日（D-1、處置第1~5天/最後一天、出關日、出關+1、+2）收盤買，隔天賣的統計，
並對最佳進場日做日K型態拆解。唯讀 data/stocks.db（disposal、prices 表），只寫 research/out/disp_overnight*.json/csv。
定義：
  處置期間 = disposal 表 start~end（同一 code+start+end 去重）；處置第k天 = 該股在 [start,end] 內第k根K棒
  D-1 = 處置第1天的前一根K棒；出關日 R0 = 處置最後一根K棒的下一根K棒；R1/R2 = 再下一/兩根
  隔天 = 進場K棒的下一根K棒（該股下一個有成交的交易日）
  成本 0.585% = 手續費 0.1425%x2 + 證交稅 0.3%（無折扣）
  只取普通股：代號 4 碼、首碼 1~9；價格為未還原原始價
"""
import json, os, re, sqlite3, sys
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "stocks.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "disp_overnight.json")
COST = 0.585
NEW_RULE = "2026-08-10"
TPS = (2, 3, 4)


def tick(p):
    return np.select([p < 10, p < 50, p < 100, p < 500, p < 1000], [0.01, 0.05, 0.1, 0.5, 1.0], 5.0)


def lu_price(prev):
    raw = prev * 1.1; t = tick(raw); return np.floor(raw / t + 1e-6) * t


def ld_price(prev):
    raw = prev * 0.9; t = tick(raw); return np.ceil(raw / t - 1e-6) * t


def r2(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 2)


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
dis = pd.read_sql("SELECT market,code,name,ann,start,end,cond,measure,detail FROM disposal", con)
dis = dis[dis.code.str.fullmatch(r"[1-9]\d{3}")]
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_num(s):
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, b = s.split("十", 1)
        return (CN.get(a, 1) if a else 1) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s)


def declared_len(s):
    m = re.search(r"[起﹝（(]\s*([0-9一二三四五六七八九十]+)\s*個營業日", s or "")
    return cn_num(m.group(1)) if m else None


dis["declared"] = dis.detail.map(declared_len)
dis = dis[dis.measure.fillna("") != "人工管制撮合"]   # 變更交易方法（全額交割、分盤集合競價）不是一般處置，排除
dis["nth"] = np.where(dis.measure.fillna("").str.contains("再次|二"), 2, 1)
dis = dis.sort_values("ann").drop_duplicates(["code", "start", "end"], keep="last")
codes = sorted(dis.code.unique())
q = "SELECT code,date,open,high,low,close,volume FROM prices WHERE date>='2025-09-01' AND code IN (%s)" % ",".join("?" * len(codes))
px = pd.read_sql(q, con, params=codes)
mkt_days = sorted(r[0] for r in con.execute("SELECT date FROM prices WHERE code='2330' AND date>='2025-09-01'"))
con.close()
last_date = px.date.max()

rows, periods_info = [], []
for code, g in px.groupby("code"):
    g = g.sort_values("date").reset_index(drop=True)
    g = g[(g.open > 0) & (g.close > 0)].reset_index(drop=True)   # 沒成交的日子不算K棒
    D = g.date.tolist(); O, H, L, C, V = (g[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(g)
    pc = np.r_[np.nan, C[:-1]]
    lu = C >= lu_price(pc) - 1e-6; ld = C <= ld_price(pc) + 1e-6
    ma5 = pd.Series(C).rolling(5).mean().to_numpy(); ma20 = pd.Series(C).rolling(20).mean().to_numpy()
    v5 = pd.Series(V).shift(1).rolling(5).mean().to_numpy()
    src = pd.Series((H + L + 2 * C) / 4)
    dif = (src.ewm(span=3, adjust=False).mean() - src.ewm(span=7, adjust=False).mean())
    hist = (dif - dif.ewm(span=3, adjust=False).mean()).to_numpy(); dif = dif.to_numpy()
    all_p = dis[dis.code == code]
    in_disp = np.zeros(n, bool)
    for r in all_p.itertuples():
        in_disp |= (np.array(D) >= r.start) & (np.array(D) <= r.end)
    for r in all_p.itertuples():
        idx = [i for i, t in enumerate(D) if r.start <= t <= r.end]
        if not idx or idx[0] == 0:
            continue
        s_i, e_i = idx[0], idx[-1]
        ended = r.end < last_date
        mlen = sum(1 for t in mkt_days if r.start <= t <= r.end)
        L_ = int(r.declared) if r.declared == r.declared and r.declared is not None else mlen
        grp = "5" if L_ == 5 else ("10" if L_ == 10 else "other")
        periods_info.append(dict(code=code, start=r.start, end=r.end, declared=r.declared, mkt_len=mlen, bars=len(idx),
                                 ended=ended, nth=int(r.nth)))
        ent = {"D-1": s_i - 1}
        for k in range(1, 6):
            if k <= len(idx):
                ent[f"D{k}"] = idx[k - 1]
        if ended:
            ent["Dlast"] = e_i
            for k in range(3):
                if e_i + 1 + k < n:
                    ent[f"R{k}"] = e_i + 1 + k
        for lab, i in ent.items():
            if i + 1 >= n or i < 1:
                continue
            j = i + 1
            row = dict(code=code, start=r.start, end=r.end, len_grp=grp, declared=L_, nth=int(r.nth), entry=lab,
                       date=D[i], next_date=D[j], new_rule=r.start >= NEW_RULE,
                       next_in_disp=bool(in_disp[j]), entry_in_other_disp=bool(lab[0] == "R" and in_disp[i]),
                       n_open=(O[j] / C[i] - 1) * 100, n_close=(C[j] / C[i] - 1) * 100, n_high=(H[j] / C[i] - 1) * 100,
                       n_red=C[j] > O[j], n_lu=bool(lu[j]),
                       chg=(C[i] / pc[i] - 1) * 100, is_lu=bool(lu[i]), is_ld=bool(ld[i]),
                       body=(C[i] - O[i]) / pc[i] * 100, upsh=(H[i] - max(O[i], C[i])) / pc[i] * 100,
                       losh=(min(O[i], C[i]) - L[i]) / pc[i] * 100, gap=(O[i] / pc[i] - 1) * 100,
                       vr5=V[i] / v5[i] if v5[i] > 0 else np.nan,
                       cum=(C[i] / C[s_i - 1] - 1) * 100 if lab != "D-1" else np.nan,
                       ab_ma5=C[i] > ma5[i] if ma5[i] == ma5[i] else np.nan, ab_ma20=C[i] > ma20[i] if ma20[i] == ma20[i] else np.nan,
                       hist=hist[i], hist_prev=hist[i - 1], dif=dif[i], dif_prev=dif[i - 1], close=C[i])
            for X in TPS:
                t = O[j] * (1 + X / 100)
                row[f"tp{X}"] = ((t if H[j] >= t else C[j]) / C[i] - 1) * 100
                row[f"tp{X}_hit"] = H[j] >= t
            rows.append(row)

df = pd.DataFrame(rows)
df["win"] = df.n_close > 0


def stats(d):
    if len(d) == 0:
        return {"n": 0}
    o = {"n": int(len(d)), "open": r2(d.n_open.mean()), "close": r2(d.n_close.mean()), "close_med": r2(d.n_close.median()),
         "high": r2(d.n_high.mean()), "win": r2(d.win.mean() * 100), "red": r2(d.n_red.mean() * 100),
         "net_open": r2(d.n_open.mean() - COST), "net_close": r2(d.n_close.mean() - COST), "open_win": r2((d.n_open > 0).mean() * 100),
         "next_lu": r2(d.n_lu.mean() * 100)}
    for X in TPS:
        o[f"tp{X}_net"] = r2(d[f"tp{X}"].mean() - COST); o[f"tp{X}_hit"] = r2(d[f"tp{X}_hit"].mean() * 100)
    o["best_net"] = max(o["net_open"], o["net_close"], *[o[f"tp{X}_net"] for X in TPS])
    return o


ORDER = ["D-1", "D1", "D2", "D3", "D4", "D5", "Dlast", "R0", "R1", "R2"]
scopes = {"all": df, "new_rule": df[df.new_rule], "pre_new_rule": df[~df.new_rule]}
res = {"definitions": __doc__, "db_last_date": last_date, "disposal_range": [dis.start.min(), dis.start.max()],
       "n_periods": {}, "by_entry": {}}
pi = pd.DataFrame(periods_info)
for sc in ("all", "new_rule", "pre_new_rule"):
    m = pi.start >= NEW_RULE if sc == "new_rule" else (pi.start < NEW_RULE if sc == "pre_new_rule" else pi.start == pi.start)
    sub = pi[m]
    res["n_periods"][sc] = {"total": int(len(sub)), "ended": int(sub.ended.sum()), "stocks": int(sub.code.nunique()),
                            "declared_len": {str(k): int(v) for k, v in sub.declared.fillna(sub.mkt_len).value_counts().items()}}
for sc, d in scopes.items():
    res["by_entry"][sc] = {}
    for grp in ("all", "5", "10", "other"):
        dd = d if grp == "all" else d[d.len_grp == grp]
        res["by_entry"][sc][grp] = {e: stats(dd[dd.entry == e]) for e in ORDER if (dd.entry == e).any()}
clean = df[~df.next_in_disp | df.entry.isin(["D-1", "D1", "D2", "D3", "D4", "D5"])]
clean = clean[~clean.entry_in_other_disp]
res["by_entry_excl_overlap"] = {e: stats(clean[clean.entry == e]) for e in ORDER}
res["overlap_counts"] = {e: int(((df.entry == e) & (df.next_in_disp | df.entry_in_other_disp)).sum()) for e in ["Dlast", "R0", "R1", "R2"]}


def buckets(d):
    B = {}
    c = d.chg
    B["漲跌≤-6%"] = c <= -6; B["漲跌-6~-3%"] = (c > -6) & (c <= -3); B["漲跌-3~0%"] = (c > -3) & (c <= 0)
    B["漲跌0~3%"] = (c > 0) & (c < 3); B["漲跌3~7%"] = (c >= 3) & (c < 7); B["漲跌≥7%"] = c >= 7
    B["漲停"] = d.is_lu; B["跌停"] = d.is_ld
    B["長紅(實體≥3%)"] = d.body >= 3; B["長黑(實體≤-3%)"] = d.body <= -3; B["小實體(|實體|<3%)"] = d.body.abs() < 3
    B["紅K"] = d.body > 0; B["黑K"] = d.body < 0
    B["上影≥2%"] = d.upsh >= 2; B["上影<2%"] = d.upsh < 2; B["下影≥2%"] = d.losh >= 2; B["下影<2%"] = d.losh < 2
    B["量≥1.5倍5日均"] = d.vr5 >= 1.5; B["量0.7~1.5倍"] = (d.vr5 >= 0.7) & (d.vr5 < 1.5); B["量<0.7倍5日均"] = d.vr5 < 0.7
    B["處置以來≤-5%"] = d.cum <= -5; B["處置以來-5~0%"] = (d.cum > -5) & (d.cum <= 0)
    B["處置以來0~5%"] = (d.cum > 0) & (d.cum < 5); B["處置以來≥5%"] = d.cum >= 5
    B["站上MA5"] = d.ab_ma5 == True; B["跌破MA5"] = d.ab_ma5 == False
    B["站上MA20"] = d.ab_ma20 == True; B["跌破MA20"] = d.ab_ma20 == False
    B["跳空≥+2%"] = d.gap >= 2; B["開盤-2~+2%"] = (d.gap > -2) & (d.gap < 2); B["跳空≤-2%"] = d.gap <= -2
    B["MACD紅柱"] = d["hist"] > 0; B["MACD綠柱"] = d["hist"] < 0
    B["柱轉弱(hist下降)"] = d["hist"] < d["hist_prev"]; B["柱轉強(hist上升)"] = d["hist"] > d["hist_prev"]
    B["DIF>0"] = d.dif > 0; B["DIF<0"] = d.dif < 0
    return {k: v.fillna(False).astype(bool) for k, v in B.items()}


def brief(d, metric):
    if len(d) == 0:
        return {"n": 0}
    s = stats(d); return {k: s[k] for k in ("n", "open", "close", "high", "win", "red", "net_close", "net_open", "tp3_net", "tp4_net")} | {"metric": r2(d[metric].mean() - COST)}


def kshape(d, metric):
    d = d.sort_values("date").reset_index(drop=True)
    dates = np.sort(d.date.unique()); mid = dates[len(dates) // 2]
    h1 = d.date <= mid
    B = buckets(d)
    single = {k: brief(d[m], metric) | {"h1": brief(d[m & h1], metric).get("metric"), "h2": brief(d[m & ~h1], metric).get("metric"),
                                         "n_h1": int((m & h1).sum()), "n_h2": int((m & ~h1).sum())} for k, m in B.items()}
    keys = list(B); combos = []
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            m = B[keys[a]] & B[keys[b]]
            nn = int(m.sum())
            if nn < 20:
                continue
            x = d.loc[m, metric] - COST
            x1, x2 = x[h1[m]], x[~h1[m]]
            if len(x1) < 8 or len(x2) < 8:
                continue
            combos.append({"cond": f"{keys[a]} + {keys[b]}", "n": nn, "metric": r2(x.mean()), "h1": r2(x1.mean()), "h2": r2(x2.mean()),
                           "n_h1": int(len(x1)), "n_h2": int(len(x2)), "win": r2((d.loc[m, "n_close"] > 0).mean() * 100),
                           "close": r2(d.loc[m, "n_close"].mean()), "open": r2(d.loc[m, "n_open"].mean())})
    base = d[metric].mean() - COST
    good = sorted([c for c in combos if c["h1"] > 0 and c["h2"] > 0], key=lambda c: -min(c["h1"], c["h2"]))[:15]
    bad = sorted([c for c in combos if c["h1"] < base and c["h2"] < base and c["h1"] < 0 and c["h2"] < 0], key=lambda c: max(c["h1"], c["h2"]))[:10]
    return {"split_date": mid, "base": brief(d, metric), "single": single, "combos_good": good, "combos_bad": bad, "n_combos_tested": len(combos)}


cand = []
for e, s in res["by_entry"]["all"]["all"].items():
    if s["n"] >= 40:
        best_rule = max(["net_open", "net_close", "tp2_net", "tp3_net", "tp4_net"], key=lambda k: s[k])
        cand.append((s[best_rule], e, best_rule))
cand.sort(reverse=True)
res["entry_rank"] = [{"entry": e, "best_rule": k, "best_net": v} for v, e, k in cand]
colmap = {"net_open": "n_open", "net_close": "n_close", "tp2_net": "tp2", "tp3_net": "tp3", "tp4_net": "tp4"}
res["kshape"] = {}
for v, e, k in cand[:3]:
    res["kshape"][e] = {"metric": colmap[k], "all": kshape(df[df.entry == e], colmap[k]),
                        "close_metric": kshape(df[df.entry == e], "n_close") if k != "net_close" else None}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
df.to_csv(OUT.replace(".json", "_rows.csv"), index=False, encoding="utf-8-sig")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
print("periods", res["n_periods"])
print("rank", res["entry_rank"])
print("overlap", res["overlap_counts"])
for sc in ("all", "new_rule", "pre_new_rule"):
    for grp in ("all", "5", "10", "other"):
        t = res["by_entry"][sc].get(grp, {})
        if not t: continue
        print(f"== {sc} / len {grp}")
        print(pd.DataFrame(t).T[["n", "open", "close", "high", "win", "red", "net_open", "net_close", "tp2_net", "tp3_net", "tp4_net", "tp3_hit"]].to_string())
print("== excl overlap"); print(pd.DataFrame(res["by_entry_excl_overlap"]).T[["n", "open", "close", "win", "red", "net_close", "tp3_net"]].to_string())