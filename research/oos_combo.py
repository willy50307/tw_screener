"""樣本外檢查：只用 2026-04 以前（熱門股）找黑K／紅K 條件組合，再看 2026-05 以後還準不準。
用法：python research/oos_combo.py"""
import os
import types

import numpy as np

from common import combo_search, load_panel, save_out

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt_black.py"), encoding="utf-8-sig").read()
bf = types.ModuleType("bf")
exec(compile(_src.split("# ---------- 主程式")[0], "bt_black.py", "exec"), bf.__dict__)

df = bf.dt_streaks(bf.extra_features(load_panel()))
last = df.date.max()
liq = (df.close >= 10) & (df.vol_lots >= 3000) & (df.close * df.vol_lots * 1000 >= 3e8)
a = df[liq & (df.date >= "2025-05-01") & (df.date < last) & df.n_close.notna()].copy()
for lab, uni in (("熱門股", a), ("全部(量≥500張)", df[(df.close >= 10) & (df.vol_lots >= 500) & (df.date >= "2025-05-01") & (df.date < last) & df.n_close.notna()].copy())):
    tr = uni[uni.date < "2026-05-01"].copy()
    te = uni[uni.date >= "2026-05-01"].copy()
    ds = np.sort(tr.date.unique())
    tr["half"] = np.where(tr.date <= ds[len(ds) // 2], 1, 2)
    Ctr, Cte = bf.cond_full(tr), bf.cond_full(te)
    res = {}
    for nm, f in (("黑K", lambda x: x.n_body < 0), ("紅K", lambda x: x.n_body > 0)):
        ytr, yte = f(tr).values.astype(float), f(te).values.astype(float)
        cb = combo_search(tr, ytr, Ctr, top=30, min_lift=1.12, min_n=40)
        rows = []
        for r in cb:
            m = np.ones(len(te), bool)
            for k in r[0].split(" ＋ "):
                m &= Cte[k][1]
            rows.append([r[0], r[1], r[2], int(m.sum()), round(float(yte[m].mean() * 100), 1) if m.sum() else None])
        n_te = sum(x[3] for x in rows)
        hit = sum((x[4] or 0) * x[3] for x in rows) / max(n_te, 1)
        print(f"\n== {lab} {nm}  訓練基準 {ytr.mean()*100:.1f}%  測試基準 {yte.mean()*100:.1f}%  組合在測試期加權命中 {hit:.1f}%（{n_te} 次）")
        for x in rows:
            print("  ", x)
        res[nm] = rows
save_out("oos_combo", res)
