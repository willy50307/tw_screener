"""
波浪理論（艾略特）自動數浪：台指期 全盤日K、60 分K
  1. 用 ZigZag 找轉折點（日K 6%、60分K 1.5% / 1%）
  2. 窮舉「起點＋5 個轉折」的組合，套鐵律過濾：
       第 2 浪不跌破第 1 浪起點、第 3 浪不是最短、第 4 浪不跟第 1 浪重疊、每一浪的高低點是該段的極值
  3. 用費波南希比例打分數（第 2 浪回檔 0.382~0.618、第 3 浪 1.618 倍、第 4 浪回檔 0.236~0.5、第 5 浪≈第 1 浪…）
  4. 主要劇本＝分數最高；備選劇本＝結構不同的第二名；另外檢查「擴張平台（A-B-C）」
數浪本來就有主觀成分，這裡是規則化的結果，一定要搭配價位驗證（失效價）
"""
import math
import sqlite3

import numpy as np
import pandas as pd

import engine
from data import connect

FIB_R = [0.236, 0.382, 0.5, 0.618, 0.786]


def zigzag(df, pct):
    """回傳 [(type, index, price)]，type = 'H' / 'L'；最後一段未完成的極值也附上（標 open=True）"""
    piv, trend, hi, lo = [], 0, 0, 0
    H, L = df["high"].values, df["low"].values
    for i in range(len(df)):
        if H[i] >= H[hi]:
            hi = i
        if L[i] <= L[lo]:
            lo = i
        if trend >= 0 and L[i] <= H[hi] * (1 - pct) and hi < i:
            piv.append(["H", hi, float(H[hi])]); trend = -1; lo = i
        elif trend <= 0 and H[i] >= L[lo] * (1 + pct) and lo < i:
            piv.append(["L", lo, float(L[lo])]); trend = 1; hi = i
    # 最後還在走的那一段
    if trend == 1:
        piv.append(["H", hi, float(H[hi]), True])
    elif trend == -1:
        piv.append(["L", lo, float(L[lo]), True])
    return piv


def _near(x, targets, tol):
    return max(0.0, 1 - min(abs(math.log(x / t)) for t in targets) / tol) if x > 0 else 0.0


def score_impulse(p, up=True):
    """p：6 個價位 [起點, 1, 2, 3, 4, 5]；回傳 (分數, 說明) 或 None（違反鐵律）"""
    s = 1 if up else -1
    w1, w2, w3, w4, w5 = (s * (p[i + 1] - p[i]) for i in range(5))
    if min(w1, w3, w5) <= 0 or min(-w2, -w4) <= 0:
        return None
    if s * (p[2] - p[0]) <= 0:                 # 第 2 浪跌破起點
        return None
    if w3 < w1 and w3 < w5:                    # 第 3 浪最短
        return None
    if s * (p[4] - p[1]) <= 0:                 # 第 4 浪與第 1 浪重疊
        return None
    r2, r3, r4, r5 = -w2 / w1, w3 / w1, -w4 / w3, w5 / w1
    sc = (_near(r2, [0.382, 0.5, 0.618], 0.6) + _near(r3, [1.618, 2.0, 2.618], 0.5) * 1.3 + _near(r4, [0.236, 0.382, 0.5], 0.6)
          + _near(r5, [0.618, 1.0, 1.618], 0.5) + (0.4 if abs(r2 - r4) >= 0.12 else 0))       # 交替原則
    return sc, {"r2": r2, "r3": r3, "r4": r4, "r5": r5}


