"""
處置股 / 注意股：抓官方公告 → 套用法規 → 預測「明天收盤在什麼價位會被列注意」以及「被注意後會不會被處置」。

法規依據（115.08.03 修正、115.08.10 實施）：
  證交所：公布或通知注意交易資訊暨處置作業要點、第四條異常標準之詳細數據及除外情形
  櫃買中心：櫃檯買賣公布或通知注意交易資訊暨處置作業要點、第四條第一項各款異常標準之詳細數據及除外情形
處置條件（第六條）：
  連續 3 個營業日達第一款；或連續 5 個營業日、最近 10 個營業日內有 6 日、最近 30 個營業日內有 12 日達第一～八款
  最近 30 個營業日內第一次處置 → 5 個營業日、約每 2 分鐘撮合、單筆 10 張或累積 30 張以上預收
  第二次（含）以上 → 5 個營業日、約每 2 分鐘撮合、全部預收
  計算期間曾達第十三款（當沖）→ 處置期間改為 7 個營業日
注意：本模組是依公開法規自行估算，部分條件（券商集中度、融資券、借券、當沖、除權息調整）無法取得資料或未納入。
"""
import datetime as dt
import json
import math
import os
import re
import time

import numpy as np
import pandas as pd
import requests

from settings import BASE

HEADERS = {"User-Agent": "Mozilla/5.0"}
META_PATH = os.path.join(BASE, "data", "meta.json")
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
      "十一": 11, "十二": 12, "十三": 13, "十四": 14}

# 各市場的法規數字
RULES = {
    "上市": dict(c1=32, c1b=25, c1b_gap=50, diff=20, pe_cap=60, c34=25,
                c3_min_lots=500, c3_min_turn=0.1, c4_turn=10, c4_diff=5,
                c2=[(30, 100, 85), (60, 130, 110), (90, 160, 135)], c2_low=None,
                c2_ex=(25, 20), small_cap=None),
    "上櫃": dict(c1=30, c1b=23, c1b_gap=40, diff=20, pe_cap=65, c34=27,
                c3_min_lots=300, c3_min_turn=1, c4_turn=5, c4_diff=3,
                c2=[(30, 100, 80), (60, 140, 80), (90, 160, 80)], c2_low=[120, 180, 240],
                c2_ex=(27, 15), small_cap=8e7),
}
CLAUSE_NAME = {1: "6日累積漲跌幅", 2: "30/60/90日起迄漲跌幅", 3: "漲跌幅＋量放大", 4: "漲跌幅＋週轉率",
               5: "漲跌幅＋券商集中", 6: "本益比/淨值比", 7: "漲跌幅＋券資比", 8: "存託憑證溢折價",
               9: "成交量放大", 10: "累積週轉率", 11: "6日起迄價差", 12: "借券賣出", 13: "當日沖銷", 14: "其他"}


# ---------------- 抓資料 ----------------

def _get(url, params=None):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.encoding = "utf-8"
            return r.json()
        except Exception as e:
            print(f"  連線失敗({attempt + 1}/3): {url} {e}")
            time.sleep(3 * (attempt + 1))
    return None


def _roc(s):
    """'115/10/14'、'115.10.14'、'1151014' → '2026-10-14'"""
    m = re.findall(r"(\d{3})[./]?(\d{2})[./]?(\d{2})", s or "")
    if not m:
        return None
    y, mo, d = m[0]
    return f"{int(y) + 1911}-{mo}-{d}"


def _clauses(text):
    nums = re.findall(r"第([一二三四五六七八九十]+)款", text or "")
    return sorted({CN[n] for n in nums if n in CN})


