"""抓主力買賣超（MoneyDJ，跟 App K 線「主力買賣超」窗格同一個來源，約 6 年日資料），存到 research/out/mf/<code>.csv。
用法：python research/mf_fetch.py 1802 2330 ...   或   python research/mf_fetch.py --liquid 400（成交值前 N 檔）"""
import os
import sqlite3
import sys
import time

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from data import HEADERS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "mf")
URL = "https://fubon-ebrokerdj.fbs.com.tw/Z/ZC/ZCW/CZKC1.djbcd"


def fetch(code):
    for k in range(3):
        try:
            r = requests.get(URL, params={"a": code, "b": "D", "c": 1440}, headers=HEADERS, timeout=20)
            cols = [x.split(",") for x in r.text.split(";")[0].strip().split(" ")]
            if len(cols) < 16:
                return []
            return [(t.replace("/", "-"), v) for t, v in zip(cols[0], cols[15]) if v not in ("", "-")]
        except Exception:
            time.sleep(2 * (k + 1))
    return []


def liquid_codes(n):
    con = sqlite3.connect(f"file:{os.path.join(BASE, 'data', 'subset.db')}?mode=ro", uri=True)
    rows = con.execute("""SELECT code, AVG(close*volume) a FROM prices WHERE date >= date((SELECT MAX(date) FROM prices), '-60 day')
                          GROUP BY code HAVING code GLOB '[1-9][0-9][0-9][0-9]' ORDER BY a DESC LIMIT ?""", (n,)).fetchall()
    con.close()
    return [r[0] for r in rows]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    codes = liquid_codes(int(sys.argv[2])) if sys.argv[1] == "--liquid" else sys.argv[1:]
    for i, c in enumerate(codes):
        p = os.path.join(OUT, f"{c}.csv")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 86400:
            continue
        try:
            rows = fetch(c)
        except Exception as e:      # 沒有主力資料的股票（格式不同）
            print(i, c, "err", e, flush=True)
            continue
        if rows:
            with open(p, "w", encoding="utf-8") as f:
                f.write("date,mf\n" + "\n".join(f"{d},{v}" for d, v in rows))
        print(i, c, len(rows), rows[-1] if rows else None, flush=True)
        time.sleep(0.4)
