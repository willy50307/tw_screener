"""
回測引擎：執行使用者寫的策略程式碼（Python 簡化語法），模擬進出場並計算績效。

策略程式碼可以用的東西：
  資料：open, high, low, close, volume, hlcc4, date（每天一個值的序列）
  處置：disposal_day（處置第幾天，非處置期間為 0）、disposal_last（是否為處置最後一天＝出關前一天）、disposal_nth（第幾次處置）
  函式：ema(x,n) sma(x,n) rsi(x,n) highest(x,n) lowest(x,n) crossover(a,b) crossunder(a,b) ref(x,n) math
  要產生的變數：
    buy        = 進場條件（True/False 序列）            ← 必填（或用 signals / buy_limit）
    buy_limit  = 盤中限價買進價（數字序列，不買的日子放 nan）：當天最低價碰到就成交，開盤更低則以開盤價成交
    direction  = "short"   放空（預設 "long" 做多）；放空時 buy / buy_limit 代表「放空進場」
                 放空的 buy_limit：當天最高價碰到就成交（開盤更高則以開盤價成交）
    entry_at_open = True   進場用「當天開盤價」（預設用收盤價）
    day_trade  = True      當沖：進場當天收盤平倉（交易稅減半 0.15%）
    signals    = {"名稱": 條件, ...}                    ← 多種進場方式時用，圖上會標名稱
    sell       = 出場條件（True/False 序列）            ← 選填
    stop_loss  = 0.04   （收盤跌破成本 4% 出場）          ← 選填
    take_profit= 0.2    （收盤漲超過成本 20% 出場）       ← 選填
    def exit_rule(pos, i): ...  回傳出場原因字串（以收盤價賣）、(原因, 賣出價)、或 False   ← 選填
       pos.entry 進場價、pos.bars 持有天數、pos.state 可自由存資料的 dict
規則：訊號出現當天以收盤價成交（等同 TradingView process_orders_on_close=true），一次只持有一筆。
"""
import builtins
import math

import numpy as np
import pandas as pd

from notice import ceil_tick, floor_tick

LOT = 1000  # 一次買 1 張（1000 股），跟 TradingView 腳本的 default_qty_value=1000 一樣