def fetch_attention(start: dt.date, end: dt.date):
    out = []
    j = _get("https://www.twse.com.tw/rwd/zh/announcement/notice",
             {"querytype": "1", "startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "response": "json"})
    for r in (j or {}).get("data", []) or []:
        out.append(("上市", r[1].strip(), r[2].strip(), _roc(r[5]), r[4]))
    j = _get("https://www.tpex.org.tw/www/zh-tw/bulletin/attention",
             {"startDate": start.strftime("%Y/%m/%d"), "endDate": end.strftime("%Y/%m/%d"), "response": "json"})
    for t in (j or {}).get("tables", []) or []:
        for r in t.get("data", []):
            if str(r[1]).strip():
                out.append(("上櫃", str(r[1]).strip(), str(r[2]).strip(), _roc(r[5]), r[4]))
    return [o for o in out if o[3]]


def fetch_disposal(start: dt.date, end: dt.date):
    out = []
    j = _get("https://www.twse.com.tw/rwd/zh/announcement/punish",
             {"startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "response": "json"})
    for r in (j or {}).get("data", []) or []:
        p = re.findall(r"\d{3}/\d{2}/\d{2}", r[6])
        if len(p) == 2:
            out.append(("上市", r[2].strip(), r[3].strip(), _roc(r[1]), _roc(p[0]), _roc(p[1]), r[5], r[7], r[8]))
    j = _get("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal",
             {"startDate": start.strftime("%Y/%m/%d"), "endDate": end.strftime("%Y/%m/%d"), "response": "json"})
    for t in (j or {}).get("tables", []) or []:
        for r in t.get("data", []):
            p = re.findall(r"\d{3}/\d{2}/\d{2}", str(r[5]))
            if str(r[2]).strip() and len(p) == 2:
                name = re.sub(r"\(.*", "", str(r[3])).strip()
                detail = re.sub(r"<br\s*/?>", "\n", str(r[8]))
                out.append(("上櫃", str(r[2]).strip(), name, _roc(r[1]), _roc(p[0]), _roc(p[1]), r[6], r[7], detail))
    return out


def fetch_meta():
    """產業別、股本（算週轉率）、本益比、休市日"""
    meta = {"company": {}, "pe": {}, "holidays": [], "date": dt.date.today().isoformat()}

    def face(s):
        m = re.search(r"([\d.]+)", s or "")
        return float(m.group(1)) if m and float(m.group(1)) > 0 else 10.0

    for r in _get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L") or []:
        cap = float(r.get("實收資本額") or 0)
        pref = float(r.get("特別股") or 0)
        meta["company"][r["公司代號"].strip()] = {"ind": r.get("產業別", "").strip(), "cap": cap,
                                                 "shares": max(cap / face(r.get("普通股每股面額")) - pref, 0)}
    for r in _get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O") or []:
        cap = float(r.get("Paidin.Capital.NTDollars") or 0)
        pref = float(r.get("PreferredStock.shares") or 0)
        meta["company"][r["SecuritiesCompanyCode"].strip()] = {
            "ind": r.get("SecuritiesIndustryCode", "").strip(), "cap": cap,
            "shares": max(cap / face(r.get("ParValueOfCommonStock")) - pref, 0)}
    for r in _get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL") or []:
        meta["pe"][r["Code"].strip()] = r.get("PEratio") or ""
    for r in _get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis") or []:
        meta["pe"][r["SecuritiesCompanyCode"].strip()] = r.get("PriceEarningRatio") or ""
    for r in _get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule") or []:
        if "開始交易" not in r["Name"] and "最後交易" not in r["Name"]:
            meta["holidays"].append(_roc(r["Date"]))
    meta["closures"] = fetch_closures(meta["holidays"])
    return meta


def fetch_closures(holidays, months=4):
    """臨時休市日（颱風等）：平日、不在休市表裡、但官方日成交資料沒有這天"""
    today = dt.date.today()
    traded, first = set(), None
    for k in range(months - 1, -1, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        j = _get("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
                 {"date": f"{y}{m:02d}01", "stockNo": "2330", "response": "json"})
        rows = (j or {}).get("data") or []
        if not rows:
            return []          # 抓不到就不要亂猜
        traded |= {_roc(r[0]) for r in rows}
        first = first or dt.date(y, m, 1)
    last, hol, out = max(traded), set(holidays), []
    d = first
    while d.isoformat() <= last:
        if d.weekday() < 5 and d.isoformat() not in traded and d.isoformat() not in hol:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def update(con, days_back=75):
    """每天更新：注意/處置公告（最近 75 天，涵蓋 30 個營業日）、公司資料"""
    today = dt.date.today()
    start = today - dt.timedelta(days=days_back)
    con.execute("""CREATE TABLE IF NOT EXISTS attention(market TEXT, code TEXT, name TEXT, date TEXT, clauses TEXT, text TEXT,
                   PRIMARY KEY(market, code, date))""")
    con.execute("""CREATE TABLE IF NOT EXISTS disposal(market TEXT, code TEXT, name TEXT, ann TEXT, start TEXT, end TEXT,
                   cond TEXT, measure TEXT, detail TEXT, PRIMARY KEY(market, code, ann, start))""")
    att = fetch_attention(start, today)
    con.executemany("INSERT OR REPLACE INTO attention VALUES(?,?,?,?,?,?)",
                    [(m, c, n, d, ",".join(map(str, _clauses(t))), t) for m, c, n, d, t in att])
    dis = fetch_disposal(start, today)
    con.executemany("INSERT OR REPLACE INTO disposal VALUES(?,?,?,?,?,?,?,?,?)", dis)
    con.commit()
    meta = fetch_meta()
    if meta["company"]:
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    print(f"  注意公告 {len(att)} 筆、處置公告 {len(dis)} 筆、公司資料 {len(meta['company'])} 家")


def load_meta():
    try:
        with open(META_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"company": {}, "pe": {}, "holidays": []}


# ---------------- 工具 ----------------

def tick(p):
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5


def ceil_tick(x):
    t = tick(x)
    return round(math.ceil(x / t - 1e-9) * t, 2)


def floor_tick(x):
    t = tick(x)
    return round(math.floor(x / t + 1e-9) * t, 2)


class Calendar:
    def __init__(self, past_days, holidays):
        self.past = sorted(past_days)
        self.holidays = set(holidays)

    def next_days(self, after: str, n: int):
        d, out = dt.date.fromisoformat(after), []
        while len(out) < n:
            d += dt.timedelta(days=1)
            if d.weekday() < 5 and d.isoformat() not in self.holidays:
                out.append(d.isoformat())
        return out

    def count_between(self, after: str, until: str):
        """after < d <= until 的交易日數"""
        n, d, end = 0, dt.date.fromisoformat(after), dt.date.fromisoformat(until)
        while d < end:
            d += dt.timedelta(days=1)
            if d.weekday() < 5 and d.isoformat() not in self.holidays:
                n += 1
        return n


def md(d):
    return f"{int(d[5:7])}/{int(d[8:10])}" if d else ""


# ---------------- 主計算 ----------------

class NoticeAnalyzer:
    def __init__(self, con, prices: pd.DataFrame):
        self.meta = load_meta()
        self.today = prices["date"].max()
        closures = self.meta.get("closures", [])
        self.cal = Calendar(prices["date"].unique(), self.meta.get("holidays", []) + closures)
        att = pd.read_sql("SELECT * FROM attention", con) if _has(con, "attention") else pd.DataFrame(
            columns=["market", "code", "name", "date", "clauses", "text"])
        dis = pd.read_sql("SELECT * FROM disposal", con) if _has(con, "disposal") else pd.DataFrame(
            columns=["market", "code", "name", "ann", "start", "end", "cond", "measure", "detail"])
        # 公告寫「遇休市、全日暫停交易則順延執行」：處置期間碰到臨時休市（颱風），迄日往後順延（官方資料不會改）
        if closures and len(dis):
            def shift(r):
                n = sum(r["ann"] < c and r["start"] <= c <= r["end"] for c in closures)
                return self.cal.next_days(r["end"], n)[-1] if n else r["end"]
            dis["end"] = dis.apply(shift, axis=1)
        self.att = {c: g.sort_values("date") for c, g in att.groupby("code")}
        self.dis = {c: g.sort_values("ann") for c, g in dis.groupby("code")}
        self.days = sorted(prices["date"].unique())
        self._build_wide(prices)

    # ----- 全市場表格 & 平均值 -----
    def _build_wide(self, prices):
        px = prices[prices["date"] >= self.days[max(0, len(self.days) - 95)]]
        self.C = px.pivot(index="date", columns="code", values="close")
        self.V = px.pivot(index="date", columns="code", values="volume") / 1000   # 張
        self.market = px.groupby("code")["market"].last()
        pct = (self.C / self.C.shift(1) - 1) * 100
        self.pct = pct.round(2)
        comp, pe = self.meta.get("company", {}), self.meta.get("pe", {})
        self.ind = pd.Series({c: comp.get(c, {}).get("ind", "") for c in self.C.columns})
        self.shares = pd.Series({c: comp.get(c, {}).get("shares", 0) for c in self.C.columns})
        self.cap = pd.Series({c: comp.get(c, {}).get("cap", 0) for c in self.C.columns})

        def pe_bad(c):
            v = pe.get(c, None)
            if v is None:
                return False
            try:
                x = float(v)
            except ValueError:
                return True  # 空白＝虧損（負值）
            return x < 0 or x >= RULES[self.market.get(c, "上市")]["pe_cap"]
        self.pe_bad = pd.Series({c: pe_bad(c) for c in self.C.columns})

        # 各種平均值（以今天的數值估計明天）
        s6 = self.pct.iloc[-6:].sum(min_count=6)
        self.avg = {}
        for mk in ("上市", "上櫃"):
            cols = self.market.index[self.market == mk]
            s = s6[cols].dropna()
            ind = self.ind[s.index]
            turn = (self.V.iloc[-1][cols] * 1000 / self.shares[cols].replace(0, np.nan) * 100).dropna()
            avg60 = self.V.iloc[-60:][cols].mean()
            mult = (self.V.iloc[-1][cols] / avg60.replace(0, np.nan)).dropna()
            win = {}
            for n, _, _ in RULES[mk]["c2"]:
                if len(self.C) >= n:
                    ch = (self.C.iloc[-1][cols] / self.C.iloc[-n][cols] - 1) * 100
                    win[n] = (ch.mean(), ch.groupby(self.ind[cols]).agg(["mean", "size"]))
            self.avg[mk] = {"s6": s.mean(), "s6_ind": s.groupby(ind).agg(["mean", "size"]),
                            "turn": turn.mean(), "mult": mult.mean(), "win": win}

    def _ind_avg(self, code, key, n=None):
        mk = self.market[code]
        ind = self.ind.get(code, "")
        tbl = self.avg[mk]["s6_ind"] if key == "s6" else self.avg[mk]["win"].get(n, (0, pd.DataFrame()))[1]
        if not ind or self.pe_bad[code] or ind not in tbl.index or tbl.loc[ind, "size"] < 5:
            return None
        return tbl.loc[ind, "mean"]

    # ----- 注意紀錄 & 處置次數 -----
    def history(self, code):
        """最近 30 個營業日內、上次處置公告之後的注意紀錄 [(date, [clauses])]"""
        g = self.att.get(code)
        if g is None:
            return []
        last30 = self.days[-30:]
        d = self.dis.get(code)
        reset = d["ann"].max() if d is not None and len(d) else ""
        return [(r.date, [int(x) for x in r.clauses.split(",") if x]) for r in g.itertuples()
                if r.date in last30 and r.date > reset]

    def need_counts(self, code):
        """還差幾次注意會被處置（假設之後每天都被注意）"""
        hist = dict(self.history(code))
        days = self.days[-30:]
        a1 = [1 in hist.get(d, []) for d in days]
        a18 = [any(1 <= c <= 8 for c in hist.get(d, [])) for d in days]

        def streak(a):
            k = 0
            for x in reversed(a):
                if not x:
                    break
                k += 1
            return k

        def window_need(a, win, req):
            for n in range(1, req + 1):
                if sum(a[len(a) - (win - n):]) + n >= req:
                    return n
            return req

        return {"3": 3 - min(streak(a1), 2), "5": 5 - min(streak(a18), 4),
                "10": window_need(a18, 10, 6), "30": window_need(a18, 30, 12),
                "a1_streak": streak(a1), "a18_streak": streak(a18),
                "a18_10": sum(a18[-10:]), "a18_30": sum(a18), "used13": any(13 in v for v in hist.values())}

    def disposal_status(self, code):
        """目前處置中（或明天開始處置）的資訊"""
        d = self.dis.get(code)
        if d is None:
            return None
        cur = d[d["end"] >= self.today]
        if cur.empty:
            return None
        r = cur.sort_values("start").iloc[-1]
        left = self.cal.count_between(self.today, r["end"])
        out_day = self.cal.next_days(r["end"], 1)[0]
        second = ("二" in str(r["measure"])) or ("再次" in str(r["measure"]))
        # 明日「急殺 -6%」掛單價：明天要在處置期間內，而且不是出關前一天（處置最後一天）
        tomorrow = self.cal.next_days(self.today, 1)[0]
        cs = self.C[code].dropna() if code in self.C.columns else None
        close = float(cs.iloc[-1]) if cs is not None and len(cs) else None     # 停牌的股票用最後一個有成交的收盤價
        dip_ok = bool(close) and r["start"] <= tomorrow < r["end"]
        dip_note = "" if dip_ok else ("明天是出關前一天，不做" if tomorrow == r["end"] else "明天已出關")
        return {
            "dip_price": floor_tick(close * 0.94) if close else None, "dip_ok": dip_ok, "dip_note": dip_note,
            "dip_base": close,"cond": _short_cond(r["cond"]), "cond_full": r["cond"], "measure": r["measure"],
                "start": r["start"], "end": r["end"], "out": out_day, "left": left,
                "started": r["start"] <= self.today, "ann": r["ann"],
                "match": "約每2分鐘撮合；" + ("所有委託全額預收" if second else "單筆10張或累積30張以上全額預收"),
                "detail": str(r["detail"])}

    def prior_disposal_30(self, code):
        d = self.dis.get(code)
        if d is None:
            return False
        return bool((d["ann"] >= self.days[-30]).any())

    # ----- 明日注意觸發價 -----
    def triggers(self, code):
        if code not in self.C.columns or self.C[code].iloc[-1] != self.C[code].iloc[-1]:
            return []
        mk = self.market[code]
        R = RULES[mk]
        c = self.C[code].dropna()
        p = self.pct[code].dropna()
        if len(c) < 7:
            return []
        C0 = float(c.iloc[-1])
        lim_up, lim_dn = floor_tick(C0 * 1.1), ceil_tick(C0 * 0.9)
        S5 = float(p.iloc[-5:].sum())
        small = R["small_cap"] and 0 < self.cap.get(code, 0) < R["small_cap"]
        mavg = None if small else self.avg[mk]["s6"]
        iavg = None if small else self._ind_avg(code, "s6")
        out = []

        def need_cum(base, direction):
            vals = [base]
            for a in (mavg, iavg):
                if a is not None:
                    vals.append(a + R["diff"] if direction > 0 else -(R["diff"] - a))
            return max(vals) if direction > 0 else min(vals)

        def px_for(cum):
            return C0 * (1 + (cum - S5) / 100)

        def add(clause, direction, price, cond="", vol=None):
            if price is None or price != price:
                return
            price = ceil_tick(price) if direction > 0 else floor_tick(price)
            if direction > 0:
                status = "already" if price <= lim_dn else ("ok" if price <= lim_up else "no")
            else:
                status = "already" if price >= lim_up else ("ok" if price >= lim_dn else "no")
            out.append({"clause": clause, "dir": direction, "price": price, "pct": round((price / C0 - 1) * 100, 2),
                        "status": status, "cond": cond, "vol": vol})

        if C0 >= 5:
            start4 = float(c.iloc[-5])     # 明天的 6 日區間起點（t-4）
            for dr in (1, -1):
                a = px_for(need_cum(dr * (R["c1"] + 0.01), dr))
                b = px_for(need_cum(dr * (R["c1b"] + (0.01 if mk == "上市" else 0)), dr))
                b = max(b, start4 + R["c1b_gap"]) if dr > 0 else min(b, start4 - R["c1b_gap"])
                best = min(a, b) if dr > 0 else max(a, b)
                add(1, dr, best, "" if best == a else f"且起迄價差≥{R['c1b_gap']}元")

        # 第三、四款：漲跌幅 25%/27% ＋ 量
        shares = self.shares.get(code, 0)
        v = self.V[code].dropna()
        for dr in (1, -1):
            price34 = px_for(need_cum(dr * (R["c34"] + 0.01), dr))
            if len(v) >= 60:
                m = max(5, (self.avg[mk]["mult"] or 0) + 4)
                s59 = float(v.iloc[-59:].sum())
                v3 = m * s59 / (60 - m) if m < 60 else None
                if shares and v3:
                    v3 = max(v3, R["c3_min_lots"], shares / 1000 * R["c3_min_turn"] / 100)
                add(3, dr, price34, f"且量≥{v3:,.0f}張（量放大{m:.1f}倍）" if v3 else "", v3)
            if shares:
                t = max(R["c4_turn"], (self.avg[mk]["turn"] or 0) + R["c4_diff"])
                v4 = shares / 1000 * t / 100
                add(4, dr, price34, f"且量≥{v4:,.0f}張（週轉率≥{t:.1f}%）", v4)

        # 第二款：30/60/90 日起迄漲跌幅
        had_c1 = any(1 in cl for _, cl in self.history(code))
        for i, (n, th, df_) in enumerate(R["c2"]):
            if len(c) < n - 1:
                continue
            if R["c2_low"] and C0 < 5:
                th = R["c2_low"][i]
            base = float(c.iloc[-(n - 1)])   # 明天的 n 日區間起點
            mav = None if small else self.avg[mk]["win"].get(n, (None,))[0]
            iav = None if small else self._ind_avg(code, "win", n)
            for dr in (1, -1):
                need = [dr * (th + 0.01)] + [a + dr * df_ for a in (mav, iav) if a is not None]
                need = max(need) if dr > 0 else min(need)
                price = base * (1 + need / 100)
                price = max(price, C0 + tick(C0)) if dr > 0 else min(price, C0 - tick(C0))
                if had_c1:  # 除外：30 日內已因第一款被注意，6 日漲跌幅也要夠大
                    ex = px_for(need_cum(dr * (R["c2_ex"][0] + 0.01), dr))
                    price = max(price, ex) if dr > 0 else min(price, ex)
                add(2, dr, price, f"（{n}日起迄{'漲' if dr > 0 else '跌'}幅）")

        # 第十一款：股價逾千元的 6 日起迄價差
        recent11 = any(11 in cl for d, cl in self.history(code) if d in self.days[-5:])
        if not recent11 and C0 > 700:
            w = c.iloc[-5:]                 # 明天 6 日區間的前 5 天
            w0, wmax, wmin = float(w.iloc[0]), float(w.max()), float(w.min())
            # 級距：(1000,2000] 價差 300 元，之後每 1000 元一級、價差 +150 元
            tiers = [(1000 + 1000 * k, 2000 + 1000 * k, 300 + 150 * k) for k in range(20)]
            for lo, hi, gap in tiers:       # 上漲：收盤是 6 日最高且比起點高出 gap
                x = max(w0 + gap, wmax + tick(wmax), lo + tick(lo))
                if x <= hi:
                    add(11, 1, x)
                    break
            for lo, hi, gap in reversed(tiers):   # 下跌：收盤是 6 日最低且比起點低 gap
                x = min(w0 - gap, wmin - tick(wmin), hi)
                if lo < x:
                    add(11, -1, x)
                    break
        # 同款同方向只留最容易達到的
        best = {}
        for t in out:
            k = (t["clause"], t["dir"])
            if k not in best or (t["price"] < best[k]["price"] if t["dir"] > 0 else t["price"] > best[k]["price"]):
                best[k] = t
        return sorted(best.values(), key=lambda t: (t["clause"], -t["dir"]))

    # ----- 給畫面用的整理 -----
    def summary(self, code):
        hist = self.history(code)
        nd = self.need_counts(code)
        ds = self.disposal_status(code)
        trig = self.triggers(code)
        today_cl = next((cl for d, cl in hist if d == self.today), [])
        need = min(nd["3"], nd["5"], nd["10"], nd["30"])
        nth = "第2次" if self.prior_disposal_30(code) else "第1次"
        days = 7 if nd["used13"] else 5
        # 明天被注意的話會不會處置
        tomorrow = self.cal.next_days(self.today, 2)
        lead = []
        if nd["3"] == 1:
            lead.append(("連續3日第一款", [1]))
        for k, name in (("5", "連續5日"), ("10", "10日內6次"), ("30", "30日內12次")):
            if nd[k] == 1:
                lead.append((name + "（第1~8款）", list(range(1, 9))))
        fc = None
        if need <= 2:
            fc = {"need": need, "nth": nth, "days": days,
                  "first_day": self.cal.next_days(self.today, need + 1)[-1],
                  "rules": [n for n, _ in lead],
                  "clauses": sorted({c for _, cl in lead for c in cl})}
        return {
            "today": today_cl, "hist": [[d, cl] for d, cl in hist], "need": nd, "min_need": need,
            "disp": ds, "triggers": trig, "fc": fc, "tomorrow": tomorrow[0], "nth": nth, "days": days,
        }


def _short_cond(s):
    s = str(s)
    for a, b in (("連續三次", "連續3日"), ("連續五次", "連續5日"), ("最近十個營業日已有六次", "10日內6次"),
                 ("連續3個營業日", "連續3日"), ("連續5個營業日", "連續5日"), ("最近10個營業日內有6個營業日", "10日內6次"),
                 ("最近30個營業日內有12個營業日", "30日內12次"), ("最近三十個營業日已有十二次", "30日內12次"),
                 ("及當日沖銷標準", "＋當沖"), ("及沖銷標準", "＋當沖")):
        s = s.replace(a, b)
    return s


def _has(con, table):
    return con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
