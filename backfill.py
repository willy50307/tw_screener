"""
一次抓完全部歷史日K（證交所 2004/2/11 起、櫃買中心 2008/1/2 起）。
  python backfill.py          ← 由新到舊抓，中斷後再執行會接著抓（已抓過的日子會跳過）
進度寫在 data/backfill_status.json，App 右上角會顯示。
執行期間會請 Windows 不要進入睡眠（程式結束自動解除，不會改電腦設定）。
"""
import ctypes
import datetime as dt
import json
import os
import sys
import threading
import time

from data import _lock, connect, fetch_tpex, fetch_twse
from settings import BASE

START = {"上市": dt.date(2004, 2, 11), "上櫃": dt.date(2008, 1, 2)}
DELAY = {"上市": 3.0, "上櫃": 2.0}
STATUS = os.path.join(BASE, "data", "backfill_status.json")
status = {"started": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "markets": {}, "done": False}


def keep_awake(on=True):
    try:   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
    except Exception:
        pass


def save_status():
    with _lock:
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False)


def run_market(con, market, fetcher):
    today = dt.date.today()
    done = {r[0] for r in con.execute("SELECT date FROM fetched WHERE market=?", (market,))}
    dates = [START[market] + dt.timedelta(days=i) for i in range((today - START[market]).days + 1)]
    todo = [d for d in reversed(dates) if d.weekday() < 5 and d.isoformat() not in done]   # 由新到舊
    st = status["markets"][market] = {"done": 0, "total": len(todo), "rows": 0, "current": None, "errors": 0}
    t0 = time.time()
    for k, d in enumerate(todo, 1):
        for attempt in range(6):   # 被暫時封鎖時等一下再試
            rows = fetcher(d)
            if rows is not None:
                break
            st["errors"] += 1
            time.sleep(60 * (attempt + 1))
        if rows is None:
            continue
        rows = [r for r in rows if r[5] is not None]
        with _lock:
            con.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?,?,?)",
                            [(r[0], d.isoformat(), market, r[1], r[2] or r[5], r[3] or r[5], r[4] or r[5], r[5], r[6] or 0)
                             for r in rows])
            if rows or d < today:
                con.execute("INSERT OR REPLACE INTO fetched VALUES(?,?,?)", (market, d.isoformat(), len(rows)))
            con.commit()
        st.update(done=k, rows=st["rows"] + len(rows), current=d.isoformat())
        el = time.time() - t0
        st["eta_min"] = round(el / k * (len(todo) - k) / 60)
        if k % 5 == 0 or k == len(todo):
            save_status()
            print(f"[{market}] {d} {len(rows)} 檔 ({k}/{len(todo)}) 剩約 {st['eta_min']} 分鐘", flush=True)
        time.sleep(DELAY[market])


def main():
    keep_awake(True)
    con = connect()
    con.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date)")
    ths = [threading.Thread(target=run_market, args=(con, m, f)) for m, f in (("上市", fetch_twse), ("上櫃", fetch_tpex))]
    [t.start() for t in ths]
    [t.join() for t in ths]
    status["done"] = True
    status["finished"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    save_status()
    keep_awake(False)
    print("全部完成", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
