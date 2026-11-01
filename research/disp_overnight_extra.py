"""補充：讀 disp_overnight_rows.csv，各進場日 x 關鍵K型態（漲停/跌停/站上MA5+MACD紅柱等），全期間 vs 新制。輸出 out/disp_overnight_extra.json"""
import json, os
import numpy as np, pandas as pd
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
df = pd.read_csv(os.path.join(D, "disp_overnight_rows.csv"), dtype={"code": str})
COST = 0.585
F = {"全部": lambda d: d.chg == d.chg,
     "收漲停": lambda d: d.is_lu,
     "漲≥7%未漲停": lambda d: (d.chg >= 7) & ~d.is_lu,
     "漲3~7%": lambda d: (d.chg >= 3) & (d.chg < 7),
     "收跌停": lambda d: d.is_ld,
     "跌≤-6%未跌停": lambda d: (d.chg <= -6) & ~d.is_ld,
     "站上MA5+MACD紅柱": lambda d: (d.ab_ma5 == True) & (d["hist"] > 0),
     "跌破MA5+MACD綠柱": lambda d: (d.ab_ma5 == False) & (d["hist"] < 0),
     "收漲停+站上MA20": lambda d: d.is_lu & (d.ab_ma20 == True),
     "非漲停": lambda d: ~d.is_lu}
ORDER = ["D-1", "D1", "D2", "D3", "D4", "D5", "Dlast", "R0", "R1", "R2"]
r2 = lambda x: None if x != x else round(float(x), 2)
def st(d):
    if not len(d): return {"n": 0}
    return {"n": len(d), "open": r2(d.n_open.mean()), "close": r2(d.n_close.mean()), "win": r2((d.n_close > 0).mean() * 100),
            "red": r2(d.n_red.mean() * 100), "net_open": r2(d.n_open.mean() - COST), "net_close": r2(d.n_close.mean() - COST),
            "tp3_net": r2(d.tp3.mean() - COST), "tp4_net": r2(d.tp4.mean() - COST)}
out = {}
for sc, d0 in {"all": df, "new_rule": df[df.new_rule], "pre_new_rule": df[~df.new_rule]}.items():
    out[sc] = {}
    for fn, f in F.items():
        d1 = d0[f(d0).fillna(False).astype(bool)]
        out[sc][fn] = {e: st(d1[d1.entry == e]) for e in ORDER}
# 「處置期間任一天(D1~D5)收漲停」去重（同一次處置只算第一次）
d = df[df.entry.isin(["D1", "D2", "D3", "D4", "D5"]) & df.is_lu].sort_values("date").drop_duplicates(["code", "start"])
out["first_lu_in_D1_D5"] = {"all": st(d), "new_rule": st(d[d.new_rule]), "pre_new_rule": st(d[~d.new_rule])}
with open(os.path.join(D, "disp_overnight_extra.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
pd.set_option("display.width", 250)
for sc in ("all", "new_rule"):
    for fn in F:
        t = pd.DataFrame(out[sc][fn]).T
        print(f"== {sc} | {fn}"); print(t.to_string())
print(out["first_lu_in_D1_D5"])