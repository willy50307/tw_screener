"""群益 API（SKCOM）報價：登入後收即時報價、逐筆成交、五檔，給盤中走勢圖和「即時報價」頁用。
沒安裝 SKCOM、沒填帳號或沒登入成功時，intraday 會自動退回原本的 Yahoo。
只做報價，不做下單。
限制（一般用戶）：即時報價一次最多 100 檔、逐筆＋五檔一次最多 10 檔，所以全市場的「盤中即時」頁還是用證交所 MIS。

需要：群益官網申請 API 權限並跑完驗證小工具、安裝 SKCOM（x64，跟 Python 位元數一樣）、pip install comtypes。
COM 元件只能在建立它的那條執行緒用，所以全部在 _run 這條常駐執行緒裡跑，外面只讀 _quotes / _ticks / _best5。
同一個程式只登入一次（第二次登入群益會回「已登入」或「處理中」），開關只是連上／離開報價主機。"""
import datetime as dt
import json
import os
import threading
import time

import pandas as pd

import settings

DLL = r"E:\api\CapitalAPI_2.13.59\元件\x64\SKCOM.dll"   # 設定裡的 capital_dll 可以改
LOGIN_ALREADY = 2003    # SK_WARNING_LOGIN_ALREADY：已經登入過，不算失敗
READY = 3003            # OnConnection 的 nKind：報價主機準備完成
DISCONNECT = (3002, 3021, 3033)
MAX_TICKS = 10          # 逐筆＋五檔最多同時訂 10 檔
REC_DIR = os.path.join(settings.BASE, "data", "recordings")

status = {"state": "off", "msg": "未啟用"}   # off / connecting / ready / error
_quotes = {}            # code -> 最新報價（z/y/o/h/l/v/t/d/name）
_ticks = {}             # code -> [(台北時間秒數, 價, 量(張), 買價, 賣價, 毫秒)]，只放今天
_best5 = {}             # code -> {"bid": [[價, 量]×5], "ask": [[價, 量]×5], "t": 秒數}
_names = {}             # code -> 股票名稱
_want = set()           # 要訂即時報價的股票（最多 100）
_groups = {}            # 會整組換掉的報價訂閱（例如期貨看盤：name -> set）；跟 _want 合起來最多 100
_pinned = []            # 「即時報價」四格看盤固定訂的逐筆（不會被走勢圖擠掉）
rc = {}                 # 最近一次訂閱的回傳值（代號或 "stocks" -> 回傳）
_flist = {}             # 期貨商品檔：期交所代碼（TXFK6）-> 群益代碼（TX00…），連上後抓一次
_olist = {}             # 選擇權商品檔（臺指 TX 開頭）：群益代碼（TXU46000K6，不帶 AM = 含夜盤）-> 到期日 YYYYMMDD
_cmd = []               # 給 _run 的指令
_lock = threading.Lock()
_thread = None
_keep = []              # 建立過的 COM 物件與事件，留到程式結束（被別的執行緒回收會讓整個 App 當掉）
_want_on = False        # 開關：要不要連報價主機
_cred = None            # (帳號, 密碼)，start() 時放進來
_login_req = False      # start() 要求登入一次
_rec = {"file": None, "name": None, "codes": [], "start": None, "n": 0}


def _sec(date, hms):
    """群益的 nDate=20261028、nTimehms=93001 → 「台北時間當作 UTC」的秒數（跟 intraday 表一致）"""
    d = dt.datetime.strptime(f"{date}{hms:06d}", "%Y%m%d%H%M%S")
    return int((d - dt.datetime(1970, 1, 1)).total_seconds())


def _now_sec():
    return int((dt.datetime.now() - dt.datetime(1970, 1, 1)).total_seconds())


def _write(obj):
    f = _rec["file"]
    if f and obj.get("c") in _rec["codes"]:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        _rec["n"] += 1


