"""
台股選股 App 後端（Flask）。
  本機：python app.py  →  開 http://localhost:5288
  雲端：之後用 gunicorn app:app 部署即可
"""
import datetime as dt
import json
import os
import threading
import time
import traceback

from flask import Flask, jsonify, request

import ai
import backtest
import broker
import capital
import market_brief
import waves
import settlement
import settle_tail
import warrants
import chips
import options
import limitup
import live
import ptt
import settings
import stats
import notice
from data import connect, update_prices
import engine as engine_mod
from engine import Engine
from strategies import STRATEGIES

PORT = int(os.environ.get("PORT", 5288))

app = Flask(__name__, static_folder="static", static_url_path="")
engine = Engine()
job = {"running": False, "msg": "", "progress": {}, "last": None, "error": None}
live_job = {"running": False, "msg": "", "error": None}


# ---------- 背景更新 ----------

def run_update():
    if job["running"]:
        return
    job.update(running=True, error=None, progress={}, msg="抓取行情資料中…")
    try:
        update_prices(settings.load()["backfill_days"], job["progress"])
        job["msg"] = "抓取處置股 / 注意股公告…"
        update_notice_data()
        job["msg"] = "選股計算中…"
        engine.reload()
        job["last"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        job["msg"] = "完成"
    except Exception as e:
        traceback.print_exc()
        job["error"] = str(e)
        job["msg"] = "更新失敗"
    finally:
        job["running"] = False


def update_notice_data():
    con = connect()
    try:
        notice.update(con)
    finally:
        con.close()


def scheduler():
    """App 開著的時候，每天到設定時間自動更新一次；晚上 7 點後抓籌碼（還沒抓齊就每 30 分鐘再試）"""
    done_today = None
    while True:
        try:
            now = dt.datetime.now()
            p = settings.load()
            hm = now.strftime("%H:%M")
            # 12:00 權證盤中快照（一天一次）
            if now.weekday() < 5 and "12:00" <= hm < "12:40" and snap_job["day"] != now.date() and not snap_job["running"]:
                snap_job["day"] = now.date()
                threading.Thread(target=run_snap, daemon=True).start()
            # 下午 4 點後：台指期、選擇權、加權指數（期交所約 15:00~16:15 公布；沒抓到每 30 分鐘再試）
            ft = p.get("fut_time", "16:00")
            if (now.weekday() < 5 and ft and ft <= hm < "23:50" and not fut_job["running"]
                    and (fut_job["last_try"] is None or now - fut_job["last_try"] > dt.timedelta(minutes=30))
                    and options.status()["done"] < now.date().isoformat()):   # 未平倉、履約價、台指期都抓到今天才算完成
                fut_job["last_try"] = now
                threading.Thread(target=run_fut, daemon=True).start()
            if now.weekday() < 5 and hm < "23:50" and not chips_job["running"]:
                st = None
                # 晚上 7 點：三大法人＋分點；晚上 10 點：融資券＋借券（各自沒抓齊才每 30 分鐘再試）
                for key, t, kinds, flag in (("eve", p.get("chips_time", "19:00"), ("inst", "broker"), "eve_done"),
                                            ("night", p.get("chips_margin_time", "22:00"), ("margin", "sbl"), "night_done")):
                    last = chips_job["last_try"].get(key)
                    if t and hm >= t and (last is None or now - last > dt.timedelta(minutes=30)):
                        st = st or chips_status_dict()
                        if not st[flag]:
                            chips_job["last_try"][key] = now
                            threading.Thread(target=run_chips, args=(7, None, kinds), daemon=True).start()
                            break
        except Exception:
            traceback.print_exc()
        try:
            # 晚上 9 點後：全市場融資合計（上市／上櫃），還沒公布就每 10 分鐘再試
            now = dt.datetime.now()
            mt = settings.load().get("chips_mtot_time", "21:00")
            if (now.weekday() < 5 and mt and mt <= now.strftime("%H:%M") < "23:55" and mtot_job["day"] != now.date()
                    and (mtot_job["last_try"] is None or now - mtot_job["last_try"] > dt.timedelta(minutes=10))):
                mtot_job["last_try"] = now
                if chips.update_margin_mkt():
                    mtot_job["day"] = now.date()
        except Exception:
            traceback.print_exc()
        try:
            t = settings.load().get("auto_update_time", "").strip()
            now = dt.datetime.now()
            if t and now.weekday() < 5 and now.strftime("%H:%M") >= t and done_today != now.date():
                if engine.date != now.date().isoformat():
                    run_update()
                done_today = now.date()
        except Exception:
            traceback.print_exc()
        time.sleep(60)


def startup():
    job.update(running=True, msg="載入資料中…")
    try:
        if notice.load_meta().get("date") != dt.date.today().isoformat():
            job["msg"] = "抓取處置股 / 注意股公告…"
            update_notice_data()
        job["msg"] = "載入資料中…"
        engine.reload()
    except Exception as e:
        traceback.print_exc()
        job["error"] = str(e)
    finally:
        job.update(running=False, msg="")
    if engine.date is None:  # 第一次使用，資料庫是空的
        run_update()
    try:                     # 開 App 時最近交易日的未平倉還沒抓（例如下午 4 點後才開）→ 先補抓一次
        now = dt.datetime.now()
        day = now.date()
        if now.weekday() >= 5 or now.strftime("%H:%M") < (settings.load().get("fut_time") or "16:00"):
            day -= dt.timedelta(days=1)
        while day.weekday() >= 5:
            day -= dt.timedelta(days=1)
        if options.status()["done"] < day.isoformat() and not fut_job["running"]:
            fut_job["last_try"] = now
            threading.Thread(target=run_fut, daemon=True).start()
    except Exception:
        traceback.print_exc()
    try:                     # 先把今日盤勢分析算好（第一次大約 20 秒）
        market_brief.report()
    except Exception:
        traceback.print_exc()


# ---------- API ----------

@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/state")
def state():
    p = settings.load()
    keys = ["signal", "watch", "mine", "fc", "disp", "attn", "turn", "gain", "vsurge", "vgrow"] + ["wl_" + w["id"] for w in p.get("watchlists", [])]
    counts = {k: sum(k in r["lists"] for r in engine.rows) for k in keys}
    p["ai_key"] = "********" if p.get("ai_key") else ""   # 不把金鑰傳到網頁
    p["finmind_token"] = "********" if p.get("finmind_token") else ""
    p["capital_pwd"] = "********" if p.get("capital_pwd") else ""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backfill_status.json"), encoding="utf-8") as f:
            backfill = json.load(f)
    except Exception:
        backfill = None
    return jsonify(date=engine.date, job=job, counts=counts, settings=p, backfill=backfill,
                   strategies=[{"key": k, "label": l} for k, l, _, _ in STRATEGIES])


@app.get("/api/list")
def stock_list():
    return jsonify(engine.rows)


@app.get("/api/stock/<code>")
def stock(code):
    c = engine.chart(code, request.args.get("tf", "D"), int(request.args.get("n", 0) or 0))
    return (jsonify(c), 200) if c else (jsonify(error="查無資料"), 404)


@app.get("/api/stats")
def stats_table():
    """數據篩選頁：全市場最新一天的統計（連漲、均量比、月線斜率、外資連買…）"""
    try:
        rows, meta = stats.table(engine)
        return jsonify(keys=stats.STATS, rows=rows, meta=meta)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/search")
def search():
    return jsonify(engine.search(request.args.get("q", "")))


@app.post("/api/update")
def update():
    threading.Thread(target=run_update, daemon=True).start()
    now = dt.datetime.now()
    if now.weekday() < 5 and "09:00" <= now.strftime("%H:%M") <= "13:35":   # 盤中按更新資料 → 順便更新盤中即時
        threading.Thread(target=run_live, daemon=True).start()
    return jsonify(ok=True)


# ---------- 盤中即時 ----------

def run_live():
    if live_job["running"]:
        return
    live_job.update(running=True, error=None, msg="開始…")
    try:
        r = live.compute(live_job)
        live_job["error"] = r.get("error")
        live_job["msg"] = r.get("error") or "完成"
    except Exception as e:
        traceback.print_exc()
        live_job.update(error=str(e), msg="失敗")
    finally:
        live_job["running"] = False


@app.get("/api/live")
def live_get():
    return jsonify(job=live_job, data=live.load_last())


@app.get("/api/capital")
def capital_status():
    return jsonify(**capital.status, ticks={c: len(t) for c, t in list(capital._ticks.items())}, quotes=len(capital._quotes),
                   rec=capital.record_status(), rc={k: str(v) for k, v in list(capital.rc.items())}, want=capital._all_want(),
                   flist=len(capital._flist))


# ---------- 即時報價頁（自選股、四格看盤、錄影重播）----------

def _names_of(codes):
    return {c: (engine.names.get(c) or [capital._names.get(c, "")])[0] for c in codes}


def _mis_quotes(codes):
    """群益沒開時：自選股的報價改跟證交所 MIS 拿"""
    from warrants import _mis
    from data import _num
    sym = [f"{'otc' if (engine.names.get(c) or ['', ''])[1] == '上櫃' else 'tse'}_{c}.tw" for c in codes]
    out = {}
    for x in _mis(sym) if sym else []:
        z = _num(x.get("z")) or _num(x.get("pz")) or live._first(x.get("b"))
        y = _num(x.get("y"))
        if z and y:
            out[x["c"]] = {"z": z, "y": y, "o": _num(x.get("o")), "h": _num(x.get("h")), "l": _num(x.get("l")),
                           "v": _num(x.get("v")), "t": x.get("t", "")}
    return out


@app.get("/api/rt/watch")
def rt_watch():
    return _rt_rows(settings.load().get("rt_watch", []))


@app.get("/api/rt/list")
def rt_list():
    """看盤 › 證券：個股K 左邊某個清單（watch 明日觀察、mine 自選、disp 處置股、wl_xxx 自己的清單…）的即時報價。
    群益只訂前 60 檔（即時報價一共 100 檔，要留給四格看盤、期貨）"""
    key = request.args.get("key", "mine")
    codes = [r["code"] for r in engine.rows if key in r["lists"]]
    return _rt_rows(codes, sub=codes[:60], group="stk")


def _rt_rows(codes, sub=None, group=None):
    """codes 的即時報價：群益有開就用群益（group = 整組換掉的訂閱，只訂 sub 那些），還沒收到的用證交所 MIS 補"""
    if capital.ready():
        if group:
            capital.subscribe_group(group, sub or [])
        else:
            capital.subscribe(codes)
        q, src = {c: capital._quotes[c] for c in codes if c in capital._quotes}, "群益即時"
        if len(q) < len(codes):   # 剛訂閱還沒收到的先用 MIS 補
            try:
                q = {**_mis_quotes([c for c in codes if c not in q]), **q}
            except Exception:
                pass
    else:
        try:
            q, src = _mis_quotes(codes), "證交所 MIS（約 5 秒延遲）"
        except Exception as e:
            q, src = {}, f"抓不到報價：{e}"
    names = _names_of(codes)
    return jsonify(src=src, rows=[{"code": c, "name": names.get(c, ""), **q.get(c, {})} for c in codes])


@app.post("/api/rt/watch")
def rt_watch_set():
    p = settings.load()
    p["rt_watch"] = [str(c).strip() for c in (request.get_json() or {}).get("codes", []) if str(c).strip()]
    settings.save(p)
    return jsonify(ok=True)


@app.get("/api/rt/board")
def rt_board():
    """五格看盤：A、B 兩組共 10 格都訂逐筆＋五檔，只回傳正在看的那組（grp=0/1，每組 5 格）的五檔、最近逐筆、1 分K"""
    codes = ([c.strip() for c in request.args.get("codes", "").split(",")] + [""] * 10)[:10]
    grp = 1 if request.args.get("grp") == "1" else 0
    p = settings.load()
    if codes != p.get("rt_board"):
        p["rt_board"] = codes
        settings.save(p)
    if not capital.ready():
        return jsonify(ready=False, msg=capital.status["msg"], rec=capital.record_status())
    capital.pin(codes[grp * 5:grp * 5 + 5] + codes[(1 - grp) * 5:(1 - grp) * 5 + 5])   # 正在看的那組先訂
    capital.subscribe([c for c in codes if c])
    names = _names_of([c for c in codes if c])
    out = []
    for c in codes[grp * 5:grp * 5 + 5]:
        if not c:
            out.append(None)
            continue
        t = list(capital._ticks.get(c, []))
        b = capital.bars_1m(c, t)
        q = capital._quotes.get(c, {})
        st, cum = capital.tick_stats(t)
        out.append({"code": c, "name": names.get(c, ""), "ref": q.get("y"), "q": q, "best5": capital._best5.get(c),
                    "ticks": [list(x) + [s] for x, s in zip(t[-300:], cum[-300:])], "n": len(t), "st": st,
                    "bars": [[int(r.date), r.open, r.high, r.low, r.close, int(r.volume / 1000)] for r in b.itertuples()]})
    return jsonify(ready=True, panes=out, rec=capital.record_status())


@app.post("/api/rt/record")
def rt_record():
    body = request.get_json() or {}
    if body.get("on"):
        if not capital.ready():
            return jsonify(error="群益沒有連線，不能錄")
        return jsonify(name=capital.record_start(body.get("codes", [])))
    capital.record_stop()
    return jsonify(ok=True)


@app.get("/api/rt/recordings")
def rt_recordings():
    return jsonify(capital.recordings())


@app.get("/api/rt/recording/<name>")
def rt_recording(name):
    try:
        return jsonify(capital.recording(name))
    except FileNotFoundError:
        return jsonify(error="找不到這段錄影"), 404


# ---------- 期貨看盤頁：左邊全部期貨合約（期交所 MIS），右邊點開的合約（群益五檔、明細、走勢）----------

def _fut_pane(c, name):
    t = list(capital._ticks.get(c, []))
    b = capital.bars_1m(c, t)
    q = capital._quotes.get(c, {})
    st, cum = capital.tick_stats(t)
    return {"code": c, "name": name or q.get("name") or capital._names.get(c, ""), "ref": q.get("y"), "q": q,
            "best5": capital._best5.get(c), "ticks": [list(x) + [s] for x, s in zip(t[-150:], cum[-150:])], "n": len(t), "st": st,
            "bars": [[int(r.date), r.open, r.high, r.low, r.close, int(r.volume / 1000)] for r in b.itertuples()]}


@app.get("/api/fut/table")
def fut_table():
    """sel = 右邊正在看的合約（期交所代碼，例如 TXFK6）"""
    import futures
    try:
        c = futures.table()
    except Exception as e:
        traceback.print_exc()
        return jsonify(rows=[], error=f"期交所行情抓不到：{e}")
    rows, cap = c["rows"], capital.ready()
    if cap:   # 近月指數期貨＋正在看的那檔訂群益報價（跟自選股、四格看盤共用 100 檔），有收到就蓋掉 MIS 的數字
        sel = request.args.get("sel", "")
        want = [r["sym"] for r in rows if r["grp"] == "index" and r["near"]][:30]
        if c.get("src") == "fallback":   # MIS 掛了：再加昨天量最大的近月個股期貨，湊到 80 檔
            want += [r["sym"] for r in sorted((r for r in rows if r["grp"] in ("stock", "mini") and r["near"]), key=lambda r: -(r["yv"] or 0))][:80 - len(want)]
        capital.subscribe_group("fut", [capital._flist.get(s) for s in want + [sel]])
        rows = [dict(r) for r in rows]
        for r in rows:
            q = capital._quotes.get(capital._flist.get(r["sym"], "\0"))
            if q and q.get("d") == dt.date.today().strftime("%Y%m%d"):
                r.update(z=q["z"], y=q.get("y") or r["y"], o=q["o"], h=q["h"], l=q["l"], v=q["v"] or r["v"], src="cap",
                         bid=q.get("bid") or r["bid"], ask=q.get("ask") or r["ask"], oi=q.get("oi") or r["oi"])
    return jsonify(rows=rows, session=c["session"], prev_date=c.get("prev_date"), cap=cap, cap_msg=capital.status["msg"],
                   flist=len(capital._flist), src=c.get("src"))


@app.get("/api/est")
def est_get():
    """看盤頁上方的預估量：加權、台指期近月、櫃買。群益 TSEA/OTCA 的總量是成交金額（百萬元），TX00 是口數"""
    import est
    import futures
    now = dt.datetime.now()
    tx_sess = "1" if now.time() >= dt.time(15, 0) or now.time() < dt.time(5, 0) else "0"
    if capital.ready():
        capital.subscribe_group("est", ["TSEA", "OTCA", "TX00"])
    q = {k: capital._quotes.get(k) or {} for k in ("TSEA", "OTCA", "TX00")}
    today = now.strftime("%Y%m%d")
    fresh = lambda x: x if x.get("d") == today else {}
    tse, otc, tx = q["TSEA"], q["OTCA"], fresh(q["TX00"])   # 現貨開盤前顯示前一天全天（pre）
    # 現貨只有日盤：9:00 前顯示空白，收盤後就是全天實際的量
    day_on = now.time() >= dt.time(9, 0)
    tse_amt = tse.get("v") * 1e6 if tse.get("v") else (est.mi5_today() if day_on else None)
    otc_amt = otc.get("v") * 1e6 if otc.get("v") else None
    tx_v = tx.get("v")
    if not tx_v:
        r = next((r for r in (futures._cache.get("rows") or []) if r["sym"].startswith("TXF") and r.get("near")), None)
        tx_v = r and r["v"]
    out = {}
    for k, cum, z, y in (("tse", tse_amt, tse.get("z"), tse.get("y")), ("otc", otc_amt, otc.get("z"), otc.get("y")),
                         ("tx", tx_v, tx.get("z"), tx.get("y"))):
        kind = k if k != "tx" else "tx" + tx_sess
        e, f, prev = est.estimate(kind, cum, now) if (k == "tx" or day_on) else (None, None, None)
        out[k] = {"cum": cum, "est": e, "frac": f, "z": z, "y": y, "prev": prev,   # prev = 前一個交易日同時間的累計
                  "yv": est.yesterday(kind, not day_on)}                       # yv = 昨量（前一個交易日全天）
    p = est.profiles()
    out["days"] = (p["tse"] or {}).get("days")
    out["tx_session"] = tx_sess
    out["ready"] = capital.ready()
    out["pre"] = not day_on   # 現貨還沒開盤：顯示的是前一天全天
    return jsonify(out)


@app.get("/api/fut/hist")
def fut_hist():
    """看盤／四格看盤走勢圖的 60分K、日K、週K、月K 歷史（今天這根網頁用即時 1 分K 接上去）。
    code = 股票代號；fut = 期交所期貨代碼（TXFK6）＋ spot = 標的股票代號 ＋ name：
    台指期（大台、小台、微台）用資料庫的台指期近月；個股期貨沒有自己的歷史，用標的股票的；其他期貨沒有。
    回傳 bars：[[台北時間秒數, 開, 高, 低, 收, 張／口]]"""
    import re
    import pandas as pd
    from engine import SPECIAL, load_special, resample
    tf = request.args.get("tf", "D")
    code, fut = request.args.get("code", ""), request.args.get("fut", "")
    note = ""
    if fut:
        if fut[:3] in ("TXF", "MXF", "TMF") or fut[:2] in ("MX", "TX"):
            code, note = "TX", "台指期近月歷史（大台、小台、微台走勢一樣，量是大台的）"
        else:
            spot = request.args.get("spot", "")
            if not spot:   # 期交所 MIS 抓不到時沒有標的代號：用群益名稱「台積電11」去掉月份找股票
                nm = re.sub(r"\d+$", "", request.args.get("name", "")).lstrip("小")
                spot = next((c for c, (n, _) in engine.names.items() if n == nm), "")
            if not spot:
                return jsonify(bars=[], error="這個期貨沒有歷史資料")
            code, note = spot, f"標的股票 {engine.names.get(spot, ('',))[0]}({spot}) 的走勢"
    try:
        if tf == "60":
            if code == "TX":
                con = connect()
                df = pd.read_sql("SELECT ts AS date, open, high, low, close, volume FROM intraday WHERE code='TX' AND tf='60' ORDER BY ts", con)
                con.close()
            else:
                import intraday
                df, _ = intraday.get(code, (engine.names.get(code) or ("", "上市"))[1], "60")
            bars = [[int(r.date), r.open, r.high, r.low, r.close, int(r.volume / 1000)] for r in df.tail(400).itertuples()]
        else:
            df = load_special(code) if code in SPECIAL else engine.history(code)
            if df is None or not len(df):
                return jsonify(bars=[], error="查無歷史資料")
            last_date = str(df["date"].iloc[-1])[:10]   # 資料庫最後一天：網頁判斷今天的 K 棒要不要自己接
            if tf in ("W", "M"):
                df = resample(df, tf)
            to_sec = lambda d: int((dt.datetime.strptime(str(d)[:10], "%Y-%m-%d") - dt.datetime(1970, 1, 1)).total_seconds())
            bars = [[to_sec(r.date), r.open, r.high, r.low, r.close, int(r.volume / 1000)] for r in df.tail(400).itertuples()]
    except Exception as e:
        traceback.print_exc()
        return jsonify(bars=[], error=f"{type(e).__name__}: {e}")
    return jsonify(bars=bars, note=note, last_date=locals().get("last_date"))


@app.get("/api/fut/pane")
def fut_pane():
    sym, name = request.args.get("sym", ""), request.args.get("name", "")
    if not capital.ready():
        return jsonify(ready=False, msg=capital.status["msg"])
    c = request.args.get("code")   # code = 直接給群益代碼（股票代號，或期貨 TX00 近月）
    if c and not name:
        name = _names_of([c]).get(c, "")
    if not c and not capital._flist:
        return jsonify(ready=False, msg="群益期貨商品檔還在下載（或帳號沒有簽期貨 API 同意書）")
    c = c or capital._flist.get(sym)
    if not c:
        return jsonify(ready=False, msg=f"群益的期貨商品檔裡找不到 {sym}")
    capital.subscribe_ticks(c)
    if c[:4].isdigit():
        capital.subscribe([c])   # 股票：昨收、昨量要從即時報價拿
    return jsonify(ready=True, pane=_fut_pane(c, name))


@app.post("/api/live/update")
def live_update():
    threading.Thread(target=run_live, daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/settings")
def save_settings():
    p = settings.load()
    body = request.get_json() or {}
    cap = ("capital_enabled", "capital_id", "capital_pwd")
    cap_old = [p.get(k) for k in cap]
    for k, v in body.items():
        if k in ("ai_key", "finmind_token", "capital_pwd") and v == "********":
            continue
        if k in settings.DEFAULTS:
            p[k] = v
    settings.save(p)
    if "dt_branches" in body:
        chips._cache.clear()
    if [p.get(k) for k in cap] != cap_old:   # 帳號或開關改了 → 重新登入群益
        capital.start()
    if set(body) - {"pages", "ai_key", "finmind_token", "ai_model", "bt_capital", "bt_fees", "dt_branches", "chips_time", "chips_margin_time", "fut_time", "mf_days"} - set(cap):   # 只改這些不用重新選股
        engine.screen()
    return jsonify(ok=True)


@app.post("/api/watch/<code>")
def toggle_watch(code):
    p = settings.load()
    wl = p["watchlist"]
    wl.remove(code) if code in wl else wl.append(code)
    settings.save(p)
    engine.screen()
    return jsonify(mine=code in wl)


@app.post("/api/watchlists")
def watchlists_op():
    """自選清單：{op: add, name} 新增／{op: rename, id, name}／{op: del, id}／{op: codes, id, add: [...], remove: [...]}"""
    b = request.get_json() or {}
    p = settings.load()
    wls = p.setdefault("watchlists", [])
    w = next((x for x in wls if x["id"] == b.get("id")), None)
    op = b.get("op")
    if op == "add":
        w = {"id": str(int(time.time() * 1000)), "name": (b.get("name") or "新自選").strip(), "codes": []}
        wls.append(w)
    elif not w:
        return jsonify(error="找不到這個清單"), 404
    elif op == "rename":
        w["name"] = (b.get("name") or w["name"]).strip()
    elif op == "del":
        wls.remove(w)
    elif op == "codes":
        for c in b.get("add", []):
            c = str(c).strip()
            if c and c not in w["codes"]:
                w["codes"].append(c)
        w["codes"] = [c for c in w["codes"] if c not in set(b.get("remove", []))]
    settings.save(p)
    engine.screen()
    return jsonify(ok=True, id=w["id"] if w else None, watchlists=wls)


@app.get("/api/disposals")
def disposals():
    return jsonify(engine.disposal_history())


@app.get("/api/presets")
def presets():
    return jsonify(backtest.PRESETS)


# ---------- 我的策略（存在 data/strategies.json）----------
STRAT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategies.json")


def load_strats():
    try:
        with open(STRAT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_strats(items):
    with open(STRAT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


@app.get("/api/strategies")
def strategies():
    return jsonify(builtin=backtest.PRESETS, mine=load_strats())


@app.post("/api/strategies")
def save_strategy():
    """新增或更新：{name, code, old_name?}（old_name 用於改名）"""
    body = request.get_json() or {}
    name, code, old = (body.get("name") or "").strip(), body.get("code") or "", (body.get("old_name") or "").strip()
    if not name:
        return jsonify(error="請輸入策略名稱")
    if name in backtest.PRESETS:
        return jsonify(error="這個名稱跟內建範本重複，請換一個")
    try:
        backtest.compile_strategy(code)
    except SyntaxError as e:
        return jsonify(error=f"程式碼語法錯誤（第 {e.lineno} 行）：{e.msg}")
    items = load_strats()
    if old and old != name and any(s["name"] == name for s in items):
        return jsonify(error="已經有同名的策略")
    items = [s for s in items if s["name"] not in (old, name)]
    items.append({"name": name, "code": code, "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
    save_strats(sorted(items, key=lambda s: s["name"]))
    return jsonify(ok=True)


@app.post("/api/strategies/delete")
def delete_strategy():
    name = ((request.get_json() or {}).get("name") or "").strip()
    save_strats([s for s in load_strats() if s["name"] != name])
    return jsonify(ok=True)


@app.post("/api/backtest")
def run_backtest():
    body = request.get_json() or {}
    p = settings.load()
    scope = body.get("scope", "one")
    if scope == "one":
        codes = [body.get("code")]
    elif scope == "disp":
        codes = sorted({r["code"] for r in engine.disposal_history()})
    else:
        codes = [c for c in engine.groups if engine_mod.is_common_stock(c, p)]
    cfg = {"capital": float(body.get("capital") or p["bt_capital"]), "fees": bool(body.get("fees", p["bt_fees"])),
           "disposals": engine.disposal_periods()}
    years = float(body.get("years") or 0)      # 0 = 全部歷史
    if years > 0:
        cfg["since"] = (dt.date.today() - dt.timedelta(days=int(365 * years))).isoformat()
    try:
        res = backtest.run(engine.history, codes, body.get("source", ""), cfg)
    except SyntaxError as e:
        return jsonify(error=f"程式碼語法錯誤（第 {e.lineno} 行）：{e.msg}")
    except Exception as e:
        return jsonify(error=f"{type(e).__name__}: {e}")
    if scope != "one":
        res["summary"].pop("max_dd", None)   # 多檔同時持有時，單一資金的回撤沒有意義
        res["summary"].pop("max_dd_pct", None)
    return jsonify(res)


@app.post("/api/chat")
def chat():
    body = request.get_json() or {}
    p = settings.load()
    try:
        text = ai.chat(body.get("messages", []), body.get("context"), p.get("ai_key", ""), p.get("ai_model") or ai.MODEL)
        return jsonify(text=text)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=ai.error_message(e))


# ---------- 漲停隔日統計 ----------
lu_job = {"running": False, "msg": "", "error": None}


def run_limitup(fetch5m):
    if lu_job["running"]:
        return
    lu_job.update(running=True, msg="開始…", error=None)
    try:
        if fetch5m:
            limitup.fetch_5m(lu_job)
        limitup.compute(lu_job)
    except Exception as e:
        traceback.print_exc()
        lu_job.update(error=str(e), msg="失敗")
    finally:
        lu_job["running"] = False


@app.get("/api/limitup")
def limitup_get():
    c = limitup.load_cache()
    return (jsonify(c), 200) if c else (jsonify(error="還沒有統計資料，請按「重新統計」"), 404)


@app.get("/api/limitup/status")
def limitup_status():
    return jsonify(lu_job)


@app.post("/api/limitup/compute")
def limitup_compute():
    body = request.get_json() or {}
    threading.Thread(target=run_limitup, args=(bool(body.get("fetch5m")),), daemon=True).start()
    return jsonify(ok=True)


# ---------- 籌碼整理 ----------
mtot_job = {"day": None, "last_try": None}
chips_job = {"running": False, "msg": "", "progress": {}, "error": None, "last": None, "last_try": {}}


fut_job = {"running": False, "last_try": None}
snap_job = {"running": False, "day": None, "msg": "", "last": None}


def run_snap():
    snap_job.update(running=True, msg="抓取中…")
    try:
        r = warrants.snapshot(snap_job)
        snap_job["last"] = r
        snap_job["msg"] = "完成" if not r.get("error") else r["error"]
    except Exception as e:
        traceback.print_exc()
        snap_job["msg"] = f"失敗：{e}"
    finally:
        snap_job["running"] = False


def run_fut():
    fut_job["running"] = True
    try:
        options.update()
        market_brief.report()
    except Exception:
        traceback.print_exc()
    finally:
        fut_job["running"] = False


def chips_status_dict():
    st = chips.status()
    st["eve_done"] = st["eve_done"] and (options.status()["inst"][1] or "") >= dt.date.today().isoformat()
    return st


def run_chips(days_back, broker_days, kinds=None):
    if chips_job["running"]:
        return
    chips_job.update(running=True, error=None, progress={}, msg="開始…")
    try:
        if not kinds or "inst" in kinds:
            chips_job["progress"]["msg"] = "抓取選擇權未平倉…"
            options.update(progress=chips_job["progress"])
        chips.update(days_back, broker_days, chips_job["progress"], **({"kinds": kinds} if kinds else {}))
        if not kinds or "broker" in kinds:
            chips_job["progress"]["msg"] = "抓取權證分點…"
            warrants.update(days_back=4, progress=chips_job["progress"])
        chips_job["progress"]["msg"] = "整理報表…"
        chips.report()                       # 先算好，打開頁面比較快
        market_brief.report()
        chips_job["last"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        chips_job["msg"] = "完成"
    except Exception as e:
        traceback.print_exc()
        chips_job.update(error=str(e), msg="失敗")
    finally:
        chips_job["running"] = False


@app.get("/api/chips")
def chips_get():
    try:
        return jsonify(chips.report(request.args.get("date") or None))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/chips/inst_range")
def chips_inst_range():
    a = request.args
    try:
        return jsonify(chips.inst_range(a.get("who", "fi"), a.get("start") or None, a.get("end") or None, etf=a.get("etf", "1") != "0"))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/options")
def options_get():
    try:
        return jsonify(options.report(request.args.get("date") or None))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/broker/<code>")
def broker_stock(code):
    try:
        return jsonify(broker.stock(code, int(request.args.get("days") or 1)))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/mainforce/<code>")
def mainforce(code):
    try:
        return jsonify(broker.mainforce(code, int(request.args.get("n") or settings.load()["mf_days"])))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}", rows=[])


@app.get("/api/broker/<code>/hist")
def broker_hist(code):
    a = request.args
    try:
        return jsonify(broker.hist(code, a.get("b"), a.get("bhid"), float(a.get("years") or 1)))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/brief")
def brief_get():
    try:
        return jsonify(market_brief.report(request.args.get("date") or None))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


_wave_cache = {"key": None, "data": None}


@app.get("/api/waves")
def waves_get():
    con = connect()
    key = con.execute("SELECT (SELECT MAX(date) FROM fut_tx), (SELECT MAX(ts) FROM intraday WHERE code='TX')").fetchone()
    con.close()
    try:
        if _wave_cache["key"] != key:
            _wave_cache.update(key=key, data=waves.analyze())
        return jsonify(_wave_cache["data"])
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


_setl_cache = {"key": None, "data": None}


@app.get("/api/settlement")
def settlement_get():
    con = connect()
    key = con.execute("SELECT (SELECT MAX(date) FROM taiex_k), (SELECT MAX(date) FROM fut_tx)").fetchone()
    con.close()
    try:
        if _setl_cache["key"] != key:
            _setl_cache.update(key=key, data=settlement.analyze())
        return jsonify(_setl_cache["data"])
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/settle_tail")
def settle_tail_get():
    try:
        return jsonify(settle_tail.analyze())
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/settle_trades")
def settle_trades_get():
    return jsonify(settle_tail.trades_load())


@app.post("/api/settle_trades")
def settle_trades_add():
    try:
        return jsonify(ok=True, rec=settle_tail.trades_add(request.get_json() or {}))
    except Exception as e:
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.delete("/api/settle_trades/<rid>")
def settle_trades_delete(rid):
    settle_tail.trades_delete(rid)
    return jsonify(ok=True)


@app.get("/api/warrants")
def warrants_get():
    try:
        return jsonify(warrants.report(request.args.get("date") or None))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/warrants/branch")
def warrants_branch():
    try:
        return jsonify(warrants.branch_history(request.args.get("name", "")))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.get("/api/warrants/snap")
def warrants_snap():
    try:
        r = warrants.snap_report()
        r["job"] = {k: v for k, v in snap_job.items() if k != "day"}
        r["status"] = warrants.status()
        return jsonify(r)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"{type(e).__name__}: {e}")


@app.post("/api/warrants/snap")
def warrants_snap_now():
    if not snap_job["running"]:
        threading.Thread(target=run_snap, daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/options/update")
def options_update_now():
    if not fut_job["running"]:
        threading.Thread(target=run_fut, daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/options/status")
def options_status():
    return jsonify(running=fut_job["running"], **options.status())


# ---------- 選擇權大分頁 › 歷史資料（期交所逐筆 → 1 分K）----------
@app.get("/api/opt/hist/days")
def opt_hist_days():
    import optpage
    return jsonify(optpage.days())


@app.get("/api/opt/live")
def opt_live():
    import optlive
    if request.args.get("stop"):
        optlive.stop()
        return jsonify(ok=True)
    try:
        c = request.args.get("center")
        return jsonify(optlive.chain(request.args.get("key") or None, float(c) if c else None))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"讀取失敗：{e}", exps=[])


@app.get("/api/opt/lottery")
def opt_lottery():
    import optmodel
    try:
        return jsonify(optmodel.lottery())
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"回測失敗：{e}")


@app.get("/api/opt/hist")
def opt_hist():
    import optpage
    try:
        return jsonify(optpage.hist(request.args.get("date", ""), request.args.get("contract") or None,
                                    night=request.args.get("night") == "1"))
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=f"讀取失敗：{e}")


@app.get("/api/chips/status")
def chips_status():
    j = {k: v for k, v in chips_job.items() if k != "last_try"}
    j.update(chips.status())
    j["opt"] = options.status()
    j["eve_done"] = j["eve_done"] and (j["opt"]["inst"][1] or "") >= dt.date.today().isoformat()
    return jsonify(j)


@app.post("/api/chips/update")
def chips_update():
    days = int((request.get_json() or {}).get("days") or 7)
    threading.Thread(target=run_chips, args=(days, 120 if days > 120 else None), daemon=True).start()
    return jsonify(ok=True)


# ---------- 想法（隨手想到、回測過的研究紀錄，存在 data/ideas.json）----------
IDEAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ideas.json")


def load_ideas():
    try:
        with open(IDEAS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_ideas(items):
    with open(IDEAS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


@app.get("/api/ideas")
def ideas_get():
    return jsonify(sorted(load_ideas(), key=lambda x: x.get("date", ""), reverse=True))


@app.post("/api/ideas")
def ideas_add():
    """新增／修改：{id?, title, question, status?}；回測結果（tables 等）由 Claude 寫入"""
    body = request.get_json() or {}
    items = load_ideas()
    if body.get("id"):
        for x in items:
            if x["id"] == body["id"]:
                for k in ("title", "question", "status", "my_note", "category"):
                    if k in body:
                        x[k] = body[k]
    else:
        if not (body.get("title") or "").strip():
            return jsonify(error="請輸入想法")
        items.append({"id": "i" + dt.datetime.now().strftime("%Y%m%d%H%M%S"), "date": dt.date.today().isoformat(),
                      "title": body["title"].strip(), "question": (body.get("question") or "").strip(), "status": "待回測",
                      "page": body.get("page") or "limitup", "category": (body.get("category") or "").strip() or "未分類"})
    save_ideas(items)
    return jsonify(ok=True)


@app.post("/api/ideas/delete")
def ideas_delete():
    i = (request.get_json() or {}).get("id")
    save_ideas([x for x in load_ideas() if x["id"] != i])
    return jsonify(ok=True)


# ---------- 筆記（依日期，存在 data/notes.json）----------
NOTES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "notes.json")


def load_notes():
    try:
        with open(NOTES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@app.get("/api/notes")
def notes_get():
    return jsonify(load_notes())


@app.post("/api/notes")
def notes_save():
    body = request.get_json() or {}
    d, text = (body.get("date") or "")[:10], body.get("text") or ""
    if not d:
        return jsonify(error="沒有日期")
    notes = load_notes()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if text.strip():
        notes[d] = {"text": text, "updated": now}
    else:
        notes.pop(d, None)
    tmp = NOTES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NOTES_PATH)
    return jsonify(ok=True, updated=now)


# ---------- PTT 市場情緒 ----------
mood = {"cache": None, "running": False, "msg": "", "last": None}


def mood_summary():
    if mood["cache"] is None:
        mood["cache"] = ptt.summary()
    return mood["cache"]


def run_mood_update():
    if mood["running"]:
        return
    mood.update(running=True, msg="開始…")
    try:
        con = connect()
        ptt._init(con)
        has = con.execute("SELECT MAX(date) FROM ptt_post").fetchone()[0]
        con.close()
        # 第一次抓近 3 個月；之後只抓最近幾天（今天的盤中、昨天和今天的盤後都會重抓最新推文）
        since = dt.date.today() - dt.timedelta(days=92 if not has else 4)
        ptt.update(since, refetch_recent_days=2, progress=mood)
        mood["cache"] = None
        mood_summary()
        mood["last"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        mood["msg"] = "完成"
    except Exception as e:
        traceback.print_exc()
        mood["msg"] = f"失敗：{e}"
    finally:
        mood["running"] = False


@app.get("/api/sentiment")
def sentiment():
    return jsonify(mood_summary())


@app.get("/api/taiex")
def taiex():
    c = engine.taiex_chart()
    return (jsonify(c), 200) if c else (jsonify(error="還沒有加權指數資料，請先按「計算最新情緒」"), 404)


@app.get("/api/sentiment/status")
def sentiment_status():
    return jsonify({k: mood[k] for k in ("running", "msg", "last")})


@app.get("/api/sentiment/day/<d>")
def sentiment_day(d):
    return jsonify(ptt.day_detail(d))


@app.post("/api/sentiment/compute")
def sentiment_compute():
    threading.Thread(target=run_mood_update, daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/shutdown")
def shutdown():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True)


threading.Thread(target=startup, daemon=True).start()
threading.Thread(target=scheduler, daemon=True).start()
capital.start()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=PORT, threaded=True)