PRESETS = {
    "MACD(3,7,3) 單發狙擊版（完整複製 Pine）": '''# 完整複製你的 TradingView「MACD(3,7,3) 單發狙擊版 (寬區間波段停利)」
fast_len, slow_len, sig_len = 3, 7, 3
shrink_pct = 0.40        # 綠柱縮腳條件
max_dif_pct = 0.015      # 高檔過熱濾網：DIF / 股價 上限（App 選股目前用 0，表示快線在 0 軸上不進場）

src = hlcc4
ema3 = ema(src, fast_len)
ema7 = ema(src, slow_len)
dif = ema3 - ema7
macd = ema(dif, sig_len)
hist = dif - macd
target = 4 * macd - 2 * ema3 + 3 * ema7          # 明日金叉門檻價

dif_ok = (dif / close) <= max_dif_pct
green_shrink = (ref(hist, 1) < 0) & (hist < 0) & (hist >= ref(hist, 1) * (1 - shrink_pct)) & (dif > ref(dif, 1))
gap_cross = (ref(hist, 1) < 0) & (ref(dif, 1) > ref(dif, 2)) & (open > ref(target, 1))
normal_cross = crossover(dif, macd)

signals = {
    "摸底": green_shrink & dif_ok,
    "跳空": gap_cross & dif_ok,
    "金叉": normal_cross & dif_ok,
}

def exit_rule(pos, i):
    """延遲停損 + 寬區間階梯停利（與 Pine 腳本相同）"""
    s = pos.state
    profit = (high[i] - pos.entry) / pos.entry
    s["max"] = max(s.get("max", 0.0), profit)
    m = s["max"]
    lock = None
    if m >= 0.25:
        lock = math.floor(m / 0.05) * 0.05 - 0.05     # 每 5% 一階，防守在下一階
    elif m >= 0.15:
        lock = 0.10
    s["below"] = s.get("below", 0) + 1 if close[i] < pos.entry * 0.96 else 0
    if s["below"] >= 2:
        return "連2日破停損"
    if lock is not None and close[i] < pos.entry * (1 + lock):
        return "收盤破停利"
    return False
''',
    "處置股：急殺-6% 隔日沖（改良版）": '''# 處置期間（不含出關前一天）盤中急殺到「前一天收盤 -6%」就買
# 隔天：漲到「隔天開盤價 +4%」就賣，沒漲到就收盤賣
# 回測範圍建議選「處置歷史裡的股票」
dip = 0.06
since = "2026-08-10"          # 只做 115/8/10 新制之後的處置

can_buy = (disposal_day >= 1) & (~disposal_last) & (date >= since)
buy_limit = (ref(close, 1) * (1 - dip)).where(can_buy)
limit_label = "急殺-6%"

def exit_rule(pos, i):
    target = open[i] * 1.04
    if high[i] >= target:
        return ("開盤+4%停利", target)
    return ("收盤賣", close[i])
''',
    "處置股：急殺-6% 抱到出關日開盤": '''# 處置期間盤中急殺到「前一天收盤 -6%」就買（每次處置只買一次）
# 抱到出關日（處置結束後第一個交易日）開盤賣
dip = 0.06
since = "2026-08-10"

can_buy = (disposal_day >= 1) & (date >= since)
buy_limit = (ref(close, 1) * (1 - dip)).where(can_buy)
limit_label = "急殺-6%"

def exit_rule(pos, i):
    if disposal_day[i] == 0 and disposal_day[i - 1] >= 1:
        return ("出關開盤賣", open[i])
    return False
''',
    "範例：均線黃金交叉": '''# 5 日線上穿 20 日線買進，跌破 20 日線賣出，停損 5%
ma5 = sma(close, 5)
ma20 = sma(close, 20)
buy = crossover(ma5, ma20)
sell = close < ma20
stop_loss = 0.05
''',
}


# ---------------- 提供給策略程式碼的函式 ----------------

def _s(x, idx):
    return x if isinstance(x, pd.Series) else pd.Series(x, index=idx)


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def sma(x, n):
    return x.rolling(n).mean()


def highest(x, n):
    return x.rolling(n).max()


def lowest(x, n):
    return x.rolling(n).min()


def ref(x, n=1):
    return x.shift(n)


def crossover(a, b):
    b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a, b):
    b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))


def rsi(x, n=14):
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


SAFE_BUILTINS = {k: getattr(builtins, k) for k in (
    "abs", "min", "max", "round", "len", "range", "float", "int", "bool", "sum", "any", "all",
    "enumerate", "zip", "dict", "list", "tuple", "str", "isinstance", "print", "ValueError")}


class Position:
    def __init__(self, entry, i, label):
        self.entry, self.start, self.label, self.bars, self.state = entry, i, label, 0, {}


def compile_strategy(code):
    return compile(code, "<策略程式碼>", "exec")


def _disposal_series(dates, periods):
    """periods：[(起, 迄, 第幾次), ...] → 每天是處置第幾天、是否最後一天、第幾次"""
    day = np.zeros(len(dates), dtype=int)
    last = np.zeros(len(dates), dtype=bool)
    nth = np.zeros(len(dates), dtype=int)
    for a, b, n in sorted(periods or []):
        idx = [i for i, t in enumerate(dates) if a <= t <= b]
        for k, i in enumerate(idx, 1):
            day[i], nth[i] = k, n
        if idx and b < dates[-1]:   # 處置已結束才確定最後一天
            last[idx[-1]] = True
    return day, last, nth