class _Events:
    """SKQuoteLib 事件。價格是整數，要除以 10^sDecimal"""

    def __init__(self, quote):
        self.q = quote
        self.idx = {}   # (市場, 索引) -> (代號, 小數位數)

    def _stock(self, m, i):
        k = (m, i)
        if k not in self.idx:
            st, code = self.q.SKQuoteLib_GetStockByIndexLONG(m, i, _skstock())
            if code != 0:
                return None, None, None
            self.idx[k] = (st.bstrStockNo, 10 ** st.sDecimal)
            _names[st.bstrStockNo] = st.bstrStockName
        return self.idx[k] + (None,)

    def OnConnection(self, nKind, nCode):
        if nKind == READY:
            status.update(state="ready", msg="群益報價已連線")
            with _lock:
                _cmd.append(("resub", None))
        elif nKind in DISCONNECT and _want_on:
            status.update(state="error", msg=f"群益報價斷線（{nKind}），稍後自動重連")

    def OnNotifyQuoteLONG(self, sMarketNo, nIndex):
        st, code = self.q.SKQuoteLib_GetStockByIndexLONG(sMarketNo, nIndex, _skstock())
        if code != 0:
            return
        k = 10 ** st.sDecimal
        z = st.nClose / k
        if z <= 0:
            if sMarketNo != 3:     # 選擇權今天沒成交也要留著（買賣價、參考價、未平倉）
                return
            z = None
        now = dt.datetime.now()
        _names[st.bstrStockNo] = st.bstrStockName
        _quotes[st.bstrStockNo] = {"code": st.bstrStockNo, "name": st.bstrStockName, "z": z, "y": st.nRef / k,
                                   "o": st.nOpen / k or z, "h": st.nHigh / k or z, "l": st.nLow / k or z, "v": st.nTQty,
                                   "yv": st.nYQty, "bid": st.nBid / k, "ask": st.nAsk / k, "oi": st.nFutureOI,
                                   "t": now.strftime("%H:%M:%S"), "d": now.strftime("%Y%m%d")}

    def OnNotifyStockList(self, sMarketNo, bstrStockData):
        # 期貨商品檔：「代碼,名稱,最後交易日,交易所代碼,跳動點,幣別;」一筆一個分號，## 開頭代表結束
        if sMarketNo == 3:   # 選擇權：TXO 月選、TX1/TX2… 週三、TXU/TXV… 週五；只留臺指、不帶 AM 的
            for rec in bstrStockData.replace("\n", ";").split(";"):
                f = [x.strip() for x in rec.split(",")]
                if len(f) > 3 and f[0].startswith("TX") and not f[0].endswith("AM") and f[2].isdigit() and len(f[2]) == 8:
                    _olist[f[0]] = f[2]
            return
        if sMarketNo != 2:
            return
        for rec in bstrStockData.replace("\n", ";").split(";"):
            f = [x.strip() for x in rec.split(",")]
            if len(f) > 3 and f[3] and not f[0].startswith("##"):
                if f[0].endswith("AM") and f[3] in _flist:   # TX11AM = 只有日盤的行情，要的是含夜盤的 TX11
                    continue
                _flist[f[3]] = f[0]
                _names.setdefault(f[0], f[1])

    def _tick(self, live, sMarketNo, nIndex, nPtr, nDate, nTimehms, nTimemillismicros, nBid, nAsk, nClose, nQty, nSimulate):
        if nSimulate:          # 試撮不算
            return
        code, k, _ = self._stock(sMarketNo, nIndex)
        if not code:
            return
        t = (_sec(nDate, nTimehms), nClose / k, nQty, nBid / k, nAsk / k, nTimemillismicros // 1000)
        _ticks.setdefault(code, []).append(t)
        if live:
            _write({"k": "t", "c": code, "t": t[0], "ms": t[5], "p": t[1], "q": t[2], "b": t[3], "a": t[4]})

    def OnNotifyTicksLONG(self, *a):
        self._tick(True, *a)

    def OnNotifyHistoryTicksLONG(self, *a):
        self._tick(False, *a)

    def OnNotifyBest5LONG(self, sMarketNo, nStockIdx, *v):
        # v：買1價,買1量…買5價,買5量,延伸買,延伸買量,賣1價,賣1量…賣5價,賣5量,延伸賣,延伸賣量,試撮
        if v[-1]:
            return
        code, k, _ = self._stock(sMarketNo, nStockIdx)
        if not code:
            return
        bid = [[v[i] / k, v[i + 1]] for i in range(0, 10, 2)]
        ask = [[v[i] / k, v[i + 1]] for i in range(12, 22, 2)]
        b = _best5[code] = {"bid": bid, "ask": ask, "t": _now_sec()}
        _write({"k": "b", "c": code, "t": b["t"], "bid": bid, "ask": ask})


class _Reply:
    """登入前一定要註冊公告事件，並回傳 -1（群益文件 3-2）"""

    def OnReplyMessage(self, bstrUserID, bstrMessages):
        return -1


def _skstock():
    import comtypes.gen.SKCOMLib as sk
    return sk.SKSTOCKLONG()


def _pump():
    """COM 事件要靠訊息迴圈才會進來"""
    import ctypes
    from ctypes import wintypes
    msg = wintypes.MSG()
    user32 = ctypes.windll.user32
    while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _run():
    try:
        import comtypes
        import comtypes.client as cc
    except ImportError:
        status.update(state="error", msg="還沒安裝 comtypes（pip install comtypes）")
        return
    comtypes.CoInitialize()   # 不呼叫 CoUninitialize：_keep 裡的物件要活到程式結束
    try:   # SKCOM 沒註冊 ProgID，只能從 dll 讀型別庫、用 CLSID 建立
        sk = cc.GetModule(settings.load().get("capital_dll") or DLL)
        center = cc.CreateObject(sk.SKCenterLib)
        reply = cc.CreateObject(sk.SKReplyLib)
        quote = cc.CreateObject(sk.SKQuoteLib)
    except Exception:
        status.update(state="error", msg="找不到 SKCOM 元件，請先安裝群益 API 並註冊 SKCOM.dll")
        return
    _keep.append((center, reply, quote))
    center.SKCenterLib_SetLogPath(os.path.join(settings.BASE, "data", "CapitalLog"))
    _keep.append([cc.GetEvents(reply, _Reply()), cc.GetEvents(quote, _Events(quote))])
    msg = center.SKCenterLib_GetReturnCodeMessage

    global _login_req
    logged, connected, retry_at = False, False, 0
    stuck_since, stuck_tries = None, 0
    page = {}     # 逐筆：code -> 頁碼 0~9（一頁一檔）
    while True:
        try:
            _pump()
            # 卡在「連線中」：群益每天早上 7:30 會斷線重連，有時只回 3001（已連線）一直等不到 3003（報價準備好）。
            # 等 40 秒還沒好就離開再重連；試 2 次還不行，同一個程式就救不回來了（10/30 實測），只能整個選股王重開
            if _want_on and connected and status["state"] == "connecting":
                stuck_since = stuck_since or time.time()
                if time.time() - stuck_since > 40:
                    stuck_since = None
                    stuck_tries += 1
                    if stuck_tries > 2:
                        status.update(state="error", msg="群益報價主機一直連不上，自動重開選股王中…")
                        print("capital:", status["msg"], flush=True)
                        _restart_app()
                    status.update(state="error", msg=f"群益報價主機沒回應，第 {stuck_tries} 次重連")
                    retry_at = 0
            elif status["state"] == "ready":
                stuck_since, stuck_tries = None, 0
            if _want_on and not logged and _login_req:   # 只在按開關／改帳號時登入一次（群益失敗 5 次要重開）
                _login_req = False
                status.update(state="connecting", msg="登入群益中…")
                code = center.SKCenterLib_LoginSetQuote(_cred[0], _cred[1], "Y")
                if code in (0, LOGIN_ALREADY):
                    logged = True
                else:
                    status.update(state="error", msg=f"群益登入失敗：{msg(code)}（{code}）")
                    print("capital:", status["msg"], flush=True)
            if _want_on and logged and (not connected or (status["state"] == "error" and time.time() > retry_at)):
                if connected:
                    quote.SKQuoteLib_LeaveMonitor()
                status.update(state="connecting", msg="連線報價主機中…")
                page.clear()
                code = quote.SKQuoteLib_EnterMonitorLONG()
                connected = True
                retry_at = time.time() + 15
                if code != 0:
                    status.update(state="error", msg=f"連報價主機失敗：{msg(code)}（{code}），稍後重試")
            if not _want_on and connected:
                quote.SKQuoteLib_LeaveMonitor()
                connected = False
                page.clear()
            if not _want_on and status["state"] != "off":
                status.update(state="off", msg="已關閉（群益帳號仍登入中）" if logged else "未啟用")
            with _lock:
                todo = list(dict.fromkeys(_cmd))   # 去掉重複的指令
                _cmd.clear()
            if status["state"] != "ready":
                with _lock:   # 還沒連上：留著等連上再做（resub 會重訂全部）
                    _cmd[:0] = [x for x in todo if x[0] != "resub"]
                time.sleep(0.05)
                continue
            for kind, arg in todo:
                if kind == "resub":
                    page.clear()
                    if _all_want():
                        quote.SKQuoteLib_RequestStocks(1, ",".join(_all_want()))
                    for c in _pinned:
                        _cmd.append(("ticks", c))
                    if not _flist:
                        quote.SKQuoteLib_RequestStockList(2)
                    if not _olist:
                        quote.SKQuoteLib_RequestStockList(3)
                elif kind == "stocks":   # 只有一頁（固定帶 1），最多 100 檔，每次帶完整清單
                    rc["stocks"] = quote.SKQuoteLib_RequestStocks(1, ",".join(_all_want()))
                elif kind == "ticks" and arg not in page:
                    if len(page) >= MAX_TICKS:   # 滿了：退掉最早訂、而且不是四格看盤的那檔
                        old = next((c for c in page if c not in _pinned), None)
                        if old is None:
                            continue
                        quote.SKQuoteLib_CancelRequestTicks(old)
                        n = page.pop(old)
                    else:
                        n = min(set(range(MAX_TICKS)) - set(page.values()))
                    _ticks.pop(arg, None)   # 訂閱後群益會把今天的逐筆全部回補，先清掉避免重複
                    page[arg] = n
                    rc[arg] = quote.SKQuoteLib_RequestTicks(n, arg)   # 回傳值留給 /api/capital 看（訂不到時查原因）
            time.sleep(0.05)
        except Exception as e:
            status.update(state="error", msg=f"群益：{type(e).__name__}: {e}")
            print("capital:", status["msg"], flush=True)
            time.sleep(2)


def _restart_app():
    """另外開一個小程式：等這個選股王結束、5288 埠空出來後再重新啟動 app.py，然後結束自己"""
    import subprocess
    import sys
    record_stop()
    app = os.path.join(settings.BASE, "app.py")
    helper = ("import os,socket,subprocess,sys,time\n"
              "for _ in range(60):\n"
              "    s=socket.socket()\n"
              "    busy=s.connect_ex(('127.0.0.1',5288))==0\n"
              "    s.close()\n"
              "    if not busy: break\n"
              "    time.sleep(1)\n"
              f"log=open({os.path.join(settings.BASE, 'data', 'app.log')!r},'a',encoding='utf-8')\n"
              f"subprocess.Popen([sys.executable,{app!r}],cwd={settings.BASE!r},stdout=log,stderr=log,"
              "env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=0x08000000)\n")
    subprocess.Popen([sys.executable, "-c", helper], cwd=settings.BASE, creationflags=0x08000000 | 0x00000008)
    os._exit(0)


def start():
    """App 啟動或設定改了之後呼叫；沒勾啟用或沒填帳號就不連"""
    global _thread, _want_on, _cred, _login_req
    p = settings.load()
    if not p.get("capital_enabled") or not p.get("capital_id") or not p.get("capital_pwd"):
        stop()
        return
    _cred = (p["capital_id"], p["capital_pwd"])
    _want_on = _login_req = True
    if not (_thread and _thread.is_alive()):
        _thread = threading.Thread(target=_run, daemon=True)
        _thread.start()


def stop():
    global _want_on
    _want_on = False
    if not (_thread and _thread.is_alive()):
        status.update(state="off", msg="未啟用")


def ready():
    return status["state"] == "ready"


def subscribe(codes):
    """訂閱即時報價（最多 100 檔）"""
    new = set(codes) - _want
    if not new:
        return
    _want.update(new)
    with _lock:
        _cmd.append(("stocks", None))


def _all_want():
    """股票（_want，數字代號排前面不會被擠掉）＋各組訂閱，最多 100 檔"""
    g = set().union(*_groups.values()) - _want if _groups else set()
    return (sorted(_want) + sorted(g))[:100]


def subscribe_group(name, codes):
    """整組換掉的報價訂閱（期貨看盤用）：上次這組有、這次沒有的就不再訂"""
    codes = set(c for c in codes if c)
    if _groups.get(name) == codes:
        return
    _groups[name] = codes
    with _lock:
        _cmd.append(("stocks", None))


def subscribe_ticks(code):
    with _lock:
        _cmd.append(("ticks", code))


def pin(codes):
    """五格看盤：固定訂這幾檔的逐筆＋五檔（最多 MAX_TICKS-1 檔，留一個給看盤／個股走勢圖）"""
    _pinned[:] = [c for c in codes if c][:MAX_TICKS - 1]
    for c in _pinned:
        subscribe_ticks(c)


def quotes(codes):
    """回傳跟 live._quotes_mis 一樣格式的 DataFrame；還沒收到的股票不會出現"""
    subscribe(codes)
    return pd.DataFrame([_quotes[c] for c in codes if c in _quotes])


def tick_stats(ticks):
    """逐筆 → 超級贏家右上角那張表要的數字；明細每筆附上累計總量"""
    if not ticks:
        return {}, []
    tot = amt = inner = outer = 0
    hi, lo, cum = -1e18, 1e18, []
    for t in ticks:
        p, q, b, a = t[1], t[2], t[3], t[4]
        tot += q
        amt += p * q
        hi, lo = max(hi, p), min(lo, p)
        if a > 0 and p >= a:
            outer += q
        elif b > 0 and p <= b:
            inner += q
        cum.append(tot)
    st = {"open": ticks[0][1], "high": hi, "low": lo, "last": ticks[-1][1], "lastq": ticks[-1][2], "t": ticks[-1][0],
          "total": tot, "amount": amt * 1000, "vwap": amt / tot if tot else None, "inner": inner, "outer": outer}
    return st, cum


def bars_1m(code, ticks=None):
    """逐筆組成 1 分K：date（秒數，分鐘開頭）、open/high/low/close/volume（股）。沒有就回空表"""
    if ticks is None:
        subscribe_ticks(code)
        ticks = list(_ticks.get(code, []))
    if not ticks:
        return pd.DataFrame()
    df = pd.DataFrame([t[:3] for t in ticks], columns=["ts", "price", "qty"])
    df["date"] = df["ts"] // 60 * 60
    g = df.groupby("date")
    return pd.DataFrame({"open": g["price"].first(), "high": g["price"].max(), "low": g["price"].min(),
                         "close": g["price"].last(), "volume": g["qty"].sum() * 1000}).reset_index()


# ---------- 錄影：把四格看盤的逐筆、五檔變化存成檔案，盤後重播 ----------

def record_start(codes):
    record_stop()
    os.makedirs(REC_DIR, exist_ok=True)
    name = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    f = open(os.path.join(REC_DIR, name + ".jsonl"), "w", encoding="utf-8", buffering=1)   # 一行寫一次，當掉也不會掉資料
    slots = [c or "" for c in codes][:10]   # 保留格子位置（A 組 0~4、B 組 5~9），重播才知道哪檔在哪格
    codes = [c for c in slots if c]
    f.write(json.dumps({"k": "meta", "codes": codes, "slots": slots, "names": {c: _names.get(c, "") for c in codes},
                        "ref": {c: (_quotes.get(c) or {}).get("y") for c in codes}, "t": _now_sec()}, ensure_ascii=False) + "\n")
    for c in codes:   # 開始錄之前今天已經有的逐筆也先存一份，重播時走勢圖才完整
        f.write(json.dumps({"k": "h", "c": c, "ticks": list(_ticks.get(c, []))}) + "\n")
        if c in _best5:
            b = _best5[c]
            f.write(json.dumps({"k": "b", "c": c, "t": b["t"], "bid": b["bid"], "ask": b["ask"]}) + "\n")
    _rec.update(file=f, name=name, codes=codes, start=_now_sec(), n=0)
    return name


def record_stop():
    f = _rec["file"]
    _rec.update(file=None, codes=[])
    if f:
        f.close()


def record_status():
    return {"on": _rec["file"] is not None, "name": _rec["name"], "codes": _rec["codes"], "start": _rec["start"], "n": _rec["n"]}


def recordings():
    if not os.path.isdir(REC_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(REC_DIR), reverse=True):
        if fn.endswith(".jsonl"):
            p = os.path.join(REC_DIR, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    meta = json.loads(f.readline())
            except Exception:
                continue
            out.append({"name": fn[:-6], "codes": meta.get("codes", []), "names": meta.get("names", {}), "size": os.path.getsize(p)})
    return out


def recording(name):
    p = os.path.join(REC_DIR, os.path.basename(name) + ".jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]
