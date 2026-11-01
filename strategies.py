"""
策略條件都放這裡，邏輯照你的 TradingView「MACD(3,7,3) 單發狙擊版」。
每個條件是一個函式：輸入整段 K 線（已含指標）和設定 p，回傳每一天是否成立 (True/False)。
要新增條件：寫一個新函式，再加進下面的 STRATEGIES，App 的設定頁面就會自動出現開關。
（函式要能同時處理單一股票和全市場表格，用 df["欄位"]、.shift() 這類寫法就沒問題）
"""
import pandas as pd


def green_shrink(df, p):
    """摸底進場：昨天綠柱、今天仍綠柱、長度 <= 昨天的 (1-N%)，且 DIF 上升"""
    h, h1 = df["hist"], df["hist"].shift(1)
    return (h1 < 0) & (h < 0) & (h >= (1 - p["shrink_pct"] / 100) * h1) & (df["dif"] > df["dif"].shift(1))


def gap_cross(df, p):
    """跳空進場：昨天綠柱、昨天 DIF 上升，且今天開盤 > 昨天算出的金叉門檻價"""
    dif1 = df["dif"].shift(1)
    return (df["hist"].shift(1) < 0) & (dif1 > df["dif"].shift(2)) & (df["open"] > df["px_cross"].shift(1))


def golden_cross(df, p):
    """收盤金叉進場：DIF 上穿 MACD 訊號線（柱狀圖由綠翻紅）"""
    h, h1 = df["hist"], df["hist"].shift(1)
    return (h1 <= 0) & (h > 0)


def dif_ok(df, p):
    """高檔過熱濾網：DIF / 收盤價 <= 上限 % 才允許進場（DIF 在 0 軸下永遠允許）"""
    if not p["dif_filter"]:
        return df["dif"] == df["dif"]
    return df["dif"] / df["close"] <= p["max_dif_pct"] / 100


# 範例：之後想加條件可以照這樣寫，然後放進 STRATEGIES
# def above_ma20(df, p):
#     return df["close"] > df["ma20"]


# (代號, 顯示名稱, 函式, 圖上標記文字)
STRATEGIES = [
    ("green_shrink", "摸底", green_shrink, "摸底"),
    ("gap_cross", "跳空", gap_cross, "跳空"),
    ("golden_cross", "金叉", golden_cross, "金叉"),
]

# 所有進場訊號都要通過的濾網
FILTERS = [dif_ok]