def run_one(df, compiled, cfg, periods=None):
    """df：單一股票的 date/open/high/low/close/volume。回傳 trades 清單、持有中的部位"""
    d = df.reset_index(drop=True)
    dates = d["date"].tolist()
    dday, dlast, dnth = _disposal_series(dates, periods)
    idx = d.index
    ns = {"__builtins__": SAFE_BUILTINS, "math": math, "np": np, "nan": float("nan"),
          "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"], "volume": d["volume"] / 1000,
          "hlcc4": (d["high"] + d["low"] + 2 * d["close"]) / 4, "date": d["date"],
          "disposal_day": pd.Series(dday, index=idx), "disposal_last": pd.Series(dlast, index=idx),
          "disposal_nth": pd.Series(dnth, index=idx),
          "ema": ema, "sma": sma, "highest": highest, "lowest": lowest, "ref": ref,
          "crossover": crossover, "crossunder": crossunder, "rsi": rsi}
    exec(compiled, ns)
    limit = _s(ns["buy_limit"], idx).astype(float).to_numpy() if "buy_limit" in ns else None
    if "signals" in ns:
        sig = {k: _s(v, idx).fillna(False).astype(bool).to_numpy() for k, v in ns["signals"].items()}
    elif "buy" in ns:
        sig = {"BUY": _s(ns["buy"], idx).fillna(False).astype(bool).to_numpy()}
    elif limit is not None:
        sig = {}
    else:
        raise ValueError("策略程式碼裡要有 buy = ...、signals = {...} 或 buy_limit = ...")
    sell = _s(ns["sell"], idx).fillna(False).astype(bool).to_numpy() if "sell" in ns else None
    sl, tp, rule = ns.get("stop_loss"), ns.get("take_profit"), ns.get("exit_rule")
    short = str(ns.get("direction", "long")).lower() == "short"
    at_open, day_trade = bool(ns.get("entry_at_open")), bool(ns.get("day_trade"))

    O, Hi, Lo, C = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    tax = 0.0015 if day_trade else 0.003
    fee_buy, fee_sell = (0.001425, 0.001425 + tax) if cfg.get("fees") else (0.0, 0.0)
    trades, pos = [], None
    for i in range(cfg.get("start_index", 0), len(d)):
        if pos is not None:
            pos.bars += 1
            reason, px = None, C[i]
            if rule:
                r = rule(pos, i)
                if isinstance(r, tuple):
                    reason, px = r[0], float(r[1])
                elif r:
                    reason = r
            gain = (pos.entry / C[i] - 1) if short else (C[i] / pos.entry - 1)
            if reason is None and sl is not None and gain <= -sl:
                reason = f"停損{sl:.0%}"
            if reason is None and tp is not None and gain >= tp:
                reason = f"停利{tp:.0%}"
            if reason is None and sell is not None and sell[i]:
                reason = "出場訊號"
            if reason:
                trades.append(_trade(pos, i, px, dates, reason, fee_buy, fee_sell, short))
                pos = None
            if pos is not None or limit is None:
                continue   # 收盤進場的策略：出場當天不再進場；盤中限價策略：同一天可以再買
        if limit is not None and limit[i] == limit[i]:
            if short:   # 放空：拉高到掛單價就成交
                lim = ceil_tick(float(limit[i]))
                if Hi[i] >= lim:
                    pos = Position(float(max(O[i], lim)), i, ns.get("limit_label", "限價空"))
            else:
                lim = floor_tick(float(limit[i]))      # 掛單價要符合升降單位（往下取）
                if Lo[i] <= lim:
                    pos = Position(float(min(O[i], lim)), i, ns.get("limit_label", "限價買"))
        else:
            label = next((k for k, v in sig.items() if v[i]), None)
            if label:
                pos = Position(O[i] if at_open else C[i], i, label)
        if pos is not None and pos.start == i and day_trade:   # 當沖：當天收盤平倉
            reason, px = "收盤平倉", C[i]
            if rule:
                r = rule(pos, i)
                if isinstance(r, tuple):
                    reason, px = r[0], float(r[1])
            trades.append(_trade(pos, i, px, dates, reason, fee_buy, fee_sell, short))
            pos = None
    open_trade = _trade(pos, len(d) - 1, C[-1], dates, "持有中", fee_buy, fee_sell, short) if pos else None
    return trades, open_trade


