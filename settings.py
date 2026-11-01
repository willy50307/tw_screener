"""使用者設定：存在 data/settings.json，App 的「設定」頁面改的就是這裡"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(BASE, "data", "settings.json")

DEFAULTS = {
    # MACD
    "macd_fast": 3,
    "macd_slow": 7,
    "macd_signal": 3,
    "price_source": "DI",        # "DI" = (高+低+2*收)/4；"close" = 收盤價
    # 進場條件
    "shrink_pct": 40,            # 綠柱縮短 % 以上
    "strategies": {"green_shrink": True, "gap_cross": True, "golden_cross": True},
    "dif_filter": True,          # 高檔過熱濾網：DIF / 收盤價 超過上限就不進場
    "max_dif_pct": 0,            # 0 = 快線在 0 軸上方就不進場；TradingView 腳本原本是 1.5
    "entry_rule": "any",         # any = 任一成立；all = 全部成立
    # 篩選
    "min_lots": 500,             # 當日成交量至少幾張
    "min_price": 10,
    "include_etf": False,
    "exclude_disposition": False,
    "watch_pct": 3,              # 明日觀察：明天漲幾 % 以內會觸發
    "watchlist": ["6488"],
    "watchlists": [],            # 自己新增的自選清單 [{id, name, codes}]：個股K 左邊多一個分頁，看盤 › 證券也能選
    # 頁面（App 最上方的分頁）：type = strategy（選股策略畫面）或 blank（空白頁，之後再做內容）
    "pages": [{"id": "macd", "name": "MACD(3,7,3) 單發狙擊版", "type": "strategy", "icon": "📈"},
              {"id": "fut", "name": "看盤", "type": "futures", "icon": "📊"},
              {"id": "disphist", "name": "處置歷史", "type": "disposal", "icon": "🚨"},
              {"id": "mood", "name": "市場情緒", "type": "sentiment", "icon": "🌡️"},
              {"id": "research", "name": "回測數據", "type": "research", "icon": "🔬"},
              {"id": "chips", "name": "籌碼整理", "type": "chips", "icon": "💰"},
              {"id": "notes", "name": "筆記", "type": "notes", "icon": "📝"},
              {"id": "quote", "name": "即時報價", "type": "quote", "icon": "📟"},
              {"id": "opt", "name": "選擇權", "type": "options", "icon": "🎯"}],
    # 即時報價頁：自選股、四格看盤的 8 檔（A 組 0~3、B 組 4~7）
    "rt_watch": [],
    "rt_board": [""] * 8,
    # 籌碼
    "chips_time": "19:00",       # 每天幾點後自動抓三大法人、券商分點
    "chips_margin_time": "22:00",
    "fut_time": "16:00",         # 每天幾點後自動抓台指期、選擇權、加權指數  # 每天幾點後自動抓融資券、借券賣出
    "dt_branches": [],           # 隔日沖分點名單（空的 = 用內建名單）
    # 回測
    "bt_capital": 1000000,
    "bt_fees": False,            # 是否扣手續費 0.1425% ×2、交易稅 0.3%
    # AI 助理（Claude API）
    "ai_key": "",
    "ai_model": "claude-opus-5-5",
    # FinMind（finmindtrade.com，選填；免費網站抓不到的資料才用）
    "finmind_token": "",
    # 群益 API（SKCOM，選填；盤中走勢圖、盤中即時改用群益逐筆。密碼只存在這台電腦的 data/settings.json）
    "capital_enabled": False,
    "capital_id": "",
    "capital_pwd": "",
    # 系統
    "auto_update_time": "15:30", # 每天自動更新時間（空白 = 不自動）
    "chart_days": 160,
    "mf_days": 20,               # K 線「主力買賣超」窗格：累計幾天（1/5/10/20/60）
    "backfill_days": 240,
}


def load():
    d = json.loads(json.dumps(DEFAULTS))
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
        d.update(saved)
        d["strategies"] = {**DEFAULTS["strategies"], **saved.get("strategies", {})}
    except FileNotFoundError:
        pass
    # 10/29 合併：當沖策略研究、想法回測、研究想法 三頁 → 「回測數據」一頁（放在第一個舊頁的位置）
    old = [i for i, pg in enumerate(d["pages"]) if pg.get("type") in ("limitup", "ideas", "btideas")
           or (pg.get("type") == "blank" and pg.get("name") == "想法回測")]
    if old:
        rest = [pg for i, pg in enumerate(d["pages"]) if i not in old]
        if not any(pg.get("type") == "research" for pg in rest):
            rest.insert(old[0], next(dict(pg) for pg in DEFAULTS["pages"] if pg["id"] == "research"))
        d["pages"] = rest
    for k, need in enumerate(DEFAULTS["pages"]):   # 內建頁面（策略、處置歷史）不可被刪除
        if not any(pg.get("id") == need["id"] for pg in d["pages"]):
            d["pages"] = d["pages"][:k] + [need] + d["pages"][k:] if need["id"] == "fut" else d["pages"] + [need]
    for pg in d["pages"]:            # 使用者新增的「盤中即時」空白頁 → 盤中即時頁面
        if pg.get("id") == "fut" and pg.get("name") == "期貨看盤":   # 10/28 改名：期貨＋證券都在這頁
            pg["name"] = "看盤"
        if pg.get("type") == "blank" and pg.get("name") == "盤中即時":
            pg["type"], pg["icon"] = "live", "⚡" if pg.get("icon", "📄") == "📄" else pg["icon"]
    return d


def save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
