"""研究：熱門股（量大、成交值大）明天容易黑K／紅K 的名單。
黑K = 隔天收 < 隔天開；紅K = 隔天收 > 隔天開。條件組合在熱門股範圍裡重新找（前後半段都要穩），
再看最新一天（資料最後一天）哪些股票符合。用法：python research/pick_nextday.py"""
import numpy as np
import pandas as pd

import os
import types

from common import combo_search, load_panel, save_out

# 借用 bt_black.py 的特徵與條件（只執行到「主程式」之前）
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt_black.py"), encoding="utf-8-sig").read()
bf = types.ModuleType("bf")
exec(compile(_src.split("# ---------- 主程式")[0], "bt_black.py", "exec"), bf.__dict__)
bf.panel = lambda: bf.dt_streaks(bf.extra_features(load_panel()))

LIQ_LOTS, LIQ_AMT = 3000, 3e8          # 熱門：當天量 ≥3000 張、成交值 ≥3 億


def liquid(df):
    amt = df.close * df.vol_lots * 1000
    return (df.close >= 10) & (df.vol_lots >= LIQ_LOTS) & (amt >= LIQ_AMT)


df = bf.panel()
last = df.date.max()
m = liquid(df) & (df.date >= "2025-05-01") & (df.date < last) & df.n_close.notna()
d = df[m].copy()
dates = np.sort(d.date.unique())
d["half"] = np.where(d.date <= dates[len(dates) // 2], 1, 2)
C = bf.cond_full(d)
yb = (d.n_body < 0).astype(float).values
yr = (d.n_body > 0).astype(float).values
print(len(d), "黑K基準", yb.mean(), "紅K基準", yr.mean())

res = {}
for nm, y in (("黑K", yb), ("紅K", yr)):
    cb = combo_search(d, y, C, top=80, min_lift=1.12, min_n=40)
    res[nm] = cb
    print("\n==", nm, "基準", round(y.mean() * 100, 1))
    for r in cb[:25]:
        print("  ", r)

# 最新一天
t = df[(df.date == last) & liquid(df)].copy()
Ct = bf.cond_full(t)
picks = {}
for nm, cb in res.items():
    rows = []
    for i, code in enumerate(t.code.values):
        hit = [r for r in cb if all(Ct[k][1][i] for k in r[0].split(" ＋ "))]
        if hit:
            hit.sort(key=lambda r: -r[2])
            rows.append([code, t.name.values[i], float(t.close.values[i]), round(float(t.chg.values[i]), 2),
                         int(t.vol_lots.values[i]), round(float(t.close.values[i] * t.vol_lots.values[i] / 1e5), 1),
                         hit[0][2], len(hit), hit[0][1], [(h[0], h[1], h[2], h[4], h[5]) for h in hit[:3]]])
    rows.sort(key=lambda r: (-r[6], -r[7], -r[5]))
    picks[nm] = rows
    print("\n##", nm, "名單", last, len(rows))
    for r in rows[:25]:
        print("  ", r[:9])
        for h in r[9]:
            print("        ", h)
save_out("pick_nextday", {"last": last, "base": [yb.mean(), yr.mean(), len(d)], "combos": res, "picks": picks})
