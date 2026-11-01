"""研究 3：今天出現什麼條件，之後會漲停？
目標：隔天漲停、3 天內（t+1~t+3）有漲停、5 天內有漲停、「近期第一根漲停」（前 20 天都沒漲停、今天也沒漲停 → 隔天漲停）
用法：python research/bt_limitup.py"""
from common import conditions, load_panel, save_out, study_tables, tbl, universe

df = load_panel()
ALL, CH = universe(df), universe(df, chips=True)
CF = lambda d: conditions(d, chips=False)
CC = lambda d: conditions(d, chips=True, macd=False, price=False, broker=True)
first = lambda d: d[(d.lu_prev20 == 0) & ~d.is_lu.astype(bool)]
TARGETS = [("lu1", "隔天漲停", "n_lu", lambda d: d),
           ("lu3", "3 天內有漲停（t+1~t+3）", "n_lu3", lambda d: d[d.n_lu3.notna()]),
           ("lu5", "5 天內有漲停（t+1~t+5）", "n_lu5", lambda d: d[d.n_lu5.notna()]),
           ("first", "近期第一根漲停（前 20 天＋今天都沒漲停 → 隔天漲停）", "n_lu", first)]
res, summ = {}, []
for key, nm, col, f in TARGETS:
    d, dc = f(ALL), f(CH)
    y, yc = d[col].values, dc[col].values
    base, bc, tables = study_tables(nm, d, y, dc, yc, CF, CC, top_single=15, bottom=5, top_combo=10, min_lift=1.3)
    summ.append([nm, len(d), round(float(y.mean() * 100), 2), round(float(yc.mean() * 100), 2)])
    res[key] = {"name": nm, "base": base, "base_chips": bc, "tables": tables}
res["summary"] = tbl("基準機率", summ, cols=["目標", "樣本數", "全期間機率%", "法人期間機率%"])
save_out("study3", res)
