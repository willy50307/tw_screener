"""補抓三大法人＋融資融券歷史（給回測用），可中斷重跑，已抓過的日子會跳過"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chips
from settings import BASE

since = dt.date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2023-05-01")
prog = {}
st = os.path.join(BASE, "data", "backfill_inst_status.json")


def save():
    with open(st, "w", encoding="utf-8") as f:
        json.dump({"since": since.isoformat(), "progress": prog, "t": dt.datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False)


import threading


def tick():
    while True:
        save()
        threading.Event().wait(30)


threading.Thread(target=tick, daemon=True).start()
chips.update(days_back=(dt.date.today() - since).days, progress=prog, kinds=("inst", "margin"))
prog["msg"] = "完成"
save()
