"""盤中即時：族群多空（含資金淨流向）、量能激增股、周轉率排行。
  資料：證交所 MIS 盤中即時報價（上市＋上櫃，免費、約 5 秒延遲）；
        MIS 抓不到時，如果設定裡有填 FinMind token，改用 FinMind 即時快照（需 FinMind 付費方案）。
  族群名單存在 data/live_groups.json，可以自己增減（沒有這個檔案會用下面的預設名單建立）。
  資金淨流向是估計值：成交金額 ×（收盤在當日高低區間的位置，-1~+1），收在最高 = 全部算流入、收在最低 = 全部算流出。
"""
import datetime as dt
import json
import os

import pandas as pd
import requests

import settings
from data import HEADERS, _num, connect
from settings import BASE
from warrants import _mis

GROUPS_PATH = os.path.join(BASE, "data", "live_groups.json")
LAST_PATH = os.path.join(BASE, "data", "live_last.json")

DEFAULT_GROUPS = [
    {"name": "CCL銅箔基板", "codes": ["2383", "6274", "6213", "6672", "8358"]},
    {"name": "PCB", "codes": ["2368", "4577", "6191", "2313", "3044", "3715", "8155", "2367", "5469", "8213", "2355"]},
    {"name": "玻纖布", "codes": ["1815", "1802", "5340", "5475", "1303"]},
    {"name": "載板", "codes": ["3037", "3189", "4958", "8046"]},
    {"name": "記憶體", "codes": ["2408", "2344", "6770", "8299", "2337", "3260", "4967", "8271", "2451"]},
    {"name": "光通訊", "codes": ["3081", "2455", "3105", "3450", "3163", "4979", "3363", "6442", "4977", "4908"]},
    {"name": "封測", "codes": ["2449", "3711", "6239", "6257", "6147", "8150", "3264"]},
    {"name": "被動元件", "codes": ["2327", "2492", "3026", "2472", "2478", "6173", "2375"]},
    {"name": "功率元件", "codes": ["8261", "2481", "5425", "5299", "6435", "3317", "2342", "8255"]},
    {"name": "矽晶圓", "codes": ["6488", "6182", "3532", "5483"]},
    {"name": "晶圓代工", "codes": ["2330", "2303", "5347"]},
    {"name": "IC設計", "codes": ["2454", "2379", "3034", "3443", "3661", "3035", "5274", "5269", "4966"]},
    {"name": "AI伺服器", "codes": ["2317", "2382", "3231", "6669", "2356", "2376", "2357", "3706"]},
    {"name": "散熱", "codes": ["3017", "3324", "3653", "2421", "6230", "3483"]},
    {"name": "機殼滑軌", "codes": ["2059", "8210", "3013"]},
    {"name": "網通", "codes": ["2345", "6285", "5388", "3380"]},
    {"name": "重電", "codes": ["1519", "1503", "1513", "1514", "2371"]},
    {"name": "航運", "codes": ["2603", "2609", "2615", "2618", "2610"]},
    {"name": "金融", "codes": ["2881", "2882", "2891", "2886", "2885"]},
]

# 一天成交量在各時間點大約累積到幾成（台股盤中量是 U 型：開盤、收盤集合競價量大）
VOL_CURVE = [("09:00", 0.0), ("09:05", 0.08), ("09:30", 0.25), ("10:00", 0.36), ("10:30", 0.45), ("11:00", 0.52),
             ("11:30", 0.58), ("12:00", 0.63), ("12:30", 0.69), ("13:00", 0.77), ("13:25", 0.86), ("13:30", 1.0)]