def find_impulses(df, piv, up=True, min_size=0.0, end_must_be_extreme=True):
    """在轉折點裡找 5 浪；每一浪的高低點必須是該段的極值"""
    H, L = df["high"].values, df["low"].values
    lows = [q for q in piv if q[0] == ("L" if up else "H")]
    highs = [q for q in piv if q[0] == ("H" if up else "L")]
    ext_hi = lambda a, b: H[a:b + 1].max()
    ext_lo = lambda a, b: L[a:b + 1].min()
    res = []
    last = len(df) - 1
    for s0 in lows:
        for a in highs:
            if a[1] <= s0[1]:
                continue
            for b in lows:
                if b[1] <= a[1]:
                    continue
                for c in highs:
                    if c[1] <= b[1]:
                        continue
                    for d in lows:
                        if d[1] <= c[1]:
                            continue
                        for e in highs:
                            if e[1] <= d[1]:
                                continue
                            pr = [s0[2], a[2], b[2], c[2], d[2], e[2]]
                            sc = score_impulse(pr, up)
                            if not sc:
                                continue
                            ix = [s0[1], a[1], b[1], c[1], d[1], e[1]]
                            # 每一段的極值檢查
                            ok = True
                            for k in range(5):
                                lo_, hi_ = ix[k], ix[k + 1]
                                if up:
                                    if k % 2 == 0 and ext_hi(lo_, hi_) > pr[k + 1] + 1e-6: ok = False
                                    if k % 2 == 0 and ext_lo(lo_, hi_) < pr[k] - 1e-6: ok = False
                                    if k % 2 == 1 and ext_lo(lo_, hi_) < pr[k + 1] - 1e-6: ok = False
                                else:
                                    if k % 2 == 0 and ext_lo(lo_, hi_) < pr[k + 1] - 1e-6: ok = False
                                    if k % 2 == 0 and ext_hi(lo_, hi_) > pr[k] + 1e-6: ok = False
                                    if k % 2 == 1 and ext_hi(lo_, hi_) > pr[k + 1] + 1e-6: ok = False
                                if not ok:
                                    break
                            if not ok:
                                continue
                            size = abs(pr[5] / pr[0] - 1)
                            if size < min_size:
                                continue
                            # 第 5 浪要是起點之後到現在的最高（最低）點 → 這組 5 浪「已完成、目前在修正」
                            if end_must_be_extreme:
                                if up and H[ix[5]:].max() > pr[5] + 1e-6: continue
                                if not up and L[ix[5]:].min() < pr[5] - 1e-6: continue
                            total = sc[0] + 1.2 * math.log1p(size * 5)
                            res.append({"score": total, "fit": sc[0], "idx": ix, "price": pr, "ratios": sc[1], "size": size, "up": up})
    return sorted(res, key=lambda x: -x["score"])


def fib_levels(a, b):
    """a→b 這段的回檔價位"""
    return [{"r": r, "price": b - (b - a) * r} for r in FIB_R]


def _date(df, i, intraday=False):
    v = df["date"].iloc[i]
    return int(v) if intraday else v


def _wave_marks(df, imp, labels, intraday=False):
    out = []
    for k, (i, p) in enumerate(zip(imp["idx"], imp["price"])):
        if k == 0:
            continue
        top = (k % 2 == 1) == imp["up"]
        out.append({"time": _date(df, i, intraday), "price": p, "text": labels[k - 1], "pos": "aboveBar" if top else "belowBar"})
    return out


def analyze():
    con = connect()
    d = engine.load_special("TX")
    con.close()
    d = d[d["date"] >= "2024-06-01"].reset_index(drop=True)
    piv = zigzag(d, 0.06)
    imps = find_impulses(d, piv, up=True, min_size=0.5)
    out = {"daily": None, "h60": None}
    last = d.iloc[-1]
    if imps:
        p1 = imps[0]
        # 備選：第 5 浪在「另一個大高點」就結束（之後走擴張平台 A-B-C，B 浪創新高）
        others = find_impulses(d, piv, up=True, min_size=0.5, end_must_be_extreme=False)
        alt = next((x for x in others if x["idx"][5] < p1["idx"][5] and x["price"][5] >= p1["price"][5] * 0.95), None)
        top_i, top_p = p1["idx"][5], p1["price"][5]
        start_p = p1["price"][0]
        drop = (last.close / top_p - 1) * 100
        w = [p1["price"][k + 1] - p1["price"][k] for k in range(5)]
        daily = {"bars": [[r.date, r.open, r.high, r.low, r.close] for r in d.itertuples()],
                 "primary": {"marks": _wave_marks(d, p1, ["1", "2", "3", "4", "5"]), "ratios": p1["ratios"], "fit": p1["fit"],
                             "points": [{"date": d["date"].iloc[i], "price": p} for i, p in zip(p1["idx"], p1["price"])], "len": w},
                 "fib_all": fib_levels(start_p, top_p),
                 "fib_w5": fib_levels(p1["price"][4], top_p),
                 "top": {"date": d["date"].iloc[top_i], "price": top_p}, "last": {"date": last.date, "close": float(last.close), "low": float(d.low.iloc[top_i:].min())},
                 "drop": drop}
        if alt:
            daily["alt"] = {"marks": _wave_marks(d, alt, ["1", "2", "3", "4", "5"]), "ratios": alt["ratios"], "fit": alt["fit"],
                            "points": [{"date": d["date"].iloc[i], "price": p} for i, p in zip(alt["idx"], alt["price"])]}
            # 擴張平台：備選的第 5 浪之後 → A（低點）→ B（超過第 5 浪的新高）→ 現在 C
            a5_i = alt["idx"][5]
            if a5_i < top_i:
                a_i = int(d.low.iloc[a5_i:top_i].idxmin())
                A = alt["price"][5] - float(d.low.iloc[a_i])
                B = top_p - float(d.low.iloc[a_i])
                daily["alt"]["flat"] = {"a_date": d["date"].iloc[a_i], "a_low": float(d.low.iloc[a_i]), "A": A, "B_ratio": B / A,
                                        "c_targets": [{"r": r, "price": top_p - A * r} for r in (1.0, 1.272, 1.618)]}
        out["daily"] = daily
    # ---------- 60 分K：從日K的頭部之後的走勢 ----------
    con = connect()
    h = pd.read_sql("SELECT ts AS date, open, high, low, close FROM intraday WHERE code='TX' AND tf='60' ORDER BY ts", con)
    con.close()
    if len(h) > 50 and out["daily"]:
        h = h.reset_index(drop=True)
        top_i = int(h.high.idxmax())
        seg = h.iloc[top_i:].reset_index(drop=True)
        best = None
        for pct in (0.015, 0.01, 0.008):
            pv = zigzag(seg, pct)
            pv = [["H", 0, float(seg.high.iloc[0])]] + [q for q in pv if q[1] > 0]
            cand = find_impulses(seg, pv, up=False, min_size=0.03, end_must_be_extreme=False)
            cand = [c for c in cand if c["idx"][0] == 0]
            if cand and (best is None or cand[0]["fit"] > best["fit"]):
                best = cand[0]
        h60 = {"bars": [[int(r.date), r.open, r.high, r.low, r.close] for r in h.itertuples()], "top": {"time": int(h.date.iloc[top_i]), "price": float(h.high.iloc[top_i])}}
        if best:
            ix = [i + top_i for i in best["idx"]]
            b2 = dict(best, idx=ix)
            end_i = ix[5]
            after = h.iloc[end_i:]
            a_len = best["price"][0] - best["price"][5]
            h60["impulse"] = {"marks": _wave_marks(h, b2, ["(1)", "(2)", "(3)", "(4)", "(5)"], intraday=True), "ratios": best["ratios"],
                              "points": [{"time": int(h.date.iloc[i]), "price": p} for i, p in zip(ix, best["price"])], "len": a_len,
                              "end": {"time": int(h.date.iloc[end_i]), "price": best["price"][5]},
                              "after_high": float(after.high.max()) if len(after) else None, "after_low": float(after.low.min()) if len(after) else None,
                              "b_targets": [{"r": r, "price": best["price"][5] + a_len * r} for r in (0.382, 0.5, 0.618)],
                              "c_targets": [{"r": r, "price": None} for r in (1.0, 1.618)]}
        out["h60"] = h60
    out["text"] = _narrative(out)
    return out


