"""App 內的「問 Claude」對話框：呼叫 Claude API（官方 anthropic SDK）。
需要 Claude API 金鑰（到 console.anthropic.com 申請，另外計費，跟 claude.ai 訂閱是分開的）。
金鑰可以在 App 設定裡填，或設成環境變數 ANTHROPIC_API_KEY。"""
import json

import anthropic

from backtest import __doc__ as BACKTEST_DOC

MODEL = "claude-opus-5-5"

SYSTEM = f"""你是「我的選股王」App 裡的助理，使用者是台股投資人，不是程式設計師。請一律用繁體中文、口語化地回答。

這個 App 的功能：
- 每天盤後抓證交所、櫃買中心的行情，用 MACD(3,7,3)「單發狙擊版」策略選股（摸底：綠柱縮短40%且DIF上升；跳空：開盤高於前一日金叉門檻價；金叉：DIF上穿MACD；高檔過熱濾網：DIF/股價上限）。
- MACD 用 (高+低+2×收)/4 計算，跟 XQ / TradingView hlcc4 相同。
- 處置預測：依證交所／櫃買中心 115.08.03 版注意、處置規則估算明日觸發注意的價位，以及還差幾次會被處置。
- 處置歷史：8/10 新制實施後被處置過的股票，以及處置前、處置中、出關後的漲跌。
- 回測：使用者在右側面板寫策略程式碼回測。

回測程式碼格式（使用者要你寫或轉換策略時，請嚴格照這個格式，並放在 ```python 程式碼區塊裡，App 會提供「套用到回測」按鈕）：
{BACKTEST_DOC}
如果使用者貼 TradingView Pine Script，請轉換成上面的格式，並說明哪些地方無法完全對應。

回答原則：
- 你會收到使用者目前畫面的資料（股票、指標、處置狀態、回測結果），請根據這些資料回答，不要編造資料裡沒有的數字。
- 可以分析、解釋、比較，但不要保證獲利；涉及買賣決策時，提醒最終由使用者自行判斷。
- 回答精簡，重點用條列。"""


def chat(messages, context, api_key="", model=MODEL):
    """messages：[{role, content}, ...]（使用者與助理的對話）；context：目前畫面資料（dict）"""
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    msgs = [dict(m) for m in messages if m.get("content")]
    if context and msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] = (f"<目前畫面資料>\n{json.dumps(context, ensure_ascii=False)}\n</目前畫面資料>\n\n"
                               + msgs[-1]["content"])
    with client.beta.messages.stream(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=msgs,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        return "（這個問題 Claude 無法回答，請換個方式問。）"
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "max_tokens":
        text += "\n\n（回答太長被截斷了）"
    return text


def error_message(e):
    if isinstance(e, anthropic.AuthenticationError):
        return "API 金鑰無效，請到「⚙ 設定」重新填寫。"
    if isinstance(e, anthropic.PermissionDeniedError):
        return "這個 API 金鑰沒有權限使用此模型。"
    if isinstance(e, anthropic.RateLimitError):
        return "請求太頻繁或額度用完，請稍後再試，或到 console.anthropic.com 檢查額度。"
    if isinstance(e, anthropic.BadRequestError):
        return f"請求格式錯誤：{e.message}"
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude 伺服器錯誤（{e.status_code}），請稍後再試。"
    if isinstance(e, anthropic.APIConnectionError):
        return "連不上 Claude 伺服器，請檢查網路。"
    if "api_key" in str(e).lower() or "auth" in str(e).lower():
        return "還沒有設定 Claude API 金鑰。請到「⚙ 設定 → AI 助理」填入金鑰（到 console.anthropic.com 申請）。"
    return f"發生錯誤：{e}"
