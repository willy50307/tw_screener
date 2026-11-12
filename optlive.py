"""
選擇權大分頁 › 即時：T 字報價＋Greeks＋各履約價未平倉
  報價：群益（capital._olist 商品檔、subscribe_group("opt")，跟股票期貨共用 100 檔 → 一次訂一個到期、價平上下 STRIKES 檔）
        群益沒連線時退回資料庫最後一天的收盤／結算價（opt_strike，盤後資料）
  標的：用買賣權平價（價平附近 C − P + K）反推的遠期價，週選、月選各自算，不受期貨正逆價差影響
  Greeks：Black-76，到期 = 到期日 13:30，時間用日曆分鐘
"""
import datetime as dt
import math
import re

import numpy as np
import pandas as pd

import capital
from data import connect

STRIKES = 15          # 價平上下各幾檔 Call、Put 都訂（31 × 2 = 62 檔＋台指期，群益上限 100）
FAR = 0               # 再往外各幾檔只訂價外那一邊（willy 11/1 決定不要，避免一半空白）
_ref = {"px": None}


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _npdf(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs(F, K, T, v, call):
    """Black-76 價格與 Greeks（利率當 0）。theta = 每天、vega = 波動率每 1%"""
    if T <= 0 or v <= 0:
        intr = max(F - K, 0) if call else max(K - F, 0)
        return {"p": intr, "d": (1.0 if F > K else 0.0) if call else (-1.0 if F < K else 0.0), "g": 0.0, "t": 0.0, "v": 0.0}
    s = v * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    if call:
        p, d = F * _ncdf(d1) - K * _ncdf(d2), _ncdf(d1)
    else:
        p, d = K * _ncdf(-d2) - F * _ncdf(-d1), _ncdf(d1) - 1
    g = _npdf(d1) / (F * s)
    th = -F * _npdf(d1) * v / (2 * math.sqrt(T)) / 365
    vg = F * _npdf(d1) * math.sqrt(T) / 100
    return {"p": p, "d": d, "g": g, "t": th, "v": vg}


def iv(F, K, T, P, call):
    """二分法反推隱含波動率；權利金低於內含價值或太小就算不出來"""
    intr = max(F - K, 0) if call else max(K - F, 0)
    if P is None or T <= 0 or P <= intr + 0.05:
        return None
    lo, hi = 0.01, 4.0
    for _ in range(60):
        m = (lo + hi) / 2
        if bs(F, K, T, m, call)["p"] > P:
            hi = m
        else:
            lo = m
    m = (lo + hi) / 2
    return m if 0.015 < m < 3.9 else None


def years_to(expire, now=None):
    """到期日 13:30 收盤（日曆時間）"""
    now = now or dt.datetime.now()
    e = dt.datetime.strptime(expire, "%Y%m%d").replace(hour=13, minute=30)
    return max((e - now).total_seconds(), 0) / (365 * 86400)


def _parse(code):
    m = re.fullmatch(r"(TX[A-Z0-9])(\d{4,6})([A-X])(\d)", code)
    if not m:
        return None
    letter = m.group(3)
    return {"pre": m.group(1), "k": int(m.group(2)), "cp": "C" if letter <= "L" else "P"}


def _kind(pre):
    return "月選" if pre == "TXO" else "週三" if pre[2].isdigit() else "週五"


def expiries():
    """群益商品檔裡的臺指選擇權到期（近的在前）"""
    out = {}
    for c, e in capital._olist.items():
        p = _parse(c)
        if p:
            out.setdefault((e, p["pre"]), 0)
            out[(e, p["pre"])] += 1
    today = dt.date.today().strftime("%Y%m%d")
    return [{"key": f"{pre}_{e}", "pre": pre, "expire": e, "kind": _kind(pre), "n": n}
            for (e, pre), n in sorted(out.items()) if e >= today]


def _db_chain(con, expire):
    """資料庫最後一天：這個到期日各履約價的收盤、結算、未平倉（期交所盤後資料）"""
    d = con.execute("SELECT MAX(date) FROM opt_strike WHERE expire = ?", (expire,)).fetchone()[0]
    if not d:
        return None, pd.DataFrame()
    s = pd.read_sql("SELECT contract, strike, cp, close, settle, volume, oi FROM opt_strike WHERE date = ? AND expire = ?", con, params=(d, expire))
    return d, s


def _tx_close():
    """資料庫最後一天台指期近月收盤（群益沒連線時當價平）"""
    con = connect()
    r = con.execute("SELECT close FROM fut_tx WHERE session='一般' AND length(contract)=6 AND date=(SELECT MAX(date) FROM fut_tx WHERE session='一般') ORDER BY volume DESC LIMIT 1").fetchone()
    con.close()
    return r[0] if r else None


def _forward(rows, guess):
    """買賣權平價：價平附近（C、P 都有報價）的 K + C − P 取中位數"""
    xs = []
    for k, r in rows.items():
        c, p = r.get("C", {}).get("mid"), r.get("P", {}).get("mid")
        if c is not None and p is not None and (guess is None or abs(k - guess) <= guess * 0.03):
            xs.append((abs(c - p), k + c - p))
    xs.sort()
    return float(np.median([x[1] for x in xs[:5]])) if xs else guess


def _mid(q):
    """參考價：買賣都有 → 中價（價差太大用成交價）；只有成交價就用成交價"""
    b, a, z = q.get("bid") or 0, q.get("ask") or 0, q.get("z")
    if b > 0 and a > 0 and a >= b:
        m = (a + b) / 2
        if z and (a - b) > max(2.0, m * 0.3) and b <= z <= a:
            return z
        return m
    return z or (q.get("y") or None)


def chain(key=None, center=None):
    """key = pre_expire（例如 TXU_20261106）；center = 想看的價平（沒給就用上次的遠期價）"""
    exps = expiries()
    con = connect()
    if not exps:   # 群益沒連線／商品檔還沒來：用資料庫列出還沒到期的合約
        today = dt.date.today().strftime("%Y%m%d")
        rows = con.execute("SELECT contract, MAX(expire) FROM opt_strike WHERE expire >= ? AND date = (SELECT MAX(date) FROM opt_strike) GROUP BY contract",
                           (today,)).fetchall()
        exps = [{"key": f"DB_{e}", "pre": "DB", "expire": e, "kind": "月選" if re.fullmatch(r"\d{6}", c) else "週三" if "W" in c else "週五", "contract": c, "n": 0}
                for c, e in sorted(rows, key=lambda r: r[1])]
    sel = next((x for x in exps if x["key"] == key), None) or (exps[0] if exps else None)
    if not sel:
        con.close()
        return {"error": "沒有選擇權合約資料", "exps": []}
    db_date, db = _db_chain(con, sel["expire"])
    con.close()
    tx = capital._quotes.get("TX00", {})        # 台指期近月（群益）
    guess = center or _ref.get(sel["key"]) or tx.get("z") or _tx_close()
    live = capital.ready() and sel["pre"] != "DB"
    rows = {}
    def _nz(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v
    dbq = {(int(r.strike), r.cp): {"z": _nz(r.close), "v": _nz(r.volume), "oi": _nz(r.oi), "stale": db_date,
                                   "mid": _nz(r.settle if r.settle and r.settle > 0 else r.close)} for r in db.itertuples()} if len(db) else {}
    if live:
        codes = {}
        for c, e in capital._olist.items():
            p = _parse(c)
            if p and e == sel["expire"] and p["pre"] == sel["pre"]:
                codes[(p["k"], p["cp"])] = c
        ks = sorted({k for k, _ in codes})
        side = {}
        if guess and ks:
            i = int(np.argmin([abs(k - guess) for k in ks]))
            lo, hi = max(0, i - STRIKES), i + STRIKES + 1
            side = {**{k: "P" for k in ks[max(0, lo - FAR):lo]}, **{k: "C" for k in ks[hi:hi + FAR]}}
            ks = ks[max(0, lo - FAR):hi + FAR]
        want = [codes[(k, cp)] for k in ks for cp in side.get(k, "CP") if (k, cp) in codes]
        capital.subscribe_group("opt", ["TX00"] + want[:90])
        for k in ks:
            for cp in "CP":
                if cp not in side.get(k, "CP"):     # 很價內的那一邊沒訂（額度不夠）→ 用資料庫最後一天收盤／結算價補，標成非即時
                    rows.setdefault(k, {})[cp] = dbq.get((k, cp), {})
                    continue
                q = capital._quotes.get(codes.get((k, cp), "\0"))
                if q:
                    rows.setdefault(k, {})[cp] = {"z": q.get("z"), "y": q.get("y"), "bid": q.get("bid"), "ask": q.get("ask"),
                                                  "v": q.get("v"), "oi": q.get("oi"), "t": q.get("t"), "mid": _mid(q)}
                else:
                    rows.setdefault(k, {})[cp] = {}
    else:
        x = db
        if guess and len(x):
            ks = sorted(x.strike.unique())
            i = int(np.argmin([abs(k - guess) for k in ks]))
            x = x[x.strike.isin(ks[max(0, i - STRIKES - FAR):i + STRIKES + FAR + 1])]
        for r in x.itertuples():
            p = r.settle if r.settle and r.settle > 0 else r.close
            nz = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else v
            rows.setdefault(int(r.strike), {})[r.cp] = {"z": nz(r.close), "y": None, "v": nz(r.volume), "oi": nz(r.oi), "mid": nz(p)}
    # 昨日未平倉（資料庫最後一天）→ 增減
    prev = {(int(r.strike), r.cp): r.oi for r in db.itertuples()} if len(db) else {}
    F = _forward(rows, guess)
    if F:
        _ref[sel["key"]] = F
    import optmodel
    T_cal = years_to(sel["expire"])
    settle_now = optmodel.is_settle_session(sel["expire"])
    # 結算日盤中：只剩幾個小時，用日曆時間算 IV 會被放大 2~3 倍（晚上、週末根本不會動）。
    # 改用「有效交易分鐘」（13:00 前照算，13:00~13:30 取平均只算 1/3）÷ 一年的日盤分鐘，跟實際波動同一把尺
    T = optmodel.settle_minutes()[0] / optmodel.YEAR_MIN if settle_now else T_cal
    out = []
    for k in sorted(rows):
        row = {"k": k}
        for cp in "CP":
            q = dict(rows[k].get(cp) or {})
            oth = rows[k].get("P" if cp == "C" else "C") or {}
            if F and (not q or q.get("stale")) and oth.get("mid") and not oth.get("stale"):
                # 沒訂即時的這一邊：用另一邊的即時價＋買賣權平價推算（C − P = F − K），比盤後價準
                syn = round(max(oth["mid"] + ((F - k) if cp == "C" else (k - F)), 0.1), 1)
                q = {"z": syn, "syn": True, "oi": q.get("oi"), "v": q.get("v"), "mid": syn}
                rows[k][cp] = q
            q.pop("mid", None)
            m = (rows[k].get(cp) or {}).get("mid")
            v = iv(F, k, T, m, cp == "C") if F and m else None
            if v:
                g = bs(F, k, T, v, cp == "C")
                th = g["t"] * (365 / 252 if settle_now else 1)     # 結算日 T 是交易年 → 換成「每個交易日」
                q.update(iv=round(v * 100, 1), d=round(g["d"], 3), g=round(g["g"] * 10000, 2), th=round(th, 2), vg=round(g["v"], 2))
            yo = prev.get((k, cp))
            if yo is not None:
                q["yoi"] = yo
            row[cp] = q
        out.append(row)
    atm = min(out, key=lambda r: abs(r["k"] - F))["k"] if out and F else None
    a = next((r for r in out if r["k"] == atm), {})
    ivs = [x for x in (a.get("C", {}).get("iv"), a.get("P", {}).get("iv")) if x] if a else []
    atm_iv = float(np.mean(ivs)) if ivs else None
    model = None
    if F and out:      # 定價模型：每個履約價的合理價（歷史報酬分佈）、價平 IV 貴不貴
        try:
            hd = optmodel.trading_days(sel["expire"])
            fv = optmodel.fair(F, [r["k"] for r in out], hd)
            st = optmodel.fair_settle(F, [r["k"] for r in out]) if settle_now else None
            for r in out:
                for i, cp in enumerate("CP"):
                    r[cp]["fair"] = round((st["fair"] if st else fv["now"])[r["k"]][i], 1)
                    r[cp]["fair_l"] = round(fv["long"][r["k"]][i], 1)
                    m = (rows[r["k"]].get(cp) or {}).get("mid")
                    if m and r[cp]["fair"] > 0.05:
                        r[cp]["mkt"] = round(m, 1)
            model = {"judge": optmodel.judge(sel["kind"], T_cal * 365, atm_iv), "long_vol": float(fv["long_vol"]), "h": round(hd, 2)}
            model["rv"] = optmodel.rv_pack()
            if settle_now:      # 結算日：歷史「剩 1 天內」的 IV 是前一天收盤（含過夜），跟盤中不能比 → 改看 IV ÷ 實際波動
                model["judge"]["settle"] = optmodel.judge_settle(atm_iv, model["rv"])
                model["judge"]["view"] = model["judge"]["settle"].get("view", "")
            if st:      # 結算日模式：標出低於內含價值（撿便宜）、剩沒多久卻還很貴的價外單
                under, rich = [], []
                for r in out:
                    for cp in "CP":
                        q, k = r[cp], r["k"]
                        intr = max(F - k, 0) if cp == "C" else max(k - F, 0)
                        buy = q.get("ask") if q.get("ask") else q.get("z")
                        if intr > 0 and buy and buy < intr - 1:
                            q["flag"] = "under"
                            under.append({"k": k, "cp": cp, "buy": buy, "intr": round(intr, 1), "gain": round(intr - buy, 1)})
                        elif intr == 0 and q.get("mkt") and q["mkt"] >= 1 and q["mkt"] > max(q["fair"] * 3, q["fair"] + 2):
                            q["flag"] = "rich"
                            rich.append({"k": k, "cp": cp, "mkt": q["mkt"], "fair": q["fair"], "otm": round(abs(k - F))})
                model["settle"] = {k_: v for k_, v in st.items() if k_ != "fair"}
                model["settle"].update(under=sorted(under, key=lambda x: -x["gain"])[:8], rich=sorted(rich, key=lambda x: x["otm"])[:8])
        except Exception as e:
            model = {"error": str(e)}
    move = F * (atm_iv / 100) * math.sqrt(T) if F and atm_iv and not np.isnan(atm_iv) else None
    # 換成「交易時間」的隱波：日曆時間會把晚上、週末也算進去，剩不到一兩天時數字會被放大，
    # 換成剩幾個交易日（收盤到收盤，含過夜）÷ 252，才能跟實際波動（日K × √252）放在一起比
    atm_iv_tt = None
    if atm_iv and not np.isnan(atm_iv):
        if settle_now:
            atm_iv_tt = atm_iv
        else:
            try:
                h_tr = optmodel.trading_days(sel["expire"]) / 252
                atm_iv_tt = atm_iv * math.sqrt(T_cal / h_tr) if h_tr > 0 and T_cal > 0 else None
            except Exception:
                atm_iv_tt = None
    return {"exps": exps, "sel": sel, "live": live, "db_date": db_date, "F": F, "T_days": round(T_cal * 365, 2), "atm": atm,
            "iv_basis": "交易時間" if settle_now else "日曆時間",
            "atm_iv_tt": None if atm_iv_tt is None else round(float(atm_iv_tt), 1),
            "atm_iv": None if atm_iv is None or np.isnan(atm_iv) else round(float(atm_iv), 1),
            "move": None if move is None else round(move), "tx": tx.get("z"), "rows": out,
            "cap": capital.status.get("msg"), "now": dt.datetime.now().strftime("%H:%M:%S"), "model": model}


def stop():
    """離開選擇權頁：把額度還給股票、期貨"""
    capital.subscribe_group("opt", [])