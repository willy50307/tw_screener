"""研究 1、2：今天收盤買，隔天會不會收「實體紅K」（收>開 且 (收-開)/昨收 ≥ 1%）
研究 1：今天沒漲停的股票；研究 2：含漲停（另外列漲停那一群）
用法：python research/bt_nextday.py"""
import numpy as np

from common import (COLS, combo_search, cond_table, conditions, load_panel, save_out, show, study_tables, tbl,
                    universe)

df = load_panel()
ALL, CH = universe(df), universe(df, chips=True)
red = lambda d: (d.n_body >= 1).astype(float).values
CF = lambda d: conditions(d, chips=False)
CC = lambda d: conditions(d, chips=True, macd=False, price=False, broker=True)


def summary(d, nm):
    y = red(d)
    return [nm, len(d), round(y.mean() * 100, 1), round(float((d.n_close > 0).mean() * 100), 1),
            round(float((d.n_open > 0).mean() * 100), 1), round(float(d.n_open.mean()), 2), round(float(d.n_close.mean()), 2)]


SUMCOLS = ["樣本", "次數", "隔天實體紅K%", "隔天收漲%", "隔天開高%", "隔天開盤%", "隔天收盤%"]
res = {}
for sid, filt in ((1, lambda d: d[~d.is_lu.astype(bool)]), (2, lambda d: d)):
    d, dc = filt(ALL), filt(CH)
    Cf = CF(d)
    base, bc, tables = study_tables(f"研究{sid}", d, red(d), dc, red(dc), CF, CC)
    s = [summary(d, "全部樣本"), summary(d[d.half == 1], "前半段"), summary(d[d.half == 2], "後半段")]
    if sid == 2:
        lu = d[d.is_lu.astype(bool)]
        s += [summary(lu, "其中：今天漲停"), summary(d[~d.is_lu.astype(bool)], "其中：今天沒漲停")]
        # 漲停那一群自己的條件表
        Cl = conditions(lu, chips=False)
        bl, rl = cond_table(lu, red(lu), Cl)
        rl = sorted(rl, key=lambda r: -r[3])
        show("漲停股", bl, rl)
        tables.append(tbl(f"今天漲停的 {len(lu):,} 筆｜隔天實體紅K 基準 {bl:.1f}%｜單一條件", rl[:15] + rl[-6:][::-1] if len(rl) > 21 else rl,
                          "前 15 個 lift 最高、後面 6 個 lift 最低"))
        luc = combo_search(lu, red(lu), Cl, top=10)
        show("漲停股組合", bl, luc)
        tables.append(tbl("今天漲停｜2~3 個條件組合｜n≥30、前後半段 lift 都 ≥1.1", luc))
    else:
        # 隔日沖：按隔天開盤賣的平均報酬（開盤出場）排序
        _, rows = cond_table(d, red(d), Cf, min_n=200)
        stable = [r for r in rows if True]
        best_open = sorted(stable, key=lambda r: -r[6])[:15]
        tables.append(tbl("隔日沖出場：隔天開盤賣平均報酬最高的條件（n≥200）", best_open, "隔天開盤% = 隔天開盤價 ÷ 今天收盤 − 1；未扣手續費、稅"))
        print("\n== 隔日沖 開盤出場 ==", *best_open, sep="\n  ")
    tables.insert(0, tbl("基準（今天收盤買）", s, cols=SUMCOLS))
    res[sid] = {"base": base, "base_chips": bc, "tables": tables}
save_out("study12", res)
