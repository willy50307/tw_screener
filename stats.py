"""個股統計數據（仿權證小哥「盤中當沖神器」的前半段欄位），K 線圖和「數據篩選」頁共用。

欄位定義（權證小哥沒公布參數，以下是拿他 2026-10-27 畫面上 14 檔的數字反推出來的）：
  連漲     連續上漲天數（收盤 > 前一天收盤）；負數＝連跌幾天
  連量     成交量連續比前一天大的天數；負數＝連續量縮幾天
  昨漲幅   前一個交易日的漲跌幅 %
  位階     (RSI(6) − 50) × 0.4，正＝強勢、負＝弱勢（最接近，平均差約 3；10 日乖離另外有一欄）
  10日／月線／季線乖離 收盤價距離 MA10／MA20／MA60 幾 %
  均量比   今天成交量 ÷ 前 20 日平均量（不含今天）　← 14 檔都吻合
  月線斜率 月線（MA20）今天比昨天漲跌幾 %（> 0 月線上彎）　← 14 檔都吻合
  週轉率   成交股數 ÷ 發行股數 %
  帶寬     布林通道(20, 2) (上軌 − 下軌) ÷ 下軌 %（越小越收斂）　← 14 檔都吻合
  外資連買／投信連買  連續買超天數；負數＝連續賣超幾天（外資含外資自營商；小哥盤中顯示的是到昨天為止）
  KD       K(9)、D(9)，RSV 平滑 1/3
  融資增減、融券餘額、券資比  融資券（每晚 10 點後才有當天資料）
"""
import time

import numpy as np
import pandas as pd

from data import connect

# [key, 名稱, 單位, 小數位, 說明]：前端的欄位、篩選下拉選單都照這個順序
STATS = [
    ["close", "成交", "", 2, "收盤價"],
    ["chg", "漲幅", "%", 2, "今天漲跌幅"],
    ["up_streak", "連漲", "天", 0, "連續上漲天數，負數＝連跌"],
    ["vol_streak", "連量", "天", 0, "成交量連續比前一天大的天數，負數＝連續量縮"],
    ["prev_chg", "昨漲幅", "%", 2, "前一個交易日漲跌幅"],
    ["pos", "位階", "", 0, "(RSI6 − 50) × 0.4，正＝強勢、負＝弱勢"],
    ["bias10", "10日乖離", "%", 1, "收盤距離 10 日均線 %"],
    ["bias20", "月線乖離", "%", 1, "收盤距離月線(MA20) %"],
    ["bias60", "季線乖離", "%", 1, "收盤距離季線(MA60) %"],
    ["vr", "均量比", "倍", 1, "今天量 ÷ 前 20 日均量"],
    ["slope20", "月線斜率", "%", 2, "月線(MA20) 今天比昨天漲跌 %，>0 上彎"],
    ["turnover", "週轉率", "%", 2, "成交股數 ÷ 發行股數"],
    ["bw", "帶寬", "%", 0, "布林(20,2) (上軌 − 下軌) ÷ 下軌，越小越收斂"],
    ["lots", "成交量", "張", 0, "成交張數"],
    ["amount", "成交值", "億", 2, "收盤 × 成交股數"],
    ["fi_streak", "外資連買", "天", 0, "外資連續買超天數，負數＝連賣"],
    ["fi", "外資買賣超", "張", 0, "外資（含外資自營商）當日買賣超"],
    ["it_streak", "投信連買", "天", 0, "投信連續買超天數，負數＝連賣"],
    ["it", "投信買賣超", "張", 0, "投信當日買賣超"],
    ["k9", "K(9)", "", 1, "KD 的 K 值"],
    ["d9", "D(9)", "", 1, "KD 的 D 值"],
    ["m_chg", "融資增減", "張", 0, "融資餘額比前一天增減"],
    ["s_bal", "融券餘額", "張", 0, "融券餘額"],
    ["ss_ratio", "券資比", "%", 1, "融券餘額 ÷ 融資餘額"],
]
KEYS = [s[0] for s in STATS]


