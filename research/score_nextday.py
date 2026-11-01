"""研究：熱門股明天黑K／紅K 打分數（每個條件的 lift 取 log 加總，樣本少的打折），用「往前滾動」驗證：
每個月只用之前的資料算權重，再看那個月每天分數前 10 名的命中率。最後用全部資料替最新一天打分。
用法：python research/score_nextday.py"""
import os
import types

import numpy as np
import pandas as pd

from common import load_panel, save_out

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt_black.py"), encoding="utf-8-sig").read()
bf = types.ModuleType("bf")
exec(compile(_src.split("# ---------- 主程式")[0], "bt_black.py", "exec"), bf.__dict__)

LIQ_LOTS, LIQ_AMT, TOP, SHRINK = 3000, 3e8, 10, 300


def liquid(df):
    return (df.close >= 10) & (df.vol_lots >= LIQ_LOTS) & (df.close * df.vol_lots * 1000 >= LIQ_AMT)


def logit(p):
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def weights(M, y):
    n = M.sum(0)
    p = (M * y[:, None]).sum(0) / np.maximum(n, 1)
    w = (logit(p) - logit(y.mean())) * n / (n + SHRINK)
    w[n < 30] = 0
    return w


df = bf.dt_streaks(bf.extra_features(load_panel()))
last = df.date.max()
a = df[liquid(df) & (df.date >= "2025-05-01")].copy().reset_index(drop=True)
C = bf.cond_full(a)
names = list(C)
M = np.column_stack([C[k][1] for k in names]).astype(np.float32)
ok = a.n_close.notna().values & (a.date < last).values
Y = {"黑K": (a.n_body < 0).values.astype(float), "紅K": (a.n_body > 0).values.astype(float)}
month = a.date.str[:7].values

out = {"last": last, "valid": {}, "picks": {}}
for nm, y in Y.items():
    rec = []
    for mo in sorted(set(month[ok])):
        if mo < "2026-01":
            continue
        tr, te = ok & (month < mo), ok & (month == mo)
        w = weights(M[tr], y[tr])
        s = M[te] @ w
        t = a[te].assign(s=s, y=y[te])
        for dte, g in t.groupby("date"):
            top = g.nlargest(TOP, "s")
            bot = g.nsmallest(TOP, "s")
            rec.append([mo, dte, len(g), g.y.mean(), top.y.mean(), bot.y.mean(),
                        g[g.s >= g.s.quantile(0.9)].y.mean()])
    r = pd.DataFrame(rec, columns=["mo", "date", "n", "base", "top", "bot", "dec"])
    bym = r.groupby("mo")[["base", "top", "bot", "dec"]].mean().round(3)
    print(f"\n== {nm} 往前滾動驗證（每天熱門股約 {r.n.mean():.0f} 檔）")
    print(bym)
    allm = r[["base", "top", "bot", "dec"]].mean()
    beat = (r.top > r.base).mean()
    print("全期", allm.round(3).to_dict(), "前10名勝過當天基準的天數比例", round(beat, 3), "天數", len(r))
    out["valid"][nm] = {"by_month": bym.reset_index().values.tolist(), "all": allm.round(4).to_dict(), "beat": beat, "days": len(r)}

    # 最新一天
    w = weights(M[ok], y[ok])
    te = (a.date == last).values
    s = M[te] @ w
    t = a[te].assign(s=s)
    rows = []
    for i in np.argsort(-s)[:25]:
        row = t.iloc[i]
        mi = np.where(M[te][i] > 0)[0]
        contrib = sorted(((names[j], w[j]) for j in mi), key=lambda x: -x[1])
        reasons = []
        for k, wj in contrib[:5]:
            msk = C[k][1] & ok
            reasons.append((k, int(msk.sum()), round(float(y[msk].mean() * 100), 1)))
        # 同時符合前三大加分條件的歷史命中率
        msk = ok.copy()
        for k, _ in contrib[:3]:
            msk &= C[k][1]
        combo = (int(msk.sum()), round(float(y[msk].mean() * 100), 1) if msk.sum() else None)
        rows.append([row.code, row["name"], float(row.close), round(float(row.chg), 2), int(row.vol_lots),
                     round(float(row.close * row.vol_lots / 1e5), 1), round(float(s[i]), 3), reasons, combo])
    out["picks"][nm] = rows
    print(f"\n## {nm} {last} 分數前 25（基準 {y[ok].mean() * 100:.1f}%）")
    for rr in rows:
        print("  ", rr[:7], "前三條件同時符合:", rr[8])
        for x in rr[7]:
            print("        ", x)
save_out("score_nextday", out)
