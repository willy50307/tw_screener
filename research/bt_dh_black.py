"""研究 4：自營商避險（dh）大買超 → 隔天收黑K（收<開）的機率
只用三大法人是全市場資料的期間（2025-10-20 起）。
用法：python research/bt_dh_black.py"""
import numpy as np

from common import combo_search, conditions, load_panel, save_out, show, tbl, universe

df = load_panel()
d = universe(df, chips=True)
y = (d.n_body < 0).astype(float).values
BASE = y.mean() * 100
h1 = (d.half == 1).values
COLS = ["條件", "次數", "隔天黑K%", "lift", "前半段%", "後半段%", "隔天開盤%", "隔天收盤%"]


def row(nm, m, base=BASE):
    m = np.asarray(m, bool)
    n = int(m.sum())
    if n == 0:
        return [nm, 0, None, None, None, None, None, None]
    r = y[m].mean() * 100
    f = lambda mm: round(float(y[mm].mean() * 100), 1) if mm.sum() >= 10 else None
    return [nm, n, round(float(r), 1), round(float(r / base), 2), f(m & h1), f(m & ~h1),
            round(float(d.n_open.values[m].mean()), 2), round(float(d.n_close.values[m].mean()), 2)]


p = d.dh_pct.values
lu = d.is_lu.astype(bool).values
big = p >= 5
tables = []
# 1. dh 買賣超佔成交量 %
bk = [("賣超 ≥5%", p <= -5), ("賣超 0~5%", (p < 0) & (p > -5)), ("沒買賣（0）", p == 0), ("買超 0~1%", (p > 0) & (p < 1)),
      ("買超 1~5%", (p >= 1) & (p < 5)), ("買超 5~10%", (p >= 5) & (p < 10)), ("買超 10~20%", (p >= 10) & (p < 20)),
      ("買超 ≥20%", p >= 20), ("── 買超 ≥5%（大買）", big), ("── 大買＋今天漲停", big & lu), ("── 大買＋今天沒漲停", big & ~lu)]
tables.append(tbl(f"自營避險買賣超佔當天成交量｜{d.date.min()}~{d.date.max()}｜全部 {len(d):,} 筆，隔天黑K 基準 {BASE:.1f}%",
                  [row(*b) for b in bk], "lift = 機率 ÷ 全部基準", COLS))
# 2. 連買天數
s = d.dh_streak.values
tables.append(tbl("大買（≥5%）× 自營避險連買天數", [row("連買第 1 天", big & (s == 1)), row("連買第 2 天", big & (s == 2)),
                                                 row("連買 3 天以上", big & (s >= 3)), row("（對照）沒大買、但連買 3 天以上", ~big & (s >= 3))], cols=COLS))
# 3. 外資／投信
fi, it = d.fi.values, d.it.values
tables.append(tbl("大買（≥5%）× 外資、投信同一天的方向", [
    row("外資買超", big & (fi > 0)), row("外資賣超", big & (fi < 0)), row("外資買超≥5%量", big & (d.fi_pct.values >= 5)),
    row("外資賣超≥5%量", big & (d.fi_pct.values <= -5)), row("投信買超", big & (it > 0)), row("投信賣超", big & (it < 0)),
    row("投信沒動作", big & (it == 0)), row("外資投信同買", big & (fi > 0) & (it > 0)), row("外資投信同賣", big & (fi < 0) & (it < 0)),
    row("土洋對作（外資買、投信賣）", big & (fi > 0) & (it < 0)), row("土洋對作（外資賣、投信買）", big & (fi < 0) & (it > 0))], cols=COLS))
# 4. 隔日沖分點（只有有分點資料的股票、2026-04-23 起）
hb = d.has_br.values.astype(bool)
dtn, dtp = d.dt_net.values, d.dt_pct.values
bb = [row("（有分點資料的全部股票）", hb), row("大買、有分點資料", big & hb), row("大買＋隔日沖分點買超", big & hb & (dtn > 0)),
      row("大買＋隔日沖分點買超≥5%量", big & hb & (dtp >= 5)), row("大買＋隔日沖分點賣超／沒進", big & hb & (dtn <= 0)),
      row("（對照）沒大買＋隔日沖分點買超≥5%量", ~big & hb & (dtp >= 5))]
tables.append(tbl("大買（≥5%）× 隔日沖分點（凱基台北/站前/城中/松山、統一城中、國票安和/敦北法人、元大土城永寧、富邦建國/仁愛、群益金鼎大安、康和永和）",
                  bb, "分點資料只從 2026-04-23 開始，而且只有有抓分點的股票，樣本少，僅供參考", COLS))
# 5. MACD（研究 1 的條件）
C = conditions(d, chips=False, price=False)
tables.append(tbl("大買（≥5%）× MACD 條件", [row(k, big & m) for k, (_, m) in C.items() if (big & m).sum() >= 30], "只列 n≥30", COLS))
# 6. 大買樣本內的 2~3 個條件組合（越容易收黑K越前面）
sub = d[big].copy()
ys = y[big]
Cs = {k: (f, m[big]) for k, (f, m) in conditions(d, chips=True, broker=False).items() if not f.startswith("c_dh")}
bs = ys.mean() * 100
cb = combo_search(sub, ys, Cs, top=12, min_lift=1.15)
show("大買後 容易黑K 組合", bs, cb)
cr = combo_search(sub, 1 - ys, Cs, top=8, min_lift=1.15)   # 反過來：大買後「不容易」黑K
show("大買後 不容易黑K 組合", 100 - bs, cr)
for r in cr:   # 換回黑K機率
    r[2], r[4], r[5] = round(100 - r[2], 1), round(100 - r[4], 1), round(100 - r[5], 1)
    r[3] = round(float(r[2] / bs), 2)
tables.append(tbl(f"大買（≥5%）樣本內｜2~3 個條件組合｜比較容易收黑K（大買樣本 {len(sub):,} 筆，黑K {bs:.1f}%）",
                  cb, "lift 相對「大買樣本」的黑K率；n≥30、前後半段 lift 都 ≥1.15", COLS))
tables.append(tbl("大買（≥5%）樣本內｜比較不會收黑K 的組合", cr, "lift < 1 = 比大買樣本更不容易黑K", COLS))
for t in tables:
    show(t["title"], BASE, t["rows"])
save_out("study4", {"base": BASE, "big_base": bs, "n": len(d), "tables": tables})