def streak(pos, neg):
    """pos / neg：布林陣列（列＝第幾天，可以是一維或二維）→ 連續天數，pos 連續記正、neg 連續記負"""
    P, N = np.asarray(pos, dtype=bool), np.asarray(neg, dtype=bool)
    one = P.ndim == 1
    if one:
        P, N = P[:, None], N[:, None]
    out = np.zeros(P.shape)
    prev = np.zeros(P.shape[1])
    for i in range(len(P)):
        prev = np.where(P[i], np.maximum(prev, 0) + 1, np.where(N[i], np.minimum(prev, 0) - 1, 0))
        out[i] = prev
    return out[:, 0] if one else out


def price_stats(d, shares):
    """d：{open, high, low, close, volume}，單一股票是 Series、全市場是「列＝天、欄＝代號」的表；shares：發行股數（數字或 Series）"""
    c, v, h, l = d["close"], d["volume"], d["high"], d["low"]
    pc = c.shift(1)
    chg = (c / pc - 1) * 100
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    std = c.rolling(20).std(ddof=0)
    lo9, hi9 = l.rolling(9).min(), h.rolling(9).max()
    rsv = ((c - lo9) / (hi9 - lo9).replace(0, np.nan) * 100)
    k9 = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    wrap = (lambda a: pd.Series(a, index=c.index)) if isinstance(c, pd.Series) else (lambda a: pd.DataFrame(a, index=c.index, columns=c.columns))
    pv = v.shift(1)
    dc = c.diff()
    gain, loss = dc.clip(lower=0).ewm(alpha=1 / 6, adjust=False).mean(), (-dc.clip(upper=0)).ewm(alpha=1 / 6, adjust=False).mean()
    rsi6 = 100 * gain / (gain + loss).replace(0, np.nan)
    return {
        "close": c, "chg": chg, "prev_chg": chg.shift(1),
        "up_streak": wrap(streak((c > pc).to_numpy(), (c < pc).to_numpy())),
        "vol_streak": wrap(streak((v > pv).to_numpy(), (v < pv).to_numpy())),
        "pos": (rsi6 - 50) * 0.4, "bias10": (c / c.rolling(10).mean() - 1) * 100, "bias20": (c / ma20 - 1) * 100, "bias60": (c / ma60 - 1) * 100,
        "vr": v / v.shift(1).rolling(20).mean().replace(0, np.nan),
        "slope20": (ma20 / ma20.shift(1) - 1) * 100,
        "turnover": v / (shares.replace(0, np.nan) if isinstance(shares, pd.Series) else (shares or np.nan)) * 100,
        "bw": 4 * std / (ma20 - 2 * std).replace(0, np.nan) * 100,
        "lots": v / 1000, "amount": c * v / 1e8,
        "k9": k9, "d9": k9.ewm(alpha=1 / 3, adjust=False).mean(),
    }


def _chip_wide(since, codes=None):
    """法人、融資券：回傳 {欄位: 列＝日期、欄＝代號 的表}（法人沒資料的日子當 0）"""
    con = connect()
    try:
        q, args = " WHERE date >= ?", [since]
        if codes:
            q += f" AND code IN ({','.join('?' * len(codes))})"
            args += list(codes)
        inst = pd.read_sql("SELECT date, code, fi + COALESCE(fid, 0) AS fi, it FROM inst" + q, con, params=args)
        mg = pd.read_sql("SELECT date, code, m_prev, m_bal, s_bal FROM margin" + q, con, params=args)
        idates = [r[0] for r in con.execute("SELECT DISTINCT date FROM inst WHERE date >= ? ORDER BY date", (since,))]
    except Exception:
        return {}
    finally:
        con.close()
    out = {}
    if len(inst):
        for k in ("fi", "it"):
            w = inst.pivot(index="date", columns="code", values=k).reindex(idates).fillna(0)
            out[k] = w
            out[k + "_streak"] = pd.DataFrame(streak((w > 0).to_numpy(), (w < 0).to_numpy()), index=w.index, columns=w.columns)
    if len(mg):
        m_bal = mg.pivot(index="date", columns="code", values="m_bal")
        out["m_chg"] = m_bal - mg.pivot(index="date", columns="code", values="m_prev")
        out["s_bal"] = mg.pivot(index="date", columns="code", values="s_bal")
        out["ss_ratio"] = out["s_bal"] / m_bal.replace(0, np.nan) * 100
    return out


