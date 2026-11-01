"""把 stocks.db 裡 2025 年以後的行情、籌碼複製到 data/subset.db（給 Claude 在雲端做回測統計用，不會改到 stocks.db）
用法：python export_subset.py"""
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "stocks.db")
DST = os.path.join(BASE, "data", "subset.db")

TABLES = {   # 表格 → 起始日期（MACD 要暖機，行情多抓幾個月）
    "prices": "2024-10-01", "inst": "2025-03-01", "margin": "2025-03-01", "sbl": "2025-03-01",
    "broker": "2025-03-01", "taiex_k": "2024-10-01", "disposal": None, "broker_id": None,
}

t0 = time.time()
if os.path.exists(DST):
    os.remove(DST)
con = sqlite3.connect(DST, uri=True)
con.execute(f"ATTACH DATABASE 'file:///{SRC.replace(os.sep, '/')}?mode=ro' AS s")
have = {r[0] for r in con.execute("SELECT name FROM s.sqlite_master WHERE type='table'")}
for t, since in TABLES.items():
    if t not in have:
        print(f"{t}: 沒有這個表格，略過")
        continue
    cols = [r[1] for r in con.execute(f"PRAGMA s.table_info({t})")]
    where = f" WHERE date >= '{since}'" if since and "date" in cols else ""
    con.execute(f"CREATE TABLE {t} AS SELECT * FROM s.{t}{where}")
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    rng = con.execute(f"SELECT MIN(date), MAX(date) FROM {t}").fetchone() if "date" in cols else ("", "")
    print(f"{t}: {n:,} 筆  {rng[0]} ~ {rng[1]}")
con.commit()
con.execute("DETACH DATABASE s")
con.execute("VACUUM")
con.close()
print(f"完成：{DST}  {os.path.getsize(DST) / 1e6:.0f} MB，花了 {time.time() - t0:.0f} 秒")
