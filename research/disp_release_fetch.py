"""補抓處置股的分點買賣超（MoneyDJ zco，買超/賣超前 15）：每次處置抓「最後一天」和「整段處置期間」兩份。
只寫 research/out/disp_release_broker.json（已抓過的跳過）。
用法：python research/disp_release_fetch.py
"""
import json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.argv = sys.argv[:1]
import broker  # noqa: E402

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "disp_release.py"), encoding="utf-8").read()
exec(src.split("if __name__")[0].replace("__file__", repr(os.path.join(BASE, "research", "disp_release.py"))))
OUT = BRK          # exec 會蓋掉 OUT，這裡改回分點資料檔

ev = events()
ev = ev[ev.rule == "new"]
done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
for k, r in enumerate(ev.itertuples()):
    g = px[r.code]
    inside = g[(g.date >= r.start) & (g.date <= r.end)].date.tolist()
    for tag, a, b in (("last", inside[-1], inside[-1]), ("all", inside[0], inside[-1])):
        key = f"{r.code}|{r.start}|{tag}"
        if key in done:
            continue
        h = broker._get("/z/zc/zco/zco.djhtm", {"a": r.code, "e": a, "f": b})
        last, rows = broker._parse_stock(h or "")
        done[key] = [{"branch": x["branch"], "net": x["net"]} for x in rows] if last else None
        time.sleep(0.3)
    if k % 10 == 0:
        json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(k, len(ev), flush=True)
json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("done", len(done))
