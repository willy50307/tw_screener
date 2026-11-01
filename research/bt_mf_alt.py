"""研究：主力買賣超（買超前15 − 賣超前15）「一天買一天賣」交替的節奏，是真的、而且能預測隔天嗎？
資料：research/out/mf/<code>.csv（mf_fetch.py 抓的，約 6 年）＋ stocks.db 股價（唯讀）。
用法：python research/bt_mf_alt.py"""
import glob
import os
import sqlite3

import numpy as np
import pandas as pd

from common import save_out

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.dirname(HERE), "data", "stocks.db")

frames = []
for p in glob.glob(os.path.join(HERE, "out", "mf", "*.csv")):
    x = pd.read_csv(p, dtype={"date": str})
    x["code"] = os.path.basename(p)[:-4]
    frames.append(x)
mf = pd.concat(frames)
codes = sorted(mf.code.unique())
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = f"SELECT code,date,name,open,high,low,close,volume FROM prices WHERE date>='{mf.date.min()}' AND code IN ({','.join('?' * len(codes))})"
px = pd.read_sql(q, con, params=codes)
con.close()
d = px.merge(mf, on=["code", "date"], how="left").sort_values(["code", "date"]).reset_index(drop=True)
g = d.groupby("code")
d["lots"] = d.volume / 1000
d["mf_pct"] = d.mf / d.lots * 100
d["s"] = np.sign(d.mf)
d["red"] = (d.close > d.open).astype(float)
d["up"] = (d.close > g.close.shift(1)).astype(float)
for k in ("s", "red", "up", "open", "close"):
    d[f"n_{k}"] = g[k].shift(-1)
d["n_red"] = (d.n_close > d.n_open).astype(float).where(d.n_close.notna())
d["n_up"] = (d.n_close > d.close).astype(float).where(d.n_close.notna())
d["n_ret"] = (d.n_close / d.close - 1) * 100
d["n_body"] = (d.n_close - d.n_open) / d.close * 100
d["flip"] = ((d.s * g.s.shift(1)) < 0).astype(float).where(g.s.shift(1).notna() & d.s.notna() & (d.s != 0))
d["n_flip"] = g.flip.shift(-1)
# 連續交替天數：到今天為止，每天都跟前一天相反，連了幾次
f = d.flip.fillna(0).astype(int)
cs = f.groupby(d.code).cumsum()
d["alt"] = cs - cs.where(f == 0).groupby(d.code).ffill().fillna(0)
d["flip20"] = g.flip.transform(lambda s: s.rolling(20, min_periods=15).mean())     # 近 20 天翻轉比例（含今天）
d["flip60"] = g.flip.transform(lambda s: s.rolling(60, min_periods=45).mean())
d["amt"] = d.close * d.volume
ok = d.n_close.notna() & d.mf.notna() & (d.mf != 0)
D = d[ok & (d.close >= 10) & (d.lots >= 1000)].copy()
print("筆數", len(D), "股票", D.code.nunique(), D.date.min(), D.date.max())

R = {}


def rates(m, lab):
    x = D[m]
    return [lab, len(x), round(x.n_flip.mean() * 100, 1), round(x.n_red.mean() * 100, 1), round(x.n_up.mean() * 100, 1),
            round(x.n_ret.mean(), 2), round(x.n_body.mean(), 2)]


COLS = ["條件", "次數", "隔天主力反向%", "隔天紅K%", "隔天收漲%", "隔天報酬%", "隔天實體%"]
# 1. 同一天：主力買超和紅K 有多相關？
same = [["主力買超的日子", int((D.s > 0).sum()), round(D[D.s > 0].red.mean() * 100, 1), round(D[D.s > 0].up.mean() * 100, 1)],
        ["主力賣超的日子", int((D.s < 0).sum()), round(D[D.s < 0].red.mean() * 100, 1), round(D[D.s < 0].up.mean() * 100, 1)]]
print("\n同日", same)
R["same"] = same
# 2. 基準與交替長度
rows = [rates(np.ones(len(D), bool), "全部")]
for side, sm in (("今天主力賣超", D.s < 0), ("今天主力買超", D.s > 0)):
    rows.append(rates(sm, side))
    for a in (1, 2, 3, 4, 5, 6):
        rows.append(rates(sm & (D.alt == a) if a < 6 else sm & (D.alt >= 6), f"　{side}＋已連續交替 {a}{'+' if a == 6 else ''} 次"))
for r in rows:
    print(r)
