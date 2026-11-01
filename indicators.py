"""
指標計算。所有函式同時支援：
  - 單一股票：DataFrame（一欄一個欄位）
  - 全市場：dict，每個欄位是一張「列=第幾天, 欄=股票代號」的表，一次算完全部股票（快很多）
"""
import numpy as np
import pandas as pd


def ema(s, n: int):
    return s.ewm(span=n, adjust=False).mean()


def indicator_cols(d, p: dict) -> dict:
    c = d["close"]
    src = (d["high"] + d["low"] + 2 * c) / 4 if p["price_source"] == "DI" else c   # DI = XQ 的 hlcc4
    x = {"ema_fast": ema(src, p["macd_fast"]), "ema_slow": ema(src, p["macd_slow"])}
    x["dif"] = x["ema_fast"] - x["ema_slow"]
    x["dea"] = ema(x["dif"], p["macd_signal"])
    x["hist"] = x["dif"] - x["dea"]             # >0 紅柱, <0 綠柱
    for n in (5, 10, 20, 60, 120):
        x[f"ma{n}"] = c.rolling(n).mean()
    std = c.rolling(20).std()
    x["bb_up"] = x["ma20"] + 2 * std
    x["bb_dn"] = x["ma20"] - 2 * std
    x.update(key_prices(x, p))
    return x


def key_prices(x, p: dict) -> dict:
    """
    每一天算出「隔天」的關鍵價（EMA 對價格是線性的，所以可以直接解出來）：
      隔天 DIF(X)  = k*X + const,  k = a_f - a_s,  const = (1-a_f)*EMAf - (1-a_s)*EMAs
      隔天 hist(X) = (1-a_sig) * (DIF(X) - DEA)
    X 是隔天的 (高+低+2*收)/4（price_source="DI" 時），跟 TradingView 策略一樣。
      px_cross  隔天 > 此價 → 黃金交叉（= 你腳本的 4*macdLine - 2*ema3 + 3*ema7）
      px_difup  隔天 > 此價 → DIF 上升
      px_shrink 隔天 >= 此價 → 綠柱縮短 N%
      px_max    隔天 <= 此價 → 才不會被「DIF 過熱濾網」擋掉（以收盤價近似）
    """
    af, as_, ag = 2 / (p["macd_fast"] + 1), 2 / (p["macd_slow"] + 1), 2 / (p["macd_signal"] + 1)
    k = af - as_
    const = (1 - af) * x["ema_fast"] - (1 - as_) * x["ema_slow"]
    m = p["max_dif_pct"] / 100
    return {
        "px_cross": (x["dea"] - const) / k,
        "px_difup": (x["dif"] - const) / k,
        "px_shrink": ((1 - p["shrink_pct"] / 100) * x["hist"] / (1 - ag) + x["dea"] - const) / k,
        "px_max": -const / (k - m) if k > m else const * np.nan,
    }


def add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    return pd.concat([df, pd.DataFrame(indicator_cols(df, p))], axis=1)


def predict_next(last, prev_dif, p: dict) -> dict:
    """
    last：最後一天的指標（單一股票的一列，或全市場每欄一檔的 Series）；prev_dif：前一天的 DIF
    回傳明天的觸發價（不適用時為 NaN）：
      shrink 明天 >= 此價 → 摸底進場（綠柱縮短 N% 且 DIF 上升）
      cross  明天 >  此價 → 收盤金叉進場
      gap    明天開盤 > 此價 → 跳空進場（今天綠柱且 DIF 上升才有）
      max    明天 <= 此價 才不會被過熱濾網擋掉
    """
    h = last["hist"]
    return {
        "shrink": np.where(h < 0, np.maximum(last["px_shrink"], last["px_difup"]), np.nan),
        "cross": np.where(h <= 0, last["px_cross"], np.nan),
        "gap": np.where((h < 0) & (last["dif"] > prev_dif), last["px_cross"], np.nan),
        "max": last["px_max"] if p["dif_filter"] else last["px_max"] * np.nan,
    }