def _trade(pos, i, px, dates, reason, fb, fs, short=False):
    if short:   # 放空：先賣（付賣方手續費＋稅）後買回
        pnl = (pos.entry * (1 - fs) - px * (1 + fb)) * LOT
        ret = (pos.entry * (1 - fs)) / (px * (1 + fb)) - 1
        return {"entry_date": dates[pos.start], "entry": round(float(pos.entry), 2), "exit_date": dates[i], "exit": round(float(px), 2),
                "label": pos.label, "reason": reason, "bars": int(i - pos.start), "side": "short",
                "pnl": int(round(float(pnl))), "ret": round(float(ret * 100), 2)}
    pnl = (px * (1 - fs) - pos.entry * (1 + fb)) * LOT
    return {"entry_date": dates[pos.start], "entry": round(float(pos.entry), 2), "exit_date": dates[i], "exit": round(float(px), 2),
            "label": pos.label, "reason": reason, "bars": int(i - pos.start),
            "pnl": int(round(float(pnl))), "ret": round(float((px * (1 - fs) / (pos.entry * (1 + fb)) - 1) * 100), 2)}


def metrics(trades, capital):
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    # 依出場日期排序算權益曲線與最大回撤
    order = sorted(range(n), key=lambda k: trades[k]["exit_date"])
    eq = capital + np.cumsum(pnl[order])
    peak = np.maximum.accumulate(np.concatenate([[capital], eq]))[1:]
    dd = (peak - eq)
    k = int(dd.argmax())
    streak = best = 0
    for v in pnl[order]:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    return {
        "trades": n, "net": round(float(pnl.sum())), "ret_pct": round(float(pnl.sum()) / capital * 100, 2),
        "wins": int(len(wins)), "win_rate": round(len(wins) / n * 100, 2),
        "gross_profit": round(float(wins.sum())), "gross_loss": round(float(losses.sum())),
        "pf": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
        "avg_win": round(float(wins.mean())) if len(wins) else 0, "avg_loss": round(float(losses.mean())) if len(losses) else 0,
        "avg_ret": round(float(np.mean([t["ret"] for t in trades])), 2),
        "max_dd": round(float(dd[k])), "max_dd_pct": round(float(dd[k] / peak[k] * 100), 2),
        "max_loss_streak": best, "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1),
    }


def run(load, codes, code_str, cfg):
    """load(代號) → K 線 DataFrame（完整歷史）。cfg["since"]：只統計這天之後進場的交易（之前 150 根拿來暖身指標）"""
    compiled = compile_strategy(code_str)
    all_trades, per, opens, errors = [], [], [], []
    p0, p1 = None, None
    since = cfg.get("since")
    for c in codes:
        g = load(c)
        if g is None or len(g) < 30:
            continue
        g = g.reset_index(drop=True)
        si = 0
        if since:
            idx = g.index[g["date"] >= since]
            if not len(idx):
                continue
            si = int(idx[0])
            g = g.iloc[max(0, si - 150):].reset_index(drop=True)
            si = min(si, 150)
        p0 = min(p0 or g["date"].iloc[si], g["date"].iloc[si])
        p1 = max(p1 or g["date"].iloc[-1], g["date"].iloc[-1])
        try:
            trades, op = run_one(g, compiled, {**cfg, "start_index": si}, (cfg.get("disposals") or {}).get(c))
        except Exception as e:
            errors.append(f"{c}: {type(e).__name__}: {e}")
            if len(codes) == 1 or len(errors) > 5:
                break
            continue
        for t in trades:
            t["code"] = c
        all_trades += trades
        if op:
            op["code"] = c
            opens.append(op)
        if trades:
            m = metrics(trades, cfg["capital"])
            per.append({"code": c, "name": g["name"].iloc[-1], "trades": m["trades"], "net": m["net"],
                        "win_rate": m["win_rate"], "pf": m["pf"]})
    res = {"summary": metrics(all_trades, cfg["capital"]), "per": sorted(per, key=lambda x: -x["net"]),
           "opens": opens, "errors": errors[:6], "stocks": len(codes), "period": [p0, p1]}
    if len(codes) == 1:
        res["trades"] = all_trades
    else:
        res["trades"] = sorted(all_trades, key=lambda t: t["exit_date"], reverse=True)[:300]
    return res
