"""處置股出關日（R0）紅K/黑K：各條件的命中率＋時間切分（前半找、後半驗）。
唯讀 data/stocks.db，只寫 research/out/disp_release.json。
定義：
  處置期間 = disposal start~end（end 依 meta closures 順延，跟 notice.py 一樣）
  Dlast = 處置最後一根K棒；R0 = 出關日（下一根K棒）
  R0 紅K = 收 > 開；R0 收漲 = 收 > Dlast 收
  外資券商 = 分點名稱有 美商/摩根/新加坡商/港商/花旗/美林/麥格理/法銀/匯豐/瑞銀/大和/野村/德意志/瑞士
  券商買賣超只看買超/賣超前 15 名（MoneyDJ，先跑 disp_release_fetch.py 補抓；只有新制 5 天處置）
只取普通股：代號 4 碼、首碼 1~9。
用法：python research/disp_release.py [代號 ...]   → 另外印出這幾檔「最近一次處置」的條件
"""
import json, os, re, sqlite3, sys
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import notice  # noqa: E402

DB = os.path.join(BASE, "data", "stocks.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "disp_release.json")
FOREIGN = re.compile(r"美商|摩根|新加坡商|港商|花旗|美林|麥格理|法銀|匯豐|瑞銀|大和|野村|德意志|瑞士")
SPLIT = "2026-09-15"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
meta = notice.load_meta()
closures = meta.get("closures", [])
cal = notice.Calendar([], meta.get("holidays", []) + closures)
dis = pd.read_sql("SELECT code,name,ann,start,end,measure FROM disposal", con)
dis = dis[dis.code.str.fullmatch(r"[1-9]\d{3}")].copy()
dis["end"] = [cal.next_days(r.end, n)[-1] if (n := sum(r.ann < c and r.start <= c <= r.end for c in closures)) else r.end
              for r in dis.itertuples()]
dis = dis[dis.start >= "2026-04-23"].drop_duplicates(["code", "start", "end"])
codes = tuple(dis.code.unique())
px = pd.read_sql(f"SELECT code,date,open,high,low,close,volume FROM prices WHERE date>='2026-04-01' AND code IN {codes}", con)
px = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
BRK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "disp_release_broker.json")
brk = json.load(open(BRK, encoding="utf-8")) if os.path.exists(BRK) else {}


def fx_dj(code, start, tag):
    """MoneyDJ 補抓的外資券商合計買賣超（張）；沒資料回 None"""
    rows = brk.get(f"{code}|{start}|{tag}")
    return None if rows is None else sum(x["net"] for x in rows if FOREIGN.search(x["branch"]))


inst = pd.read_sql(f"SELECT code,date,fi,it FROM inst WHERE date>='2026-04-01' AND code IN {codes}", con).set_index(["code", "date"])


def events():
    rows = []
    for r in dis.itertuples():
        g = px.get(r.code)
        if g is None:
            continue
        inside = g.index[(g.date >= r.start) & (g.date <= r.end)]
        if len(inside) < 3:
            continue
        s, e = inside[0], inside[-1]
        if s == 0 or e + 1 >= len(g):
            ev = None
        else:
            ev = g.loc[e + 1]
        D, P = g.loc[e], g.loc[s - 1]
        lots = D.volume / 1000

        fx_last, fx_all = fx_dj(r.code, r.start, "last"), fx_dj(r.code, r.start, "all")
        vol_all = g.loc[s:e, "volume"].sum() / 1000

        def side(v, base):
            return "缺" if v is None else "買" if v >= 0.003 * base else "賣" if v <= -0.003 * base else "無"
        it_all = sum(inst["it"].get((r.code, d), 0.0) or 0 for d in g.loc[s:e, "date"])
        rng = D.high - D.low
        rows.append({
            "code": r.code, "name": r.name, "start": r.start, "end": r.end,
            "rule": "new" if r.start >= "2026-08-10" else "old",
            "r0": None if ev is None else ev.date,
            "red": None if ev is None else bool(ev.close > ev.open),
            "up": None if ev is None else bool(ev.close > D.close),
            "oc": None if ev is None else round((ev.close / ev.open - 1) * 100, 2),
            "cc": None if ev is None else round((ev.close / D.close - 1) * 100, 2),
            "last_red": bool(D.close > D.open), "last_black": bool(D.close < D.open),
            "ret": round((D.close / P.close - 1) * 100, 2),
            "pos": round((D.close - D.low) / rng, 2) if rng > 0 else 0.5,
            "fx_last": side(fx_last, lots), "fx_all": side(fx_all, vol_all),
            "fx_last_n": fx_last, "fx_all_n": fx_all, "lots": round(lots),
            "it_buy": bool(it_all > 0),
        })
    return pd.DataFrame(rows)


CONDS = {
    "全部": lambda d: d.index == d.index,
    "最後一天外資券商買": lambda d: d.fx_last == "買",
    "最後一天外資券商賣": lambda d: d.fx_last == "賣",
    "最後一天外資券商沒進出": lambda d: d.fx_last == "無",
    "處置5天外資券商買": lambda d: d.fx_all == "買",
    "處置5天外資券商賣": lambda d: d.fx_all == "賣",
    "處置5天外資券商沒進出": lambda d: d.fx_all == "無",
    "最後一天黑K＋外資券商買": lambda d: d.last_black & (d.fx_last == "買"),
    "最後一天黑K＋外資券商賣/沒進出": lambda d: d.last_black & (d.fx_last != "買"),
    "最後一天紅K": lambda d: d.last_red,
    "最後一天黑K": lambda d: d.last_black,
    "收在當天低檔（位置<0.25）": lambda d: d.pos < 0.25,
    "收在當天高檔（位置>0.75）": lambda d: d.pos > 0.75,
    "處置期間漲>10%": lambda d: d.ret > 10,
    "處置期間跌>10%": lambda d: d.ret < -10,
    "處置期間-10%~+10%": lambda d: d.ret.between(-10, 10),
    "投信處置期間買超": lambda d: d.it_buy,
}


def stat(d):
    d = d[d.red.notna()]
    if not len(d):
        return {"n": 0}
    return {"n": int(len(d)), "red": round(d.red.mean() * 100, 1), "up": round(d.up.mean() * 100, 1),
            "oc": round(d.oc.mean(), 2), "cc": round(d.cc.mean(), 2)}


if __name__ == "__main__":
    ev = events()
    res = {}
    for rule in ("new", "all"):
        e = ev if rule == "all" else ev[ev.rule == "new"]
        res[rule] = {k: {"全期": stat(e[f(e)]), "前半": stat(e[f(e) & (e.r0 < SPLIT)]), "後半": stat(e[f(e) & (e.r0 >= SPLIT)])}
                     for k, f in CONDS.items()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"split": SPLIT, "res": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for rule in ("new", "all"):
        print(f"=== {rule}（前半 R0<{SPLIT}，後半之後） 紅K% / 收漲% / 開→收 / 昨收→收 (n)")
        for k, v in res[rule].items():
            print(f"{k:24s}", " | ".join(f"{p}: {s.get('red','-')}/{s.get('up','-')}/{s.get('oc','-')}/{s.get('cc','-')} ({s['n']})" for p, s in v.items()))
    if len(sys.argv) > 1:
        cur = ev[ev.code.isin(sys.argv[1:])].sort_values("start").groupby("code").tail(1)
        print(cur[["code", "name", "start", "end", "last_red", "last_black", "ret", "pos", "fx_last", "fx_all", "it_buy"]].to_string())
