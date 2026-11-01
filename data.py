"""抓資料：證交所(上市)、櫃買中心(上櫃) 每日收盤行情 + 處置股 / 注意股。全部是官方免費公開資料，不需要 API key。"""
import datetime as dt
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from settings import BASE

DB_PATH = os.path.join(BASE, "data", "stocks.db")
HEADERS = {"User-Agent": "Mozilla/5.0"}
_lock = threading.Lock()


def _num(x):
    x = str(x).replace(",", "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def _get_json(url, params=None):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.encoding = "utf-8"
            return r.json()
        except Exception as e:
            print(f"  連線失敗({attempt + 1}/3): {e}")
            time.sleep(5 * (attempt + 1))
    return None


# ---------- 每日行情 ----------

def fetch_twse(d: dt.date):
    """上市：回傳 [(code, name, open, high, low, close, volume_shares), ...]，非交易日回傳 []"""
    j = _get_json("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                  {"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    if not j or j.get("stat") != "OK":
        return [] if j else None
    for t in j.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            i = {k: f.index(k) for k in f}
            return [(r[i["證券代號"]].strip(), r[i["證券名稱"]].strip(), _num(r[i["開盤價"]]), _num(r[i["最高價"]]),
                     _num(r[i["最低價"]]), _num(r[i["收盤價"]]), _num(r[i["成交股數"]])) for r in t["data"]]
    return []


def fetch_tpex(d: dt.date):
    """上櫃：格式同 fetch_twse"""
    j = _get_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                  {"date": d.strftime("%Y/%m/%d"), "type": "EW", "response": "json"})
    if not j:
        return None
    if j.get("date") != d.strftime("%Y%m%d"):
        return []
    for t in j.get("tables", []):
        f = [x.strip() for x in (t.get("fields") or [])]
        if "代號" in f and "收盤" in f:
            i = {k: f.index(k) for k in f}
            return [(r[i["代號"]].strip(), r[i["名稱"]].strip(), _num(r[i["開盤"]]), _num(r[i["最高"]]),
                     _num(r[i["最低"]]), _num(r[i["收盤"]]), _num(r[i["成交股數"]])) for r in t["data"]]
    return []


# ---------- 資料庫 ----------

def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS prices(code TEXT, date TEXT, market TEXT, name TEXT,
                   open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(code, date))""")
    con.execute("CREATE TABLE IF NOT EXISTS fetched(market TEXT, date TEXT, n INTEGER, PRIMARY KEY(market, date))")
    return con


def _update_market(con, market, fetcher, dates, delay, progress):
    today = dt.date.today()
    done = {r[0] for r in con.execute("SELECT date FROM fetched WHERE market=?", (market,))}
    todo = [d for d in dates if d.isoformat() not in done]
    for k, d in enumerate(todo, 1):
        progress[market] = [k, len(todo)]
        rows = fetcher(d)
        if rows is None:
            print(f"  [{market}] {d} 抓取失敗，下次再試")
            continue
        rows = [r for r in rows if r[5] is not None]  # 當天沒成交的跳過
        with _lock:
            con.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?,?,?)",
                            [(r[0], d.isoformat(), market, r[1], r[2] or r[5], r[3] or r[5], r[4] or r[5], r[5], r[6] or 0)
                             for r in rows])
            # 今天如果還沒公布（空的），不要記錄，下次執行會再抓
            if rows or d < today:
                con.execute("INSERT OR REPLACE INTO fetched VALUES(?,?,?)", (market, d.isoformat(), len(rows)))
            con.commit()
        print(f"  [{market}] {d} {len(rows)} 檔  ({k}/{len(todo)})")
        time.sleep(delay)  # 證交所有流量限制，太快會被暫時封鎖


def update_prices(days_back, progress=None):
    """progress：傳入一個 dict，會即時寫入 {"上市": [第幾天, 共幾天], ...} 給畫面顯示進度"""
    progress = {} if progress is None else progress
    con = connect()
    today = dt.date.today()
    dates = [today - dt.timedelta(days=i) for i in range(days_back, -1, -1)]
    dates = [d for d in dates if d.weekday() < 5]
    print("更新行情資料（第一次會比較久，約 10~15 分鐘；之後每天只抓新的一天）")
    with ThreadPoolExecutor(2) as ex:
        a = ex.submit(_update_market, con, "上市", fetch_twse, dates, 3.0, progress)
        b = ex.submit(_update_market, con, "上櫃", fetch_tpex, dates, 2.0, progress)
        a.result(), b.result()
    con.close()


def load_prices(since=None):
    """since：只讀這天之後的資料（全部歷史很大，選股只需要最近一段）"""
    con = connect()
    if since:
        df = pd.read_sql("SELECT * FROM prices WHERE date >= ? ORDER BY code, date", con, params=(since,))
    else:
        df = pd.read_sql("SELECT * FROM prices ORDER BY code, date", con)
    con.close()
    return df


def load_code(code, since=None):
    """單一股票的完整歷史（給回測、長週期 K 線用）"""
    con = connect()
    q, args = "SELECT * FROM prices WHERE code=?", [code]
    if since:
        q += " AND date >= ?"
        args.append(since)
    df = pd.read_sql(q + " ORDER BY date", con, params=args)
    con.close()
    return df
