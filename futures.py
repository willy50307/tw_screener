"""期貨看盤頁：全部期貨合約的即時行情表。
全部合約用期交所 MIS（mis.taifex.com.tw，免費、約幾秒延遲、有買賣價和未平倉）；
昨量、昨日未平倉用期交所「期貨每日交易行情」下載（前一個交易日，一般盤）；
有群益報價的合約（目前點開的那檔、近月指數期貨）用群益的即時數字蓋過去。"""
import csv
import datetime as dt
import io
import json
import os
import re
import threading
import time

import requests

import settings
from data import HEADERS

MIS = "https://mis.taifex.com.tw/futures/api/getQuoteList"
# MIS 的 KindID：1 指數、2 永續指數、3 海外指數、4 股票、5 ETF、6 匯率、7 商品、8 小型股票
KIND = {"1": "index", "2": "index", "3": "index", "4": "stock", "5": "stock", "8": "mini", "6": "other", "7": "other"}
# MIS 代碼前 3 碼 -> 期交所下載檔的「契約」欄（股票期貨兩邊一樣，只有這幾個指數期貨不一樣）
CSV_CODE = {"TXF": "TX", "MXF": "MTX", "EXF": "TE", "FXF": "TF", "MX1": "MTX", "MX2": "MTX", "MX4": "MTX", "MX5": "MTX",
            "TX1": "TX", "TX2": "TX", "TX4": "TX", "TX5": "TX"}
MONTH = "ABCDEFGHIJKL"

_cache = {"t": 0, "rows": [], "session": None}
_prev = {"date": None, "rows": {}, "t": 0, "got": None}
_last = {}   # (KindID, 盤別) -> (抓的時間, 清單)
_cool = {"until": 0, "fails": 0}
_groups_cache = {}
TTL = 10     # 全部合約幾秒更新一次（期交所一次要抓 8 類，太頻繁會被擋）
_lock = threading.Lock()


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _session():
    """夜盤 15:00～隔天 05:00；早上開盤前（05:00～08:45）還是看夜盤最後的價格"""
    t = dt.datetime.now().time()
    return "1" if t >= dt.time(14, 50) or t < dt.time(8, 30) else "0"


def _ym(sym):
    """TXFK6 -> ('TXF', '202611')；週契約 MX4J6 -> ('MX4', '202610W4')"""
    p, m, y = sym[:3], sym[3], sym[4]
    if m not in MONTH or not y.isdigit():
        return p, ""
    year = dt.date.today().year // 10 * 10 + int(y)
    if year < dt.date.today().year - 1:
        year += 10
    ym = f"{year}{MONTH.index(m) + 1:02d}"
    if p[:2] in ("MX", "TX") and p[2].isdigit():
        ym += "W" + p[2]
    return p, ym


def _prev_day():
    """前一個交易日的成交量、未平倉（一般盤）：{(契約, 到期月份): (量, 未平倉)}；一天只抓一次"""
    today = dt.date.today()
    if _prev["date"] and _prev["got"] == today and _prev["rows"]:
        return _prev
    if time.time() - _prev["t"] < 300 and _prev["date"]:
        return _prev
    _prev["t"] = time.time()
    d = today - dt.timedelta(days=1)
    if dt.datetime.now().time() < dt.time(5, 0):
        d -= dt.timedelta(days=1)      # 半夜還是前一天的夜盤
    for _ in range(10):
        if d.weekday() < 5:
            try:
                r = requests.post("https://www.taifex.com.tw/cht/3/futDataDown", headers=HEADERS, timeout=60,
                                  data={"down_type": "1", "commodity_id": "all", "commodity_id2": "",
                                        "queryStartDate": d.strftime("%Y/%m/%d"), "queryEndDate": d.strftime("%Y/%m/%d")})
                rows = [x for x in csv.reader(io.StringIO(r.content.decode("big5", errors="replace"))) if len(x) > 17 and x[0][:4].isdigit()]
            except Exception as e:
                print("期貨昨日行情抓取失敗", e)
                return _prev
            if rows:
                out = {}
                for x in rows:
                    if x[17].strip() != "一般":
                        continue
                    out[(x[1].strip(), x[2].strip())] = (_f(x[9]), _f(x[11]))
                _prev.update(date=d.isoformat(), rows=out, got=today)
                return _prev
        d -= dt.timedelta(days=1)
    return _prev


