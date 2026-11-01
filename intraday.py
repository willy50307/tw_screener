"""分K（5分、60分）：從 Yahoo Finance 抓（免帳號；5分K約最近 60 天、60分K約最近 2~3 年），存在資料庫快取。
點開某一檔股票的分K時才抓那一檔，30 分鐘內重複點不會重抓。
有登入群益 API 時，今天的 1 分K（盤中走勢圖）改用群益逐筆組成。"""
import threading
import time

import pandas as pd
import yfinance as yf

import capital
from data import connect

TF = {"1": ("1m", "7d"), "5": ("5m", "60d"), "60": ("60m", "730d")}   # 1 分K：盤中走勢圖用（只有最近 7 天）
TTL = {"1": 60}                                                        # 走勢圖盤中 1 分鐘就可以重抓，其他 30 分鐘
_last = {}
_lock = threading.Lock()


def _ticker(code, market):
    if code == "TAIEX":
        return "^TWII"
    return f"{code}.{'TWO' if market == '上櫃' else 'TW'}"


def get(code, market, tf):
    """回傳 DataFrame：date（台北時間的 Unix 秒數）、open/high/low/close/volume（股）"""
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS intraday(code TEXT, tf TEXT, ts INTEGER, open REAL, high REAL, low REAL,
                   close REAL, volume REAL, PRIMARY KEY(code, tf, ts))""")
    key = (code, tf)
    err = None
    if time.time() - _last.get(key, 0) > TTL.get(tf, 1800):
        try:
            iv, period = TF[tf]
            h = yf.Ticker(_ticker(code, market)).history(period=period, interval=iv, auto_adjust=False)
            if len(h):
                # 時間轉成「台北時間當作 UTC」的秒數，圖上才會顯示 09:00~13:30
                ts = (h.index.tz_convert("Asia/Taipei").tz_localize(None) - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")
                rows = [(code, tf, int(t), float(o), float(hi), float(lo), float(c), float(v))
                        for t, o, hi, lo, c, v in zip(ts, h["Open"], h["High"], h["Low"], h["Close"], h["Volume"]) if c == c]
                with _lock:
                    con.executemany("INSERT OR REPLACE INTO intraday VALUES(?,?,?,?,?,?,?,?)", rows)
                    con.commit()
            _last[key] = time.time()
        except Exception as e:
            err = str(e)
    if tf == "1" and capital.ready():   # 有登入群益：今天的 1 分K 用群益逐筆組，蓋掉 Yahoo 的（Yahoo 會延遲、偶爾缺分鐘）
        b = capital.bars_1m(code)
        if len(b):
            with _lock:
                con.executemany("INSERT OR REPLACE INTO intraday VALUES(?,?,?,?,?,?,?,?)",
                                [(code, tf, int(r.date), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
                                 for r in b.itertuples()])
                con.commit()
            err = None
    df = pd.read_sql("SELECT ts AS date, open, high, low, close, volume FROM intraday WHERE code=? AND tf=? ORDER BY ts",
                     con, params=(code, tf))
    con.close()
    return df, err
