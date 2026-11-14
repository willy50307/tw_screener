"""
美國信用利差：ICE BofA 公司債選擇權調整利差（OAS），資料來源 = 美國聖路易聯準銀行 FRED 公開 CSV（免金鑰）
  BAMLH0A0HYM2  高收益債（垃圾債）利差
  BAMLC0A0CM    投資級公司債利差
  BAMLC0A4CBBB  BBB 級利差（投資級最底層）
  BAMLH0A3HYC   CCC 級以下利差（最爛的垃圾債）
單位都是「百分點」（例 3.10 ＝ 比同天期美國公債多 3.10%）。
只下載純文字 CSV，只解析日期＋數字，不執行任何下載內容。結果快取在 data/credit_spread.json，6 小時內不重抓。
"""
import datetime as dt
import io
import json
import os
import threading

import requests

# FRED 會擋只寫 "Mozilla/5.0" 的 UA（連線直接被斷），所以不用 data.HEADERS
HEADERS = {"User-Agent": "tw-screener/1.0"}

SERIES = [("hy", "BAMLH0A0HYM2", "高收益債", "#ff7043"),
          ("ig", "BAMLC0A0CM", "投資級", "#42a5f5"),
          ("bbb", "BAMLC0A4CBBB", "BBB 級", "#ab47bc"),
          ("ccc", "BAMLH0A3HYC", "CCC 級以下", "#ffd600")]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "credit_spread.json")
TTL = 6 * 3600
_lock = threading.Lock()


def _fetch(sid):
    r = requests.get(URL, params={"id": sid, "cosd": "1997-01-01"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    if "csv" not in ct and "text" not in ct:          # 只收純文字 CSV
        raise ValueError(f"FRED 回傳格式不對：{ct}")
    if len(r.content) > 5_000_000:
        raise ValueError("FRED 回傳檔案過大")
    out = []
    for i, line in enumerate(io.StringIO(r.text)):
        p = line.strip().split(",")
        if i == 0 or len(p) != 2:
            continue
        try:
            d = dt.date.fromisoformat(p[0]).isoformat()
            v = float(p[1])
        except ValueError:                             # 假日是 "."
            continue
        out.append([d, round(v, 2)])
    if not out:
        raise ValueError(f"{sid} 沒有資料")
    return out


def _pct_rank(vals, v):
    return round(sum(1 for x in vals if x <= v) / len(vals) * 100, 1) if vals else None


def _chg(rows, n):
    return round(rows[-1][1] - rows[-1 - n][1], 2) if len(rows) > n else None


def _stats(rows):
    vals = [v for _, v in rows]
    last = rows[-1]
    y1 = [v for d, v in rows if d >= (dt.date.fromisoformat(last[0]) - dt.timedelta(days=365)).isoformat()]
    lo = min(rows, key=lambda r: r[1])
    hi = max(rows, key=lambda r: r[1])
    return {"date": last[0], "last": last[1], "prev": rows[-2][1] if len(rows) > 1 else None,
            "d1": _chg(rows, 1), "w1": _chg(rows, 5), "m1": _chg(rows, 21), "m3": _chg(rows, 63), "y1": _chg(rows, 252),
            "ma20": round(sum(vals[-20:]) / min(20, len(vals)), 2), "ma60": round(sum(vals[-60:]) / min(60, len(vals)), 2),
            "y1_lo": min(y1), "y1_hi": max(y1), "pct_all": _pct_rank(vals, last[1]), "pct_1y": _pct_rank(y1, last[1]),
            "lo": lo, "hi": hi, "from": rows[0][0]}


def _hy_view(s):
    v = s["last"]
    if v < 3:
        lvl, txt = "極低（市場很樂觀）", "利差在 3% 以下＝資金搶風險資產，股市通常偏多，但也代表過度樂觀，回升時容易有修正"
    elif v < 4:
        lvl, txt = "正常偏低", "信用市場穩定，沒有系統性壓力"
    elif v < 5:
        lvl, txt = "警戒", "利差上到 4~5%，市場開始擔心景氣／違約，股市波動通常變大"
    elif v < 7:
        lvl, txt = "壓力", "利差 5~7%，信用緊縮，過去多出現在股市明顯修正期"
    else:
        lvl, txt = "危機", "利差 7% 以上，過去只出現在 2008 金融海嘯、2020 疫情等危機"
    notes = [f"高收益債利差 {v:.2f}%：<b>{lvl}</b>，{txt}"]
    if s["m1"] is not None and s["m1"] >= 0.75:
        notes.append(f"一個月急升 {s['m1']:+.2f} 個百分點 → 信用市場在緊張，注意股市風險")
    elif s["m1"] is not None and s["m1"] >= 0.3:
        notes.append(f"一個月上升 {s['m1']:+.2f} 個百分點，風險偏好在降溫")
    elif s["m1"] is not None and s["m1"] <= -0.3:
        notes.append(f"一個月收斂 {s['m1']:+.2f} 個百分點，風險偏好回升")
    if s["last"] > s["ma20"] > s["ma60"]:
        notes.append("目前在 20 日／60 日均線之上且均線向上排列＝利差擴大趨勢")
    elif s["last"] < s["ma20"] < s["ma60"]:
        notes.append("目前在 20 日／60 日均線之下＝利差收斂趨勢")
    return lvl, notes


def get(force=False):
    with _lock:
        cache = None
        if os.path.exists(PATH):
            try:
                with open(PATH, encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                cache = None
        fresh = cache and (dt.datetime.now() - dt.datetime.fromisoformat(cache["fetched"])).total_seconds() < TTL
        if fresh and not force:
            return cache
        out = {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "source": "FRED（ICE BofA OAS）", "series": {}, "errors": {}}
        for key, sid, name, color in SERIES:
            try:
                rows = _fetch(sid)
                out["series"][key] = {"id": sid, "name": name, "color": color, "rows": rows, "stats": _stats(rows)}
            except Exception as e:
                out["errors"][key] = f"{type(e).__name__}: {e}"
                if cache and key in cache.get("series", {}):            # 抓失敗就沿用舊的
                    out["series"][key] = cache["series"][key]
        if not out["series"]:
            if cache:
                cache["errors"] = out["errors"]
                return cache
            return {"error": "抓不到 FRED 資料：" + "；".join(out["errors"].values())}
        hy = out["series"].get("hy")
        if hy:
            out["level"], out["notes"] = _hy_view(hy["stats"])
            ig = out["series"].get("ig")
            if ig:
                m = dict(ig["rows"])
                out["series"]["gap"] = {"id": "HY-IG", "name": "高收益－投資級", "color": "#26a69a",
                                        "rows": [[d, round(v - m[d], 2)] for d, v in hy["rows"] if d in m]}
                out["series"]["gap"]["stats"] = _stats(out["series"]["gap"]["rows"])
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, PATH)
        return out