def _mis(kind, session):
    """一類合約的行情；同時打太多次期交所會回空白，失敗就重試、再不行沿用上一次的"""
    key = (kind, session)
    old = _last.get(key, (0, []))
    if session == "0" and _session() == "1" and time.time() - old[0] < 600:
        return kind, old[1], session      # 夜盤時日盤資料不會再變，10 分鐘抓一次就好
    if time.time() < _cool["until"]:
        return kind, old[1], session
    try:
        r = requests.post(MIS, json={"MarketType": session, "SymbolType": "F", "KindID": kind, "CID": "", "ExpireMonth": "",
                                     "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}, timeout=15)
        lst = r.json().get("RtData", {}).get("QuoteList", [])
        _last[key] = (time.time(), lst)
        _cool["fails"] = 0
        return kind, lst, session
    except Exception:
        # 期交所回錯誤（太頻繁會回 520）：先停一下再抓，連續失敗就停更久（最多 5 分鐘），這段時間沿用上一次的資料
        _cool["fails"] += 1
        _cool["until"] = time.time() + min(300, 30 * _cool["fails"])
        return kind, old[1], session


def table():
    """全部期貨合約（不含現貨、價差單）。快取 3 秒，多個分頁同時開也只抓一次"""
    with _lock:
        sess = _session()
        if time.time() - _cache["t"] < TTL and _cache["session"] == sess:
            return _cache
        prev = _prev_day()
        jobs = [(k, "0") for k in KIND] + ([(k, "1") for k in KIND] if sess == "1" else [])
        res = [_mis(*a) for a in jobs]   # 一個一個抓，不要同時打
        night = {}   # 夜盤有交易的合約：蓋掉日盤的價格（未平倉夜盤沒有，留日盤收盤後的）
        for kind, lst, s in res:
            if s == "1":
                for x in lst:
                    if x.get("SymbolID", "").endswith("-M") and _f(x.get("CLastPrice")):
                        night[x["SymbolID"][:-2]] = x
        rows = []
        for kind, lst, s in res:
            if s != "0":
                continue
            for x in lst:
                sid = x.get("SymbolID", "")
                if not sid.endswith("-F") or "/" in sid:
                    continue
                sym = sid[:-2]
                p, ym = _ym(sym)
                yv, yoi = prev["rows"].get((CSV_CODE.get(p, p), ym), (None, None))
                oi = _f(x.get("OpenInterest"))
                n = night.get(sym)
                q = n or x
                rows.append({"sym": sym, "name": x.get("DispCName", ""), "spot": x.get("SpotID", ""), "grp": KIND[kind], "ym": ym,
                             "z": _f(q.get("CLastPrice")) or None, "y": _f(q.get("CRefPrice")),
                             "bid": _f(q.get("CBestBidPrice")) or None, "ask": _f(q.get("CBestAskPrice")) or None,
                             "o": _f(q.get("COpenPrice")) or None, "h": _f(q.get("CHighPrice")) or None, "l": _f(q.get("CLowPrice")) or None,
                             "v": _f(q.get("CTotalVolume")) or 0, "yv": _f(x.get("CTotalVolume")) if n else yv, "oi": oi, "yoi": yoi,
                             "t": (q.get("CTime") or "").rjust(6, "0"), "night": bool(n), "day_only": sess == "1" and not n})
        src = "mis"
        if rows:
            _save_groups(rows)
        else:   # 期交所 MIS 掛了：用群益的期貨商品檔＋昨天的量、未平倉列出合約，價格等群益報價蓋上去
            rows, src = _fallback(prev, sess), "fallback"
        # 同一個商品，到期月份最近的那個 = 近月
        seen = set()
        for r in sorted(rows, key=lambda r: (r["sym"][:3], r["ym"])):
            r["near"] = r["sym"][:3] not in seen
            seen.add(r["sym"][:3])
        _cache.update(t=time.time(), rows=rows, session=sess, prev_date=prev.get("date"), src=src)
        return _cache


# ---------- 期交所 MIS 抓不到時的備案 ----------
GRP_PATH = os.path.join(settings.BASE, "data", "fut_groups.json")
INDEX_PRE = {"TXF", "MXF", "TMF", "EXF", "FXF", "GTF", "BTF", "E4F", "G2F", "M1F", "SHF", "SOF", "XIF", "ZEF", "ZFF",
             "MX1", "MX2", "MX4", "MX5", "F1F", "SPF", "SXF", "TJF", "UDF", "UNF"}
OTHER_PRE = {"RHF", "RTF", "XAF", "XBF", "XEF", "XJF", "BRF", "GDF", "TGF"}


def _save_groups(rows):
    g = {r["sym"][:3]: r["grp"] for r in rows}
    if g != _groups_cache.get("g"):
        _groups_cache["g"] = g
        try:
            with open(GRP_PATH, "w", encoding="utf-8") as f:
                json.dump(g, f)
        except OSError:
            pass


def _load_groups():
    if "g" not in _groups_cache:
        try:
            with open(GRP_PATH, encoding="utf-8") as f:
                _groups_cache["g"] = json.load(f)
        except (OSError, ValueError):
            _groups_cache["g"] = {}
    return _groups_cache["g"]


def _fallback(prev, sess):
    import capital
    groups = _load_groups()
    rows = []
    for oid, code in list(capital._flist.items()):
        if len(oid) != 5 or "/" in oid:
            continue
        p, ym = _ym(oid)
        if not ym:
            continue
        hit = prev["rows"].get((CSV_CODE.get(p, p), ym))
        if not hit:       # 昨天沒有這個合約（過期或不是一般月份合約）
            continue
        name = capital._names.get(code, oid)
        grp = groups.get(p) or ("index" if p in INDEX_PRE else "other" if p in OTHER_PRE else "mini" if name.startswith("小") else "stock")
        rows.append({"sym": oid, "name": name, "spot": "", "grp": grp, "ym": ym, "z": None, "y": None, "bid": None, "ask": None,
                     "o": None, "h": None, "l": None, "v": 0, "yv": hit[0], "oi": None, "yoi": hit[1], "t": "",
                     "night": False, "day_only": False})
    return rows


# ---------- 個股K 的台指期(TX)：接上還沒進資料庫的夜盤 ----------
_txl = {"t": 0, "v": None}


def _wd_back(d, include):
    """d 當天（include）或之前最近的平日"""
    if not include:
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _wd_next(d):
    d += dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def tx_live():
    """台指期近月目前的行情（期交所 MIS，免費）。夜盤 15:00～隔天 05:00 歸屬下一個交易日（期交所規定），
    所以夜盤這根的日期是下一個交易日；15:00 後資料庫還沒有今天日盤時也一併給今天日盤。
    回傳 {"day": (日期, 開, 高, 低, 收, 口) 或 None, "night": (...) 或 None}；不是夜盤時段回 None。
    國定假日沒有排除（日期可能標成假日，隔天期交所資料下載後就會被正確資料取代）"""
    now = dt.datetime.now()
    if _session() != "1" or dt.time(14, 50) <= now.time() < dt.time(15, 0):
        return None
    if time.time() - _txl["t"] < 20:
        return _txl["v"]
    _txl["t"] = time.time()
    with _lock:
        day = _mis("1", "0")[1]
        night = _mis("1", "1")[1]
    syms = [x["SymbolID"][:-2] for x in day if re.fullmatch(r"TXF[A-L]\d-F", x.get("SymbolID", ""))]
    if not syms:
        _txl["v"] = None
        return None
    near = min(syms, key=lambda s: _ym(s)[1])
    anchor = _wd_back(now.date(), now.time() >= dt.time(15, 0))   # 今天日盤（下午）／昨天日盤（半夜、清晨）
    target = _wd_next(anchor)

    def bar(lst, sid, d):
        x = next((x for x in lst if x.get("SymbolID") == sid), None)
        o, h, l, c, v = (_f(x.get(k)) if x else None for k in ("COpenPrice", "CHighPrice", "CLowPrice", "CLastPrice", "CTotalVolume"))
        return (d.isoformat(), o, h, l, c, v or 0) if o and h and l and c else None

    _txl["v"] = {"day": bar(day, near + "-F", anchor) if anchor == now.date() else None,
                 "night": bar(night, near + "-M", target)}
    return _txl["v"]
