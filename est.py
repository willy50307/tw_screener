"""看盤頁上方的「預估量」：加權指數、台指期、櫃買指數的目前成交金額（口數）和預估全天量。

算法（XQ 等看盤軟體的做法）：先用過去 N 天，算出「每天到這個時間點，成交量通常已經佔全天的幾 %」，
再用今天到現在的累計量 ÷ 這個比例 = 預估全天量。例如過去 20 天 10:00 時平均已成交全天的 31%，
今天 10:00 累計 2,000 億，預估就是 2,000 ÷ 0.31 ≈ 6,450 億。
比單純用「已過幾分鐘 / 270 分鐘」準，因為開盤和收盤集合競價的量本來就特別大。

資料：
  上市：證交所「每 5 秒委託成交統計」（MI_5MINS）過去 20 天做比例；今天的累計金額用群益 TSEA，沒有就用 MI_5MINS 今天最新一筆。
  上櫃：櫃買沒有免費的每 5 秒統計，比例借用上市的（兩邊的日內分布很像）；今天的累計金額用群益 OTCA。
  台指期：選股王資料庫裡台指期 5 分K（期交所逐筆檔整理的）過去 20 天做比例，日盤、夜盤分開；今天的口數用期貨看盤表的近月台指期。
"""
import datetime as dt
import json
import os
import threading
import time

import requests

import settings
from data import HEADERS, connect

DIR = os.path.join(settings.BASE, "data", "est")
DAYS = 20
_prof = {"tse": None, "tse_day": None, "tx": {}, "tx_day": None}
_lock = threading.Lock()
_busy = {"on": False}


def _n(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


def _mi5(d):
    """某一天的每 5 秒累計：[(9:00 起的秒數, 累計金額(元), 累計張數)]；抓過的存檔"""
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, f"mi5_{d:%Y%m%d}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS", params={"date": f"{d:%Y%m%d}", "response": "json"},
                     headers=HEADERS, timeout=20).json()
    rows = []
    for x in r.get("data") or []:
        h, m, s = map(int, x[0].split(":"))
        rows.append([(h - 9) * 3600 + m * 60 + s, _n(x[7]) * 1e6, _n(x[6])])
    if d < dt.date.today() and rows and rows[-1][0] >= 4.5 * 3600:   # 完整的一天才存（休市日存空的，免得一直重抓）
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rows, f)
    elif d < dt.date.today() and r.get("stat") != "OK":
        with open(p, "w", encoding="utf-8") as f:
            json.dump([], f)
    return rows


def _curve(rows, step, total_len, absolute=False):
    """累計序列 → 每 step 秒一格的「佔全天比例」（absolute=True 回傳累計值本身，給「較昨日同時間」用）"""
    full = rows[-1][1] if rows else 0
    if not full:
        return None
    out, k = [], 0
    for t in range(0, total_len + 1, step):
        while k + 1 < len(rows) and rows[k + 1][0] <= t:
            k += 1
        v = rows[k][1] if rows[k][0] <= t else 0
        out.append(v if absolute else v / full)
    return out


def _avg(curves):
    return [sum(c[i] for c in curves) / len(curves) for i in range(len(curves[0]))]


def _build_tse():
    """上市：過去 20 個交易日每 5 秒（9:00～13:30，跟證交所資料一樣細，開盤第一分鐘就能估）平均累計比例"""
    curves, prev, totals, d = [], None, [], dt.date.today() - dt.timedelta(days=1)
    for _ in range(45):
        if len(curves) >= DAYS:
            break
        if d.weekday() < 5:
            try:
                rows = _mi5(d)
                if not os.path.exists(os.path.join(DIR, f"mi5_{d:%Y%m%d}.json")):
                    time.sleep(1.5)   # 新抓的才要等，別打太快
            except Exception as e:
                print("預估量：抓 MI_5MINS 失敗", d, e)
                rows = []
                time.sleep(3)
            c = _curve([(t, a) for t, a, _ in rows], 5, 270 * 60)
            if c:
                curves.append(c)
                totals.append((d.isoformat(), rows[-1][1]))
                if prev is None:   # 最近一個交易日的累計金額，給「較昨日同時間」
                    prev = _curve([(t, a) for t, a, _ in rows], 5, 270 * 60, absolute=True)
        d -= dt.timedelta(days=1)
    if not curves:
        return None
    return {"curve": _avg(curves), "days": len(curves), "step": 5, "start": "09:00", "prev": prev, "totals": totals[:5]}


def _otc_totals():
    """上櫃每天的成交金額（約略）：資料庫日K 收盤價×成交量加總，跟櫃買公布的差 1% 左右。新到舊最近 5 天"""
    con = connect()
    rows = con.execute("SELECT date, SUM(close*volume) FROM prices WHERE market='上櫃' AND date >= ? GROUP BY date ORDER BY date DESC LIMIT 5",
                       ((dt.date.today() - dt.timedelta(days=20)).isoformat(),)).fetchall()
    con.close()
    return [(d, v) for d, v in rows if d < dt.date.today().isoformat()]