R["alt"] = rows
# 3. 近期節奏：近 20 天翻轉比例
rows2 = []
for side, sm in (("今天主力賣超", D.s < 0), ("今天主力買超", D.s > 0)):
    for lo, hi in ((0, .3), (.3, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
        rows2.append(rates(sm & (D.flip20 >= lo) & (D.flip20 < hi), f"{side}｜近20天翻轉 {int(lo*100)}~{min(int(hi*100),100)}%"))
for r in rows2:
    print(r)
R["flip20"] = rows2
# 4. 交替＋大量（主力買賣超佔成交量 ≥ 10%）
rows3 = []
big = D.mf_pct.abs() >= 10
for side, sm in (("今天主力賣超", D.s < 0), ("今天主力買超", D.s > 0)):
    rows3.append(rates(sm & big, f"{side}≥10%量"))
    rows3.append(rates(sm & big & (D.alt >= 4), f"{side}≥10%量＋已交替≥4次"))
    rows3.append(rates(sm & big & (D.flip20 >= .7), f"{side}≥10%量＋近20天翻轉≥70%"))
    rows3.append(rates(sm & (D.alt >= 4) & (D.flip20 >= .7), f"{side}＋已交替≥4次＋近20天翻轉≥70%"))
for r in rows3:
    print(r)
R["big"] = rows3
# 5. 時間穩定度：依年份
rows4 = []
D["yr"] = D.date.str[:4]
for y_, x in D.groupby("yr"):
    m = (x.s < 0) & (x.alt >= 4)
    m2 = (x.s > 0) & (x.alt >= 4)
    rows4.append([y_, int(m.sum()), round(x[m].n_flip.mean() * 100, 1), round(x[m].n_red.mean() * 100, 1), round(x[m].n_up.mean() * 100, 1),
                  int(m2.sum()), round(x[m2].n_flip.mean() * 100, 1), round(x[m2].n_red.mean() * 100, 1), round(x.n_flip.mean() * 100, 1), round(x.n_red.mean() * 100, 1)])
print("\n年份", rows4)
R["year"] = rows4
# 6. 個股：哪些股票交替最明顯（近 60 天翻轉比例最高），以及「最後一天」的狀態
lastd = d.date.max()
t = d[(d.date == lastd) & d.mf.notna()].copy()
t = t[(t.close >= 10) & (t.lots >= 1000)]
t["mf_pct"] = t.mf_pct.round(1)
scr = t.sort_values(["alt", "flip20"], ascending=False)[["code", "name", "close", "mf", "mf_pct", "alt", "flip20", "flip60", "red"]].head(40)
print("\n", lastd, "交替最明顯\n", scr.round(2).to_string())
R["screen"] = scr.round(3).values.tolist()
R["last"] = lastd
# 7. 每檔自己的歷史：交替 ≥4 次後，隔天真的再反向的比例（看是不是某些股票特別準）
per = D[D.alt >= 4].groupby("code").agg(n=("n_flip", "size"), flip=("n_flip", "mean"), red=("n_red", "mean"))
per = per[per.n >= 15].sort_values("flip", ascending=False)
print("\n個股 交替≥4次後隔天再反向\n", per.head(20).round(3).to_string(), "\n...\n", per.tail(5).round(3).to_string())
R["per_stock"] = per.reset_index().round(3).values.tolist()
# 台玻
tb = d[d.code == "1802"].tail(25)[["date", "close", "open", "mf", "mf_pct", "alt", "flip20", "red"]]
print("\n台玻\n", tb.round(2).to_string())
T = D[D.code == "1802"]
R["1802"] = {"rows": tb.round(3).values.tolist(),
             "all": rates(D.code == "1802", "台玻全部"),
             "sell": rates((D.code == "1802") & (D.s < 0), "台玻 主力賣超隔天"),
             "sell_alt4": rates((D.code == "1802") & (D.s < 0) & (D.alt >= 4), "台玻 主力賣超＋已交替≥4次"),
             "buy_alt4": rates((D.code == "1802") & (D.s > 0) & (D.alt >= 4), "台玻 主力買超＋已交替≥4次"),
             "alt4": rates((D.code == "1802") & (D.alt >= 4), "台玻 已交替≥4次"),
             "same_buy_red": round(T[T.s > 0].red.mean() * 100, 1), "same_sell_red": round(T[T.s < 0].red.mean() * 100, 1)}
for k, v in R["1802"].items():
    if k != "rows":
        print(k, v)
R["cols"] = COLS
save_out("mf_alt", R)
