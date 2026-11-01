"""選股引擎：讀資料庫 → 算指標 → 套策略 → 產生清單。App 和之後的雲端版都共用這支。"""
import datetime as dt
import threading
from functools import reduce

import numpy as np
import pandas as pd

import settings
import intraday
from data import connect, load_code, load_prices
from indicators import add_indicators, indicator_cols, predict_next
from notice import CLAUSE_NAME, NoticeAnalyzer, md
from strategies import FILTERS, STRATEGIES

FIELDS = ["date", "open", "high", "low", "close", "volume"]
LOAD_DAYS = 550          # 啟動時載入最近幾天（日曆天）
TF_LABEL = {"D": "日K", "W": "週K", "M": "月K", "60": "60分K", "5": "5分K"}


def resample(df, rule):
    """日K → 週K（W）/ 月K（M）。日期標在該週/該月最後一個交易日"""
    d = df.copy()
    key = pd.to_datetime(d["date"]).dt.to_period("W-FRI" if rule == "W" else "M")
    out = d.groupby(key, sort=True).agg(date=("date", "last"), open=("open", "first"), high=("high", "max"),
                                        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    return out.reset_index(drop=True)


def r2(x):
    return None if x is None or pd.isna(x) else round(float(x), 2)


# 指數／期貨：在「個股K」可以查（輸入 TX、台指期、TAIEX、加權），不會進選股、排行
SPECIAL = {"TX": ("台指期 近月 全盤(夜盤+日盤)", "期貨", "口"), "TXD": ("台指期 近月 日盤", "期貨", "口"), "TAIEX": ("加權指數", "指數", "億")}


def load_special(code):
    """台指期：每天成交量最大的月份（近月，換月時會有價差跳動）的日盤；加權指數：taiex_k。
    volume 存成「單位 × 1000」，讓畫面上「張」的算法直接變成口數／億元"""
    con = connect()
    try:
        if code in ("TX", "TXD"):
            f = pd.read_sql("SELECT date, session, contract, open, high, low, close, volume FROM fut_tx WHERE close IS NOT NULL", con)
            f = f[f["contract"].str.fullmatch(r"\d{6}")]
            # 近月：最後交易日（結算日）還沒過的合約裡最早到期的那個；結算日當天仍是舊合約
            last = f[(f["session"] == "一般") & (f["volume"] > 0)].groupby("contract")["date"].max()
            day = f[f["session"] == "一般"]
            day = day.assign(last=day["contract"].map(last))
            day = day[day["date"] <= day["last"]].sort_values(["date", "last"]).groupby("date").head(1)
            day = day.set_index("date")
            if code == "TX":      # 全盤：開＝前一晚夜盤開盤，高低含夜盤，收＝日盤收盤，量＝兩盤相加
                nt = f[(f["session"] == "盤後") & (f["volume"] > 0)].set_index(["date", "contract"])
                key = list(zip(day.index, day["contract"]))
                n = nt.reindex(key)
                n.index = day.index
                has = n["open"].notna()
                day.loc[has, "open"] = n.loc[has, "open"]
                day["high"] = np.fmax(day["high"], n["high"])
                day["low"] = np.fmin(day["low"], n["low"])
                day["volume"] = day["volume"] + n["volume"].fillna(0)
            f = day.reset_index()[["date", "open", "high", "low", "close", "volume"]]
            f["volume"] = f["volume"] * 1000
        else:
            f = pd.read_sql("SELECT date, open, high, low, close, amount AS volume FROM taiex_k ORDER BY date", con)
            f["volume"] = f["volume"].fillna(0) / 1e8 * 1000
    except Exception:
        return None
    finally:
        con.close()
    f = f.dropna(subset=["open", "high", "low", "close"])
    f["code"], f["name"], f["market"] = code, SPECIAL[code][0], SPECIAL[code][1]
    return f[["code", "date", "market", "name", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def is_common_stock(code, p):
    if not (len(code) == 4 and code.isdigit()):
        return False
    return p["include_etf"] or not code.startswith("0")


def run_strategies(d, p):
    """d 可以是單一股票 DataFrame 或全市場 dict。回傳 {策略key: 布林表, "entry": 進場布林表}"""
    ok = reduce(lambda a, b: a & b, [f(d, p).fillna(False).astype(bool) for f in FILTERS])
    sig = {key: fn(d, p).fillna(False).astype(bool) & ok for key, _, fn, _ in STRATEGIES}
    keys = [k for k, _, _, _ in STRATEGIES if p["strategies"].get(k, True)]
    if not keys:
        sig["entry"] = sig[STRATEGIES[0][0]] & False
    else:
        op = (lambda a, b: a | b) if p["entry_rule"] == "any" else (lambda a, b: a & b)
        sig["entry"] = reduce(op, [sig[k] for k in keys])
    return sig


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.groups = {}
        self.names = {}
        self.prices = None
        self.date = None
        self.rows = []
        self.notices = {"disp": {}, "attn": {}}
        self.na = None
        self.nbrief = {}
        self.shares = {}

    # ----- 處置 / 注意 -----
    def load_notice(self, prices):
        """整理處置中、今日注意、快被處置的股票（只算最近 30 日有注意紀錄的，比較快）"""
        if prices.empty:
            return
        con = connect()
        na = NoticeAnalyzer(con, prices)
        con.close()
        p = settings.load()
        codes = {c for c in set(na.att) | set(na.dis) | set(p["watchlist"]) if is_common_stock(c, p) or c in p["watchlist"]}
        brief, disp, attn = {}, {}, {}
        for c in codes:
            if c not in self.names:
                continue
            s = na.summary(c)
            if not (s["disp"] or s["today"] or s["fc"] or c in p["watchlist"]):
                continue
            ok = [t for t in s["triggers"] if t["status"] != "no"]
            # 排序：已達標 → 只看價格的條款 → 明天最容易達到的（漲的要漲越少越容易、跌的反之）
            ok.sort(key=lambda t: (t["status"] != "already", t["vol"] is not None, t["pct"] * t["dir"]))
            brief[c] = {
                "disp": s["disp"], "today": s["today"], "fc": s["fc"], "min_need": s["min_need"],
                "trig": [f"{_circ(t['clause'])}{'已達' if t['status'] == 'already' else ''}"
                         f"{t['price']:g}{'↑' if t['dir'] > 0 else '↓'}({t['pct']:+.1f}%)" for t in ok[:2]],
            }
            if s["disp"]:
                d = s["disp"]
                disp[c] = f"{d['cond']}｜{d['measure']}｜{md(d['start'])}~{md(d['end'])}"
            if s["today"]:
                g = na.att[c]
                attn[c] = "；".join(g[g["date"] == na.today]["text"].tolist())
        with self.lock:
            self.na, self.nbrief = na, brief
            self.shares = {c: v.get("shares", 0) for c, v in na.meta.get("company", {}).items()}
            self.notices = {"disp": disp, "attn": attn}

    # ----- 載入 -----
    def reload(self):
        # 選股只需要最近約一年半（MA120、90 日起迄漲幅都夠用）；完整歷史另外按需讀取
        since = (dt.date.today() - dt.timedelta(days=LOAD_DAYS)).isoformat()
        prices = load_prices(since)
        groups = {c: g.reset_index(drop=True) for c, g in prices.groupby("code", sort=False)}
        for c in SPECIAL:
            f = load_special(c)
            if f is not None and len(f) >= 30:
                groups[c] = f[f["date"] >= since].reset_index(drop=True)
        with self.lock:
            self.prices = prices
            self.groups = groups
            self.names = {c: (g["name"].iloc[-1], g["market"].iloc[-1]) for c, g in groups.items()}
            self.date = prices["date"].max() if len(prices) else None
        self.load_notice(prices)
        self.screen()

    def make_row(self, code, last, prev_close, hits, entry, pr, p):
        """pr：明日關鍵價 {shrink, cross, gap, max}"""
        close = float(last["close"])
        on = p["strategies"]
        need = [x for x, k in ((pr["shrink"], "green_shrink"), (pr["cross"], "golden_cross"))
                if on.get(k, True) and pd.notna(x)]
        if need and pd.notna(pr["max"]) and min(need) > pr["max"]:
            need = []  # 明天就算觸發，也會被過熱濾網擋掉
        name, market = self.names[code]
        return {
            "code": code, "name": name, "market": market, "date": last["date"],
            "close": r2(close), "chg": r2((close / prev_close - 1) * 100) if prev_close else None,
            "lots": int(last["volume"] / 1000),
            "hits": hits, "entry": bool(entry),
            "shrink": r2(pr["shrink"]) if on.get("green_shrink", True) else None,
            "cross": r2(pr["cross"]) if on.get("golden_cross", True) else None,
            "gap": r2(pr["gap"]) if on.get("gap_cross", True) else None,
            "max": r2(pr["max"]), "dif_pct": r2(last["dif"] / close * 100),
            "need_pct": r2((min(need) / close - 1) * 100) if need else None,
            "hist": r2(last["hist"]),
            "disp": self.notices["disp"].get(code, ""), "attn": self.notices["attn"].get(code, ""),
            "mine": code in p["watchlist"],
            "notice": self.nbrief.get(code),
        }

    # ----- 全市場選股（一次算完全部股票）-----
    def screen(self):
        p = settings.load()
        prices = self.prices
        if prices is None or prices.empty:
            with self.lock:
                self.rows = []
            return
        custom = [("wl_" + w["id"], set(w.get("codes", []))) for w in p.get("watchlists", [])]   # 自己新增的自選清單
        wl = set(p["watchlist"]).union(*(s for _, s in custom))
        counts = prices.groupby("code")["date"].transform("size")
        keep = prices["code"].map(lambda c: c in wl or is_common_stock(c, p)) & (counts >= 30)
        px = prices[keep].copy()
        # 每檔股票各自從最後一天往回對齊：k=0 是最後一天，-1 是前一天…（停牌的日子不會產生空格）
        px["k"] = px.groupby("code").cumcount() - px.groupby("code")["date"].transform("size") + 1
        W = {f: px.pivot(index="k", columns="code", values=f) for f in FIELDS}
        W.update(indicator_cols(W, p))
        sig = run_strategies(W, p)
        L = {k: v.iloc[-1] for k, v in W.items()}
        pred = {k: np.asarray(v, dtype=float) for k, v in predict_next(L, W["dif"].iloc[-2], p).items()}
        prev_close = W["close"].iloc[-2]
        S = {k: v.iloc[-1] for k, v in sig.items()}
        labels = [(k, label) for k, label, _, _ in STRATEGIES if p["strategies"].get(k, True)]

        # ----- 量價排行（排除成交量太小、股價低於 min_price 的水餃股）-----
        vol, close = W["volume"], W["close"]
        v0 = vol.iloc[-1]
        avg5 = vol.iloc[-6:-1].mean()                              # 前 5 天平均（不含今天）
        vratio = v0 / avg5.replace(0, np.nan)
        vgrow = (vol.iloc[-1] > vol.iloc[-2]) & (vol.iloc[-2] > vol.iloc[-3]) & (vol.iloc[-3] > vol.iloc[-4])
        vgrow_pct = (vol.iloc[-1] / vol.iloc[-4].replace(0, np.nan) - 1) * 100   # 3 天量增幅
        chg = (close.iloc[-1] / close.iloc[-2] - 1) * 100
        shares = pd.Series(self.shares).reindex(close.columns)
        turnover = v0 / shares.replace(0, np.nan) * 100
        elig = (L["date"] == self.date) & (v0 / 1000 >= p["min_lots"]) & (close.iloc[-1] >= p["min_price"])
        elig = elig & pd.Series([is_common_stock(c, p) for c in close.columns], index=close.columns)
        top_turn = set(turnover[elig].dropna().nlargest(50).index)
        top_gain = set(chg[elig].dropna().nlargest(50).index)
        surge = set(vratio[elig & (vratio >= 2)].index)
        grow = set(vgrow[elig & vgrow].index)

        rows = []
        for i, code in enumerate(W["close"].columns):
            mine = code in wl
            if L["date"][code] != self.date and not mine:
                continue
            last = {k: L[k][code] for k in ("date", "close", "volume", "hist", "dif")}
            entry = S["entry"][code]
            hits = [label for k, label in labels if S[k][code]]
            row = self.make_row(code, last, prev_close[code], hits, entry, {k: v[i] for k, v in pred.items()}, p)
            liquid = row["lots"] >= p["min_lots"] and row["close"] >= p["min_price"]
            blocked = p["exclude_disposition"] and row["disp"]
            lists = []
            if row["entry"] and liquid and not blocked:
                lists.append("signal")
            if not row["entry"] and liquid and not blocked and row["need_pct"] is not None \
                    and row["need_pct"] <= p["watch_pct"]:
                lists.append("watch")
            if row["disp"]:
                lists.append("disp")
            if row["attn"]:
                lists.append("attn")
            if row["notice"] and row["notice"]["fc"]:
                lists.append("fc")
            if code in p["watchlist"]:
                lists.append("mine")
            lists += [k for k, s in custom if code in s]
            for name, members in (("turn", top_turn), ("gain", top_gain), ("vsurge", surge), ("vgrow", grow)):
                if code in members:
                    lists.append(name)
            row["turnover"] = r2(turnover.get(code))
            row["vratio"] = r2(vratio.get(code))
            row["vgrow_pct"] = r2(vgrow_pct.get(code)) if code in grow else None
            if lists:
                row["lists"] = lists
                rows.append(row)
        with self.lock:
            self.rows = rows

    # ----- 單一股票 K 線圖資料 -----
    def history(self, code, since=None):
        """完整歷史日K（資料庫）"""
        if code in SPECIAL:
            f = load_special(code)
            return f if since is None or f is None else f[f["date"] >= since].reset_index(drop=True)
        return load_code(code, since)

    def chart(self, code, tf="D", n=None):
        """tf：D 日K、W 週K、M 月K、60 / 5 分K；n：顯示根數（0 或 None＝設定值；-1＝全部）"""
        p = settings.load()
        g = self.groups.get(code)
        if code in SPECIAL:            # 指數／期貨每次都讀資料庫最新的（不用等重新載入）
            f = load_special(code)
            if f is not None and len(f) >= 30:
                g = f.tail(max(len(g) if g is not None else 0, 400)).reset_index(drop=True)
        if g is None or len(g) < 30:
            return None
        # 右上角資訊（收盤、明日關鍵價…）一律用日K算
        df = add_indicators(g, p)
        sig = run_strategies(df, p)
        last = df.iloc[-1]
        pred = {k: float(v) for k, v in predict_next(last, df["dif"].iloc[-2], p).items()}
        labels = [(k, label) for k, label, _, _ in STRATEGIES if p["strategies"].get(k, True)]
        row = self.make_row(code, last, df["close"].iloc[-2], [label for k, label in labels if sig[k].iloc[-1]],
                            sig["entry"].iloc[-1], pred, p)
        if tf == "T":
            return self.trend(code, g, row)
        n = int(n or (-1 if tf in ("W", "M") else p["chart_days"]))   # 週K／月K 預設整段歷史
        err = None
        if tf == "D" and (n < 0 or n > len(g)):        # 要看比載入範圍更久的日K → 讀完整歷史
            full = self.history(code)
            if len(full) > len(g):
                df = add_indicators(full, p)
                sig = run_strategies(df, p)
        if tf in ("W", "M"):
            src = resample(self.history(code), tf)
        elif tf in ("60", "5") and code in ("TX", "TXD"):
            # 期交所逐筆成交轉成的分K（近 30 個交易日；TX 含夜盤、TXD 只取日盤 08:45~13:45）
            con = connect()
            src = pd.read_sql("SELECT ts AS date, open, high, low, close, volume FROM intraday WHERE code='TX' AND tf=? ORDER BY ts", con, params=(tf,))
            con.close()
            if code == "TXD" and len(src):
                hm = pd.to_datetime(src["date"], unit="s").dt.strftime("%H:%M")
                src = src[(hm >= "08:45") & (hm < "13:45")].reset_index(drop=True)
            err = None if len(src) else "還沒有台指期分K（每天下午 4 點後自動從期交所抓）"
        elif tf in ("60", "5"):
            src, err = intraday.get(code, self.names[code][1], tf)
        else:
            src = None
        if src is not None:
            if len(src) < 2:
                return {"row": row, "notice": None, "tf": tf, "error": err or "沒有這個週期的資料", "bars": [],
                        "ma5": [], "ma10": [], "ma20": [], "ma60": [], "ma120": [], "bbu": [], "bbd": [],
                        "dif": [], "dea": [], "hist": [], "marks": [], "keyp": [], "next_day": None}
            df = add_indicators(src, p)
        d = df if n < 0 else df.tail(n)
        t = d["date"].tolist()

        def line(col):
            return [[a, r2(b)] for a, b in zip(t, d[col]) if pd.notna(b)]

        marks, keyp, next_day = [], [], None
        if tf == "D":
            marks = [[a, short] for key, _, _, short in STRATEGIES if p["strategies"].get(key, True)
                     for a in d.loc[sig[key].loc[d.index], "date"]]
            # MACD 關鍵價預測（隔日偏移）：第 t 天顯示「用第 t-1 天收盤算出」的兩個關鍵價
            h_prev = df["hist"].shift(1)
            shrink = np.maximum(df["px_shrink"], df["px_difup"]).shift(1).where(h_prev < 0)   # 摸底：綠柱縮短且 DIF 上升
            cross = df["px_cross"].shift(1).where(h_prev <= 0)                                # 金叉
            di = (df["high"] + df["low"] + 2 * df["close"]) / 4 if p["price_source"] == "DI" else df["close"]
            keyp = [[a, r2(s_), r2(c_), r2(x_)] for a, s_, c_, x_ in
                    zip(t, shrink.loc[d.index], cross.loc[d.index], di.loc[d.index])]
            next_day = self.na.cal.next_days(self.date, 1)[0] if self.na is not None and row["date"] == self.date else None
        nsum = None
        if self.na is not None and code not in SPECIAL:
            nsum = self.na.summary(code)
            ag = self.na.att.get(code)
            texts = dict(zip(ag["date"], ag["text"])) if ag is not None else {}
            nsum["hist"] = [[x, cl, texts.get(x, "")] for x, cl in nsum["hist"]]
            nsum["clause_name"] = CLAUSE_NAME
        vol_div = 1000
        st = None
        if tf == "D" and code not in SPECIAL:     # 仿權證小哥的統計數據（連漲、均量比、月線斜率、外資連買…），每天一筆
            try:
                import stats
                ser = stats.series(df[["date", "open", "high", "low", "close", "volume"]], code, self.shares.get(code))
                st = {"keys": stats.STATS, "by_date": {a: ser[a] for a in t if a in ser}}
            except Exception:
                import traceback
                traceback.print_exc()
        return {
            "stats": st,
            "row": row, "notice": nsum, "tf": tf, "error": err, "total": int(len(df)),
            "vol_unit": SPECIAL[code][2] if code in SPECIAL else None,
            "bars": [[a, r2(o), r2(h), r2(l), r2(c), int(v / vol_div)] for a, o, h, l, c, v in
                     zip(t, d["open"], d["high"], d["low"], d["close"], d["volume"])],
            "ma5": line("ma5"), "ma10": line("ma10"), "ma20": line("ma20"), "ma60": line("ma60"), "ma120": line("ma120"),
            "bbu": line("bb_up"), "bbd": line("bb_dn"),
            "dif": line("dif"), "dea": line("dea"), "hist": line("hist"),
            "marks": marks,
            "keyp": keyp,            # [日期, 當日摸底價, 當日金叉價, 當日實際(高+低+2收)/4]
            "next_day": next_day,    # 明天日期（畫明日關鍵價用）
        }

    # ----- 盤中走勢圖（1 分K，Yahoo 只有最近 7 天）：價格、均價線、昨收 -----
    def trend(self, code, g, row, day=None):
        out = {"row": row, "tf": "T", "bars": [], "vwap": [], "days": []}
        if code in SPECIAL:
            out["error"] = "指數／期貨沒有走勢圖，請看 5分K"
            return out
        src, err = intraday.get(code, self.names[code][1], "1")
        out["src"] = "capital" if intraday.capital.ready() and intraday.capital._ticks.get(code) else "yahoo"
        if src is None or not len(src):
            out["error"] = err or "抓不到 1 分K（Yahoo 只有最近 7 天）"
            return out
        t = pd.to_datetime(src["date"], unit="s")
        src = src.assign(day=t.dt.strftime("%Y-%m-%d"), hm=t.dt.strftime("%H:%M"))
        src = src[(src["hm"] >= "09:00") & (src["hm"] <= "13:30")]
        days = sorted(src["day"].unique())
        if not days:
            out["error"] = "沒有盤中資料"
            return out
        day = day if day in days else days[-1]
        d = src[src["day"] == day].reset_index(drop=True)
        prev = g[g["date"] < day]
        ref = float(prev["close"].iloc[-1]) if len(prev) else float(d["open"].iloc[0])
        today = g[g["date"] == day]
        if len(today) and d["hm"].iloc[-1] < "13:30":   # Yahoo 沒有 13:30 收盤集合競價，用日K 收盤補一點
            c = float(today["close"].iloc[0])
            ts = int((pd.Timestamp(day + " 13:30") - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s"))
            d = pd.concat([d, pd.DataFrame([{"date": ts, "open": c, "high": c, "low": c, "close": c, "volume": 0, "day": day, "hm": "13:30"}])], ignore_index=True)
        tp = (d["high"] + d["low"] + d["close"]) / 3
        cv = d["volume"].cumsum()
        vwap = ((tp * d["volume"]).cumsum() / cv.replace(0, np.nan)).fillna(d["close"])
        out.update(day=day, days=days, ref=r2(ref),
                   bars=[[int(a), r2(o), r2(h), r2(l), r2(c), int(v / 1000)] for a, o, h, l, c, v in
                         zip(d["date"], d["open"], d["high"], d["low"], d["close"], d["volume"])],
                   vwap=[[int(a), r2(v)] for a, v in zip(d["date"], vwap)],
                   high=r2(d["high"].max()), low=r2(d["low"].min()),
                   day_close=r2(today["close"].iloc[0]) if len(today) else None,
                   day_lots=int(today["volume"].iloc[0] / 1000) if len(today) else None,
                   error=err if not len(d) else None)
        return out

    # ----- 加權指數日K（情緒頁用，同樣算 MACD / 關鍵價 / 策略訊號）-----
    def taiex_chart(self):
        p = settings.load()
        con = connect()
        df = pd.read_sql("SELECT date, open, high, low, close, amount AS volume FROM taiex_k ORDER BY date", con)
        con.close()
        if len(df) < 30:
            return None
        df["name"], df["market"] = "加權指數", "指數"
        df = add_indicators(df, p)
        sig = run_strategies(df, p)
        last, prev = df.iloc[-1], df.iloc[-2]
        pred = {k: float(v) for k, v in predict_next(last, prev["dif"], p).items()}
        t = df["date"].tolist()

        def line(col):
            return [[a, r2(b)] for a, b in zip(t, df[col]) if pd.notna(b)]
        h_prev = df["hist"].shift(1)
        shrink = np.maximum(df["px_shrink"], df["px_difup"]).shift(1).where(h_prev < 0)
        cross = df["px_cross"].shift(1).where(h_prev <= 0)
        di = (df["high"] + df["low"] + 2 * df["close"]) / 4
        row = {"code": "TAIEX", "name": "加權指數", "date": last["date"], "close": r2(last["close"]),
               "chg": r2((last["close"] / prev["close"] - 1) * 100),
               "shrink": r2(pred["shrink"]), "cross": r2(pred["cross"])}
        return {
            "row": row, "tf": "D", "vol_unit": "億",
            "bars": [[a, r2(o), r2(h), r2(l), r2(c), int(v / 1e8)] for a, o, h, l, c, v in
                     zip(t, df["open"], df["high"], df["low"], df["close"], df["volume"])],
            "ma5": line("ma5"), "ma10": line("ma10"), "ma20": line("ma20"), "ma60": line("ma60"), "ma120": line("ma120"),
            "bbu": line("bb_up"), "bbd": line("bb_dn"), "dif": line("dif"), "dea": line("dea"), "hist": line("hist"),
            "marks": [[a, short] for key, _, _, short in STRATEGIES if p["strategies"].get(key, True)
                      for a in df.loc[sig[key], "date"]],
            "keyp": [[a, r2(s_), r2(c_), r2(x_)] for a, s_, c_, x_ in zip(t, shrink, cross, di)],
            "next_day": self.na.cal.next_days(last["date"], 1)[0] if self.na is not None else None,
        }

    def disposal_periods(self):
        """{代號: [(處置起, 處置迄, 第幾次), ...]}，給回測用"""
        if self.na is None:
            return {}
        return {c: [(r.start, r.end, 2 if ("二" in str(r.measure) or "再次" in str(r.measure)) else 1)
                    for r in d.itertuples()] for c, d in self.na.dis.items()}

    # ----- 處置歷史（115/8/10 新制之後）-----
    def disposal_history(self, since="2026-08-10"):
        if self.na is None:
            return []
        p = settings.load()
        out = []
        for code, d in self.na.dis.items():
            g = self.groups.get(code)
            if g is None or not is_common_stock(code, p):
                continue
            dates = g["date"].tolist()
            C = g["close"].to_numpy(dtype=float)
            for r in d.itertuples():
                if r.start < since:
                    continue
                s_i = next((i for i, x in enumerate(dates) if x >= r.start), None)
                e_i = max((i for i, x in enumerate(dates) if x <= r.end), default=None)
                if s_i is None or e_i is None or s_i == 0:
                    continue

                def chg(a, b):
                    return r2((C[b] / C[a] - 1) * 100) if 0 <= a < len(C) and 0 <= b < len(C) else None
                ongoing = r.end > self.date
                out.append({
                    "code": code, "name": self.names[code][0], "market": self.names[code][1],
                    "ann": r.ann, "start": r.start, "end": r.end, "cond": _short(r.cond),
                    "nth": 2 if ("二" in str(r.measure) or "再次" in str(r.measure)) else 1,
                    "pre5": chg(s_i - 6, s_i - 1), "during": chg(s_i - 1, e_i),
                    "post5": None if ongoing else chg(e_i, e_i + 5), "post10": None if ongoing else chg(e_i, e_i + 10),
                    "ongoing": ongoing, "close": r2(C[-1]),
                })
        return sorted(out, key=lambda x: (x["start"], x["code"]), reverse=True)

    def search(self, q, limit=20):
        q = q.strip()
        if not q:
            return []
        hits = [(c, n, m) for c, (n, m) in self.names.items() if c.upper().startswith(q.upper()) or q in n]
        alias = {"TX": ("台指", "期貨", "大台", "台股指數", "指數期貨", "全盤"), "TXD": ("台指", "期貨", "大台", "日盤"),
                 "TAIEX": ("加權", "大盤", "指數", "台股指數")}
        hits += [(c, *self.names[c]) for c, words in alias.items() if c in self.names and any(w in q or q in w for w in words)
                 and c not in [h[0] for h in hits]]
        hits.sort(key=lambda x: (not x[0].startswith(q), len(x[0]), x[0]))
        return [{"code": c, "name": n, "market": m} for c, n, m in hits[:limit]]


def _short(s):
    from notice import _short_cond
    return _short_cond(s)


def _circ(n):
    return "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭"[n - 1] if 1 <= n <= 14 else str(n)