def _narrative(o):
    D, H = o.get("daily"), o.get("h60")
    T = {"summary": [], "daily": [], "h60": [], "levels": [], "alt": [], "notes": []}
    if not D:
        return T
    pts, r = D["primary"]["points"], D["primary"]["ratios"]
    f = lambda x: f"{x:,.0f}"
    months = (pd.Timestamp(pts[5]["date"]) - pd.Timestamp(pts[0]["date"])).days / 30.4
    T["daily"] = [
        f"起點 {pts[0]['date']} 低點 <b>{f(pts[0]['price'])}</b>（整段上升 5 浪歷時約 {months:.0f} 個月，漲 {pts[5]['price'] / pts[0]['price'] - 1:.0%}）",
        f"第 1 浪 → {pts[1]['date']} {f(pts[1]['price'])}（漲 {f(pts[1]['price'] - pts[0]['price'])} 點）",
        f"第 2 浪 → {pts[2]['date']} {f(pts[2]['price'])}（回檔第 1 浪的 {r['r2']:.0%}）",
        f"第 3 浪 → {pts[3]['date']} {f(pts[3]['price'])}（是第 1 浪的 {r['r3']:.2f} 倍{'，延伸浪' if r['r3'] >= 1.6 else ''}）",
        f"第 4 浪 → {pts[4]['date']} {f(pts[4]['price'])}（回檔第 3 浪的 {r['r4']:.0%}，沒有跌進第 1 浪的範圍）",
        f"第 5 浪 → {pts[5]['date']} <b>{f(pts[5]['price'])}</b>（是第 1 浪的 {r['r5']:.2f} 倍{'，第 3 浪延伸時第 5 浪常跟第 1 浪等長' if 0.8 <= r['r5'] <= 1.2 else ''}）"]
    last = D["last"]
    T["summary"].append(f"<b>日K：</b>從 {pts[0]['date'][:7]} 的 {f(pts[0]['price'])} 到 {pts[5]['date']} 的 {f(pts[5]['price'])}，"
                        f"符合完整的<b>上升 5 浪</b>；最新收盤 {f(last['close'])}，離高點 {D['drop']:+.1f}%")
    if H and H.get("impulse"):
        im = H["impulse"]
        ip = im["points"]
        hi_after = im["after_high"] or im["end"]["price"]
        b = im["b_targets"]
        T["h60"] = [f"從高點 {f(ip[0]['price'])} 開始的下跌，60 分K 數得出<b>完整的下跌 5 浪</b>："
                    + "、".join(f"({k}) {f(p['price'])}" for k, p in enumerate(ip[1:], 1)),
                    f"第 (3) 浪是第 (1) 浪的 {im['ratios']['r3']:.2f} 倍、第 (5) 浪是第 (1) 浪的 {im['ratios']['r5']:.2f} 倍",
                    f"下跌 5 浪 = 修正的 <b>A 浪</b>（或更大一級下跌的第 (1) 浪），共跌 {f(im['len'])} 點",
                    f"A 浪結束後的反彈目前最高 {f(hi_after)}；B 浪常見反彈到 A 浪的 38.2%~61.8%：{f(b[0]['price'])}／{f(b[1]['price'])}／{f(b[2]['price'])}"]
        T["summary"].append(f"<b>60 分K：</b>從 {f(ip[0]['price'])} 跌到 {f(ip[5]['price'])} 是完整的<b>下跌 5 浪＝A 浪</b>，"
                            f"目前在 <b>B 浪反彈</b>（反彈目標 {f(b[0]['price'])}~{f(b[2]['price'])}），之後還有 <b>C 浪</b>要跌")
        a_end = ip[5]["price"]
        T["levels"] += [f"<b>A 浪低點 {f(a_end)}</b>：B 浪的支撐；跌破代表 C 浪提早開始",
                        f"B 浪反彈壓力：{f(b[0]['price'])}（38.2%）、{f(b[1]['price'])}（50%）、{f(b[2]['price'])}（61.8%）",
                        f"C 浪目標（從 B 浪高點算，C＝A）：假設 B 反彈到 50%（{f(b[1]['price'])}）→ C 約 {f(b[1]['price'] - im['len'])}；C＝1.618A → 約 {f(b[1]['price'] - im['len'] * 1.618)}"]
    fa = {x["r"]: x["price"] for x in D["fib_all"]}
    T["levels"] += [f"整段上升 5 浪（{f(pts[0]['price'])}→{f(pts[5]['price'])}）的回檔：23.6% {f(fa[0.236])}、38.2% {f(fa[0.382])}、50% {f(fa[0.5])}",
                    f"<b>第 4 浪低點 {f(pts[4]['price'])}</b>：大級數修正最常見的目標區（回到前一個第 4 浪附近）",
                    f"<b>失效價 {f(pts[5]['price'])}</b>：如果突破這個高點，代表第 5 浪還沒結束（延伸），頭部的說法就不成立"]
    T["summary"].append(f"<b>現在的位置：</b>大級數上升 5 浪可能已在 {pts[5]['date']} 完成，進入像圖中「【5】之後的 A-B-C 修正」；"
                        f"短線是 A 浪跌完後的 B 浪反彈。若 B 浪反彈無法站回 {f(H['impulse']['b_targets'][2]['price']) if H and H.get('impulse') else '前高'} 之上、再跌破 A 浪低點，C 浪就會展開")
    al = D.get("alt")
    if al:
        ap = al["points"]
        T["alt"].append(f"備選劇本：第 5 浪在 {ap[5]['date']} 的 {f(ap[5]['price'])} 就結束（第 1 浪 {ap[0]['date']}→{ap[1]['date']}）")
        if al.get("flat"):
            fl = al["flat"]
            T["alt"].append(f"之後走<b>擴張平台修正</b>：A 浪跌到 {fl['a_date']} 的 {f(fl['a_low'])}，B 浪反彈到 {f(pts[5]['price'])}（A 浪的 {fl['B_ratio']:.2f} 倍，超過前高），"
                            f"現在是 <b>C 浪</b>，目標 C＝A 約 {f(fl['c_targets'][0]['price'])}、C＝1.618A 約 {f(fl['c_targets'][2]['price'])}（比主要劇本更空）")
    T["notes"] = ["波浪理論的數浪有主觀成分，同一段走勢常有多種數法；這裡用固定規則（鐵律＋費波南希比例打分）選出最合理的兩種",
                  "請以「失效價」管理：突破前高＝頭部說法失效；跌破 A 浪低點＝C 浪啟動",
                  "台指期是近月連續（換月時有價差），60 分K 只有最近 30 個交易日"]
    return T


if __name__ == "__main__":
    import json
    o = analyze()
    print(json.dumps(o["text"], ensure_ascii=False, indent=1))
    print(o["daily"]["primary"]["points"])
    if o["daily"].get("alt"):
        print("alt", o["daily"]["alt"]["points"], o["daily"]["alt"].get("flat"))
    if o["h60"] and o["h60"].get("impulse"):
        print("h60", o["h60"]["impulse"]["points"])