def load_groups():
    try:
        with open(GROUPS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        with open(GROUPS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_GROUPS, f, ensure_ascii=False, indent=2)
        return DEFAULT_GROUPS


def load_last():
    try:
        with open(LAST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def vol_frac(hm):
    """hm = "10:15" → 這個時間點大約已經成交全天量的幾成"""
    if hm >= "13:30":
        return 1.0
    for (t0, f0), (t1, f1) in zip(VOL_CURVE, VOL_CURVE[1:]):
        if t0 <= hm < t1:
            m = lambda t: int(t[:2]) * 60 + int(t[3:])
            return f0 + (f1 - f0) * (m(hm) - m(t0)) / (m(t1) - m(t0))
    return 0.05


def _history(con, today):
    """前一個交易日以前的 20 天：均量、均線、20 日高點、昨高昨低（只看普通股）"""
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM prices WHERE date < ? ORDER BY date DESC LIMIT 20", (today,))]
    if not days:
        return pd.DataFrame(), None
    h = pd.read_sql("SELECT code, date, market, name, high, low, close, volume FROM prices WHERE date >= ? AND date < ? "
                    "AND length(code)=4 AND substr(code,1,1)!='0' ORDER BY code, date", con, params=(days[-1], today))
    g = h.groupby("code")
    last = g.tail(1).set_index("code")
    out = pd.DataFrame({
        "market": last["market"], "name": last["name"], "prev_close": last["close"], "prev_high": last["high"], "prev_low": last["low"],
        "avg5": g["volume"].apply(lambda s: s.tail(5).mean()) / 1000,     # 張
        "ma5": g["close"].apply(lambda s: s.tail(5).mean()),
        "ma20": g["close"].apply(lambda s: s.mean() if len(s) >= 20 else None),
        "high20": g["high"].max(),
    })
    out = out[last["date"] == days[0]]     # 前一個交易日沒成交（停牌、下市）的不要
    return out, days[0]


def _first(s):
    """MIS 的五檔報價格式 '101.5_101_100.5_' → 101.5"""
    return _num(str(s or "").split("_")[0]) or None


def _quotes_mis(hist):
    sym = [f"{'otc' if m == '上櫃' else 'tse'}_{c}.tw" for c, m in zip(hist.index, hist["market"])]
    raw = _mis(sym + ["tse_t00.tw", "otc_o00.tw"])
    q, idx = [], {}
    for x in raw:
        c = x.get("c")
        z = _num(x.get("z")) or _num(x.get("pz")) or _first(x.get("b")) or _first(x.get("a"))
        y = _num(x.get("y"))
        if c in ("t00", "o00"):
            if z and y:
                idx[c] = {"price": z, "chg": round((z / y - 1) * 100, 2)}
            continue
        if not z or not y:
            continue
        q.append({"code": c, "z": z, "y": y, "o": _num(x.get("o")) or z, "h": _num(x.get("h")) or z,
                  "l": _num(x.get("l")) or z, "v": _num(x.get("v")) or 0, "t": x.get("t", ""), "d": x.get("d", "")})
    return pd.DataFrame(q), idx


def _quotes_finmind(token):
    r = requests.get("https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot",
                     params={"token": token}, headers=HEADERS, timeout=30)
    j = r.json()
    if j.get("status") not in (200, None) or not j.get("data"):
        raise RuntimeError(j.get("msg") or "FinMind 沒有回傳資料")
    q = []
    for x in j["data"]:
        z, chgp = x.get("close"), x.get("change_price") or 0
        if not z:
            continue
        ts = str(x.get("date", ""))
        q.append({"code": str(x["stock_id"]), "z": z, "y": z - chgp, "o": x.get("open") or z, "h": x.get("high") or z,
                  "l": x.get("low") or z, "v": x.get("total_volume") or 0,
                  "t": ts[11:19], "d": ts[:10].replace("-", "")})
    return pd.DataFrame(q), {}


def _r(v, d=2):
    return None if v is None or pd.isna(v) else round(float(v), d)


def compute(progress=None):
    progress = {} if progress is None else progress
    p = settings.load()
    min_price = p.get("min_price", 10) or 10
    today = dt.date.today().isoformat()
    con = connect()
    try:
        hist, prev_day = _history(con, today)
    finally:
        con.close()
    if hist.empty:
        return {"error": "資料庫裡還沒有歷史行情，請先按「更新資料」"}

    progress["msg"] = f"抓盤中即時報價（{len(hist)} 檔，約 30 秒）…"
    source, err = "證交所 MIS 即時報價", None
    try:
        q, idx = _quotes_mis(hist)
    except Exception as e:
        q, idx, err = pd.DataFrame(), {}, str(e)
    if q.empty and p.get("finmind_token"):
        progress["msg"] = "MIS 抓不到，改用 FinMind…"
        try:
            q, idx = _quotes_finmind(p["finmind_token"])
            source = "FinMind 即時快照"
        except Exception as e:
            err = f"FinMind：{e}"
    if q.empty:
        return {"error": "抓不到即時報價" + (f"（{err}）" if err else "（可能不是交易時間或連線問題）")}

    progress["msg"] = "計算中…"
    d = q.drop_duplicates("code").set_index("code").join(hist, how="inner")
    d = d[d["z"] > 0]
    qd = d["d"].mode().iloc[0] if len(d) else ""
    qt = d["t"].max() if len(d) else ""
    live_today = qd == today.replace("-", "")
    frac = vol_frac(qt[:5]) if live_today and qt else 1.0
    frac = max(frac, 0.05)

    comp = {}
    try:
        import notice
        comp = notice.load_meta().get("company", {})
    except Exception:
        pass
    from chips import IND
    d["ind"] = [IND.get(comp.get(c, {}).get("ind", ""), "其他") for c in d.index]
    d["shares"] = [comp.get(c, {}).get("shares") for c in d.index]

    d["chg"] = (d["z"] / d["y"] - 1) * 100
    rng = d["h"] - d["l"]
    sign = (d["z"] > d["y"]).astype(float) - (d["z"] < d["y"]).astype(float)
    d["pos"] = ((d["z"] - d["l"]) / rng).where(rng > 0, (sign + 1) / 2)       # 0 = 在最低、1 = 在最高
    d["amt"] = d["v"] * 1000 * (d["h"] + d["l"] + d["z"]) / 3 / 1e8           # 億
    d["flow"] = d["amt"] * (d["pos"] * 2 - 1)
    d["est"] = d["v"] / frac                                                  # 估計全天量（張）
    d["vr"] = (d["est"] / d["avg5"]).where(d["avg5"] > 0)
    d["turn"] = (d["v"] * 1000 / d["shares"] * 100).where(d["shares"].fillna(0) > 0)
    d["est_turn"] = d["turn"] / frac

    def stock_row(c, r, extra=()):
        row = {"code": c, "name": r["name"], "ind": r["ind"], "price": _r(r["z"]), "chg": _r(r["chg"]), "pos": _r(r["pos"]),
               "lots": int(r["v"]), "amt": _r(r["amt"]), "flow": _r(r["flow"]), "vr": _r(r["vr"])}
        for k in extra:
            row[k] = _r(r[k])
        return row

    def group_stats(name, sub, with_members=True):
        sub = sub.sort_values("chg", ascending=False)
        amt = sub["amt"].sum()
        wchg = (sub["chg"] * sub["amt"]).sum() / amt if amt > 0 else sub["chg"].mean()
        avg5 = sub["avg5"].sum()
        g = {"name": name, "n": int(len(sub)), "chg": _r(sub["chg"].mean()), "wchg": _r(wchg),
             "up": int((sub["chg"] > 0).sum()), "down": int((sub["chg"] < 0).sum()),
             "amt": _r(amt), "flow": _r(sub["flow"].sum()), "vr": _r(sub["est"].sum() / avg5 if avg5 > 0 else None),
             "lead": [{"code": c, "name": r["name"], "chg": _r(r["chg"])} for c, r in sub.head(3).iterrows()],
             "lag": [{"code": c, "name": r["name"], "chg": _r(r["chg"])} for c, r in sub.tail(3)[::-1].iterrows()]}
        if with_members:
            g["members"] = [stock_row(c, r) for c, r in sub.iterrows()]
        return g

    # 族群（自訂名單）
    groups = []
    for grp in load_groups():
        sub = d[d.index.isin([str(c) for c in grp.get("codes", [])])]
        if len(sub):
            groups.append(group_stats(grp["name"], sub))
    groups.sort(key=lambda g: g["wchg"] or 0, reverse=True)

    # 產業別（證交所／櫃買分類，全部普通股）
    inds = [group_stats(n, sub) for n, sub in d[d["amt"] > 0].groupby("ind") if len(sub) >= 3]
    inds.sort(key=lambda g: g["wchg"] or 0, reverse=True)

    # 個股強弱：股價 ≥ 最低股價、估計全天量 ≥ 1000 張，跟大盤比
    mkt = idx.get("t00", {}).get("chg")
    act = d[(d["z"] >= min_price) & (d["est"] >= 1000)].copy()
    base = mkt if mkt is not None else d["chg"].median()
    act["rel"] = act["chg"] - base
    strong = [stock_row(c, r, ("rel",)) for c, r in act.sort_values("chg", ascending=False).head(30).iterrows()]
    weak = [stock_row(c, r, ("rel",)) for c, r in act.sort_values("chg").head(30).iterrows()]

    # 量能激增：排除雞蛋水餃股（股價 < 最低股價）、估計全天量 ≥ 1000 張、量比 ≥ 2
    s = d[(d["z"] >= min_price) & (d["est"] >= 1000) & (d["vr"] >= 2)].copy()
    lim_up = s["chg"] >= 9.5
    s["tags"] = [[t for t, ok in (("漲停", lu), ("突破昨高", r["z"] > r["prev_high"]), ("創20日高", r["h"] >= r["high20"]),
                                  ("站上均線", r["z"] > r["ma5"] and (pd.isna(r["ma20"]) or r["ma5"] > r["ma20"])),
                                  ("收在高檔", r["pos"] >= 0.8)) if ok]
                 for (c, r), lu in zip(s.iterrows(), lim_up)]
    # 動能分數：漲幅 × 量比（量比最多算到 5 倍），再依技術條件加分
    s["score"] = s["chg"] * s["vr"].clip(upper=5) + s["tags"].map(len) * 2
    up = s[(s["chg"] >= 2) & (s["pos"] >= 0.6)].sort_values("score", ascending=False).head(40)
    surge_up = [{**stock_row(c, r, ("est", "avg5", "score")), "tags": r["tags"]} for c, r in up.iterrows()]
    dn = s[(s["chg"] <= -2) & (s["pos"] <= 0.4)].copy()
    dn["tags"] = [[t for t, ok in (("跌停", r["chg"] <= -9.5), ("跌破昨低", r["z"] < r["prev_low"]),
                                   ("收在低檔", r["pos"] <= 0.2), ("跌破均線", r["z"] < r["ma5"])) if ok] for c, r in dn.iterrows()]
    dn["score"] = dn["chg"] * dn["vr"].clip(upper=5) - dn["tags"].map(len) * 2
    surge_dn = [{**stock_row(c, r, ("est", "avg5", "score")), "tags": r["tags"]}
                for c, r in dn.sort_values("score").head(30).iterrows()]

    # 周轉率前 20（普通股）
    t = d[d["turn"].notna()].sort_values("turn", ascending=False).head(20)
    turnover = [stock_row(c, r, ("turn", "est_turn")) for c, r in t.iterrows()]

    res = {"time": f"{qd[:4]}-{qd[4:6]}-{qd[6:]} {qt}" if qd else qt, "live": live_today and frac < 1, "frac": _r(frac),
           "source": source, "prev_day": prev_day, "min_price": min_price,
           "market": {"taiex": idx.get("t00"), "otc": idx.get("o00"), "n": int(len(d)),
                      "up": int((d["chg"] > 0).sum()), "down": int((d["chg"] < 0).sum()),
                      "amt": _r(d["amt"].sum(), 0), "flow": _r(d["flow"].sum(), 1)},
           "groups": groups, "inds": inds, "strong": strong, "weak": weak,
           "surge_up": surge_up, "surge_dn": surge_dn, "turnover": turnover,
           "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(LAST_PATH, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res