def _r(x, nd):
    if x is None or pd.isna(x) or not np.isfinite(x):
        return None
    return int(round(float(x))) if nd == 0 else round(float(x), nd)


ND = {s[0]: s[3] for s in STATS}


def series(g, code, shares):
    """單一股票每天的統計：{日期: [依 KEYS 順序的值]}，給 K 線圖滑鼠移到哪天就顯示哪天"""
    g = g.reset_index(drop=True)
    x = price_stats(g, shares)
    since = g["date"].iloc[max(0, len(g) - 400)]
    chip = _chip_wide(since, [code])
    dates = g["date"].tolist()
    for k, w in chip.items():
        x[k] = pd.Series(w[code].reindex(dates).to_numpy() if code in w.columns else np.nan, index=g.index)
    tail = max(0, len(g) - 400)
    return {dates[i]: [_r(x[k].iloc[i], ND[k]) if k in x else None for k in KEYS] for i in range(tail, len(g))}


_cache = {"key": None, "rows": None, "meta": None}


def table(engine):
    """全市場最新一天的統計（數據篩選頁用）。資料日期／法人日期沒變就用快取"""
    import settings
    from engine import is_common_stock
    con = connect()
    try:
        key = (engine.date, con.execute("SELECT MAX(date) FROM inst").fetchone()[0],
               con.execute("SELECT MAX(date) FROM margin").fetchone()[0], id(engine.prices))
    except Exception:
        key = (engine.date, None, None, id(engine.prices))
    finally:
        con.close()
    if _cache["key"] == key:
        return _cache["rows"], _cache["meta"]
    t0 = time.time()
    p = settings.load()
    px = engine.prices
    if px is None or px.empty:
        return [], {}
    px = px[px["code"].map(lambda c: is_common_stock(c, p) or c in p["watchlist"])].copy()
    px["k"] = px.groupby("code").cumcount() - px.groupby("code")["date"].transform("size") + 1
    W = {f: px.pivot(index="k", columns="code", values=f) for f in ("date", "high", "low", "close", "volume")}
    W = {k: v.iloc[-260:] for k, v in W.items()}           # 最近約一年就夠算
    shares = pd.Series(engine.shares, dtype=float).reindex(W["close"].columns)
    x = price_stats(W, shares)
    L = {k: v.iloc[-1] for k, v in x.items()}
    last_date = W["date"].iloc[-1]
    chip = _chip_wide((pd.Timestamp(engine.date) - pd.Timedelta(days=200)).date().isoformat())
    chip_date = {}
    for k, w in chip.items():
        if not len(w):
            continue
        L[k] = w.iloc[-1].reindex(W["close"].columns)
        chip_date[k] = w.index[-1]
    try:
        import chips
        ind = chips._industry()
    except Exception:
        ind = {}
    rows = []
    for code in W["close"].columns:
        if last_date[code] != engine.date:       # 今天沒交易（停牌、下市）
            continue
        name, market = engine.names.get(code, ("", ""))
        r = {"code": code, "name": name, "market": market, "ind": ind.get(code, "")}
        for k in KEYS:
            r[k] = _r(L[k][code], ND[k]) if k in L else None
        rows.append(r)
    meta = {"date": engine.date, "inst_date": chip_date.get("fi"), "margin_date": chip_date.get("s_bal"),
            "n": len(rows), "secs": round(time.time() - t0, 1)}
    _cache.update(key=key, rows=rows, meta=meta)
    return rows, meta