def _build_tx():
    """台指期：資料庫裡 TX 5 分K，日盤（8:45 起 300 分鐘）、夜盤（15:00 起 840 分鐘）各自的平均累計比例"""
    con = connect()
    rows = con.execute("SELECT ts, volume FROM intraday WHERE code='TX' AND tf='5' ORDER BY ts").fetchall()
    con.close()
    out = {}
    for sess, start, length in (("0", dt.time(8, 45), 300), ("1", dt.time(15, 0), 840)):
        days = {}
        for ts, v in rows:
            t = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=ts)   # 資料庫的 ts 是「台北時間當作 UTC」
            base = dt.datetime.combine(t.date(), start)
            if sess == "1" and t.time() < dt.time(12, 0):
                base -= dt.timedelta(days=1)          # 半夜到清晨屬於前一天開始的夜盤
            off = (t - base).total_seconds()
            if 0 <= off < length * 60:
                days.setdefault(base.date(), []).append((off + 300, v))   # K 棒時間是開頭，收完這根才算進累計
        curves, cums = [], []
        for day in sorted(days)[-DAYS - 1:]:
            acc, cum = 0, []
            for off, v in sorted(days[day]):
                acc += v / 1000          # 資料庫的量是 口×1000
                cum.append((off, acc))
            if cum and cum[-1][0] >= length * 60 * 0.9:
                curves.append(_curve(cum, 300, length * 60))
                cums.append(cum)
        curves = [c for c in curves if c][-DAYS:]
        if curves:
            out[sess] = {"curve": _avg(curves), "days": len(curves), "step": 300, "start": start.strftime("%H:%M"),
                         "prev": _curve(cums[-1], 300, length * 60, absolute=True)}
    return out


def _refresh():
    try:
        tse = _build_tse()
        tx = _build_tx()
        otc = _otc_totals()
        with _lock:
            _prof.update(tse=tse, tx=tx, otc_totals=otc, tse_day=dt.date.today(), tx_day=dt.date.today())
    except Exception as e:
        print("預估量：建立比例失敗", e)
    finally:
        _busy["on"] = False


def profiles():
    """一天重算一次（第一次要抓 20 天的證交所資料，約 30 秒，在背景跑）"""
    if _prof["tse_day"] != dt.date.today() and not _busy["on"]:
        _busy["on"] = True
        threading.Thread(target=_refresh, daemon=True).start()
    return _prof


def _at(curve, step, secs):
    """曲線在第 secs 秒的值（格子中間用直線內插；台指期是 5 分鐘一格，不內插 9:05 前會一直停在第一格）"""
    if not curve or secs < 0:
        return None
    x = secs / step
    i = int(x)
    if i >= len(curve) - 1:
        return curve[-1]
    return curve[i] + (curve[i + 1] - curve[i]) * (x - i)


def estimate(kind, cum, now=None):
    """kind = tse / otc / tx0 / tx1；cum = 今天到現在的累計（金額或口數）。
    回傳 (預估全天, 已佔比例, 前一個交易日同時間的累計)；前一日同時間只有上市、台指期有（櫃買沒有免費的逐 5 秒資料）"""
    p = profiles()
    now = now or dt.datetime.now()
    prof = p["tse"] if kind in ("tse", "otc") else (p["tx"] or {}).get(kind[-1])
    if not prof:
        return None, None, None
    h, mi = map(int, prof["start"].split(":"))
    base = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if kind == "tx1" and now.time() < dt.time(12, 0):
        base -= dt.timedelta(days=1)
    secs = (now - base).total_seconds()
    prev = _at(prof.get("prev"), prof["step"], secs) if kind != "otc" else None
    if secs >= (len(prof["curve"]) - 1) * prof["step"]:
        return cum, 1.0, prev
    f = _at(prof["curve"], prof["step"], secs)
    if not cum or not f or f < 0.003:   # 剛開盤幾秒，比例太小會亂跳，先不估
        return None, f, prev
    return cum / f, f, prev


def yesterday(kind, pre):
    """昨量：正在顯示的那一天的前一個交易日全天（pre = 現貨還沒開盤、畫面顯示的是前一天，所以要再往前一天）"""
    p = _prof
    if kind in ("tse", "otc"):
        tot = (p["tse"] or {}).get("totals") if kind == "tse" else p.get("otc_totals")
        k = 1 if pre else 0
        return tot[k][1] if tot and len(tot) > k else None
    prof = (p["tx"] or {}).get(kind[-1])
    return prof["prev"][-1] if prof and prof.get("prev") else None


def mi5_today():
    """證交所今天最新的累計成交金額（盤中有沒有更新要看證交所；沒有就回 None）"""
    if time.time() - _today["t"] < 30:   # 30 秒抓一次就好
        return _today["v"]
    _today["t"] = time.time()
    try:
        rows = _mi5(dt.date.today())
        _today["v"] = rows[-1][1] if rows else None
    except Exception:
        _today["v"] = None
    return _today["v"]


_today = {"t": 0, "v": None}
