"""最後名單：黑K 先看「反彈碰均線沒站上」＋（上影≥2% / 5日漲5~10% / 量增上影）這幾個樣本外還站得住的條件，
再用 score_nextday 的分數排；紅K 直接用分數排。用法：python research/final_pick.py"""
import os
import types

import numpy as np

from common import load_panel, save_out

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "score_nextday.py"), encoding="utf-8-sig").read()
sn = types.ModuleType("sn")
sn.__file__ = os.path.abspath(__file__)
exec(compile(_src.split("df = bf.dt_streaks")[0], "score_nextday.py", "exec"), sn.__dict__)
bf = sn.bf

df = bf.dt_streaks(bf.extra_features(load_panel()))
last = df.date.max()
a = df[sn.liquid(df) & (df.date >= "2025-05-01")].copy().reset_index(drop=True)
C = bf.cond_full(a)
names = list(C)
M = np.column_stack([C[k][1] for k in names]).astype(np.float32)
ok = a.n_close.notna().values & (a.date < last).values
te = (a.date >= "2026-05-01").values
now = (a.date == last).values
yb, yr = (a.n_body < 0).values, (a.n_body > 0).values


def rate(m, y):
    return int(m.sum()), (round(float(y[m].mean() * 100), 1) if m.sum() else None)


robust = {}
for ma in (10, 20, 60):
    f = C[f"從下碰MA{ma}沒站上"][1]
    robust[f"碰MA{ma}沒站上＋5日漲5~10%"] = f & C["5日漲5~10%"][1]
    robust[f"碰MA{ma}沒站上＋上影≥2%"] = f & C["上影線≥2%"][1]
    robust[f"碰MA{ma}沒站上＋量增上影"] = f & C["量增（≥1.5倍）＋上影≥2%"][1]
rstat = {k: (rate(m & ok, yb), rate(m & ok & te, yb)) for k, m in robust.items()}
for k, v in rstat.items():
    print(k, "熱門股全期", v[0], "5月起", v[1])

out = {"last": last, "base": [round(yb[ok].mean() * 100, 1), round(yr[ok].mean() * 100, 1)], "robust": rstat}
for nm, y, use_robust in (("黑K", yb, True), ("紅K", yr, False)):
    w = sn.weights(M[ok], y[ok].astype(float))
    s = M @ w
    idx = np.where(now)[0]
    cand = []
    for i in idx:
        flags = [k for k, m in robust.items() if m[i]] if use_robust else []
        mi = np.where(M[i] > 0)[0]
        top = sorted(((names[j], w[j]) for j in mi), key=lambda x: -x[1])[:4]
        reasons = [(k, *rate(C[k][1] & ok, y)) for k, _ in top]
        best = max((rstat[f][0][1] for f in flags), default=None)
        r = a.iloc[i]
        cand.append({"code": r.code, "name": r["name"], "close": float(r.close), "chg": round(float(r.chg), 2),
                     "body": round(float(r.body), 2), "lots": int(r.vol_lots), "amt": round(float(r.close * r.vol_lots / 1e5), 1),
                     "score": round(float(s[i]), 3), "flags": flags, "best": best, "reasons": reasons})
    if use_robust:
        cand.sort(key=lambda c: (-(len(c["flags"]) > 0), -c["score"]))
    else:
        cand.sort(key=lambda c: -c["score"])
    out[nm] = cand[:15]
    # 分數前 10 名在往前滾動驗證的命中率
    print(f"\n## {nm}")
    for c in cand[:15]:
        print(c["code"], c["name"], c["close"], c["chg"], c["body"], c["lots"], c["amt"], c["score"], c["flags"], c["best"])
        for x in c["reasons"]:
            print("      ", x)
save_out("final_pick", out)
