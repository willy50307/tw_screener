// ---------- 右側面板：回測 / 問 AI ----------
window.BT_TRADES = {};
let sidePanel = null, LAST_BT = null, AI_MSGS = [];
const lsGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch(e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch(e) {} };
const esc = s => String(s).replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));

function openSide(p){
  sidePanel = p;
  $("side").classList.add("open");
  $("panelBt").style.display = p === "bt" ? "flex" : "none";
  $("panelAi").style.display = p === "ai" ? "flex" : "none";
  $("panelBr").style.display = p === "br" ? "flex" : "none";
  $("sideTitle").textContent = {bt: "📊 策略回測", ai: "💬 問 Claude", br: "🏦 主力進出"}[p];
  if (p === "br" && window.brShow) brShow();
  document.querySelectorAll("#sideTabs button").forEach(b => b.classList.toggle("on", b.dataset.p === p));
  setTimeout(() => ChartView.resizeAll(), 0);
}
function closeSide(){
  sidePanel = null;
  $("side").classList.remove("open");
  document.querySelectorAll("#sideTabs button").forEach(b => b.classList.remove("on"));
  setTimeout(() => ChartView.resizeAll(), 0);
}
document.querySelectorAll("#sideTabs button").forEach(b => b.onclick = () => sidePanel === b.dataset.p ? closeSide() : openSide(b.dataset.p));
$("sideClose").onclick = closeSide;

// ===== 回測 =====
let PRESETS = {}, MINE = [], CUR_STRAT = null;   // CUR_STRAT：目前載入的「我的策略」名稱
const BLANK_TPL = `# 我的新策略
# 資料：open high low close volume hlcc4 date
# 函式：ema(x,n) sma(x,n) rsi(x,n) highest(x,n) lowest(x,n) crossover(a,b) crossunder(a,b) ref(x,n)
# 處置：disposal_day（處置第幾天）disposal_last（出關前一天）disposal_nth（第幾次處置）

buy = crossover(sma(close, 5), sma(close, 20))    # 進場條件（收盤價買）
sell = close < sma(close, 20)                      # 出場條件（選填）
stop_loss = 0.05                                   # 停損 5%（選填）
# take_profit = 0.10                               # 停利 10%（選填）
`;

async function loadStrats(select){
  const r = await api("/api/strategies");
  PRESETS = r.builtin; MINE = r.mine;
  $("btPreset").innerHTML =
    `<optgroup label="內建範本">${Object.keys(PRESETS).map(k => `<option value="b:${esc(k)}">${esc(k)}</option>`).join("")}</optgroup>` +
    `<optgroup label="我的策略">${MINE.length ? MINE.map(s => `<option value="m:${esc(s.name)}">${esc(s.name)}</option>`).join("")
                                          : `<option disabled>（還沒有，按「＋ 新增策略」）</option>`}</optgroup>`;
  if (select) $("btPreset").value = select;
  stButtons();
}
const selStrat = () => { const v = $("btPreset").value || ""; return {kind: v[0], name: v.slice(2)}; };
const stratCode = s => s.kind === "b" ? PRESETS[s.name] : (MINE.find(x => x.name === s.name) || {}).code;
function stButtons(){
  const mine = selStrat().kind === "m";
  $("stRename").disabled = $("stDel").disabled = !mine;
  $("stCur").textContent = CUR_STRAT ? `編輯中：${CUR_STRAT}` : "";
}
(async () => {
  await loadStrats();
  CUR_STRAT = lsGet("btCur", "") || null;
  if (CUR_STRAT && MINE.some(s => s.name === CUR_STRAT)) $("btPreset").value = "m:" + CUR_STRAT; else CUR_STRAT = null;
  $("btCode").value = lsGet("btCode", PRESETS[Object.keys(PRESETS)[0]]);
  stButtons();
  (function waitS(){ if (S) { $("btFees").checked = !!S.settings.bt_fees; $("btCap").value = S.settings.bt_capital; } else setTimeout(waitS, 200); })();
})();
$("btPreset").onchange = stButtons;
$("btLoad").onclick = () => {
  const s = selStrat(), code = stratCode(s);
  if (code == null) return;
  if ($("btCode").value.trim() && !confirm(`載入「${s.name}」會覆蓋目前編輯中的程式碼，確定？`)) return;
  $("btCode").value = code; lsSet("btCode", code);
  CUR_STRAT = s.kind === "m" ? s.name : null; lsSet("btCur", CUR_STRAT || "");
  stButtons();
};
async function saveStrat(name, code, old){
  const r = await post("/api/strategies", {name, code, old_name: old || ""});
  if (r.error) return r.error;
  CUR_STRAT = name; lsSet("btCur", name);
  await loadStrats("m:" + name);
  return null;
}
// 新增策略
$("stNew").onclick = () => {
  $("formStrat").elements.name.value = "";
  $("stCode").value = BLANK_TPL;
  $("stErr").style.display = "none";
  $("dlgStrat").showModal();
};
$("stTpl").onclick = () => { $("stCode").value = BLANK_TPL; };
$("stFromCur").onclick = () => { $("stCode").value = $("btCode").value; };
$("stCancel").onclick = () => $("dlgStrat").close();
$("formStrat").onsubmit = async e => {
  e.preventDefault();
  const name = $("formStrat").elements.name.value.trim(), code = $("stCode").value;
  if (MINE.some(s => s.name === name) && !confirm(`已經有「${name}」，要覆蓋嗎？`)) return;
  const err = await saveStrat(name, code);
  if (err) { $("stErr").textContent = err; $("stErr").style.display = "block"; return; }
  $("dlgStrat").close();
  $("btCode").value = code; lsSet("btCode", code);
  $("btOut").innerHTML = `<div class="k">已新增策略「${esc(name)}」，按「▶ 執行回測」試試看</div>`;
};
// 儲存：存回目前編輯中的「我的策略」；如果是內建範本或還沒命名，就另存新策略
$("stSave").onclick = async () => {
  let name = CUR_STRAT;
  if (!name) {
    name = (prompt("儲存成新策略，請輸入名稱：") || "").trim();
    if (!name) return;
    if (MINE.some(s => s.name === name) && !confirm(`已經有「${name}」，要覆蓋嗎？`)) return;
  }
  const err = await saveStrat(name, $("btCode").value);
  $("btOut").innerHTML = err ? `<div class="err">${esc(err)}</div>` : `<div class="k">已儲存「${esc(name)}」</div>`;
};
$("stRename").onclick = async () => {
  const s = selStrat(); if (s.kind !== "m") return;
  const name = (prompt("新的策略名稱：", s.name) || "").trim();
  if (!name || name === s.name) return;
  const err = await saveStrat(name, stratCode(s), s.name);
  if (err) alert(err);
};
$("stDel").onclick = async () => {
  const s = selStrat(); if (s.kind !== "m" || !confirm(`確定刪除「${s.name}」？`)) return;
  await post("/api/strategies/delete", {name: s.name});
  if (CUR_STRAT === s.name) { CUR_STRAT = null; lsSet("btCur", ""); }
  await loadStrats();
};
$("btCode").oninput = () => lsSet("btCode", $("btCode").value);
$("btCode").onkeydown = e => {   // Tab 鍵輸入 4 個空白
  if (e.key !== "Tab") return;
  e.preventDefault();
  const t = e.target, s = t.selectionStart;
  t.value = t.value.slice(0, s) + "    " + t.value.slice(t.selectionEnd);
  t.selectionStart = t.selectionEnd = s + 4; lsSet("btCode", t.value);
};
$("btFees").onchange = () => post("/api/settings", {bt_fees: $("btFees").checked});
$("btCap").onchange = () => post("/api/settings", {bt_capital: Number($("btCap").value)});

$("btRun").onclick = async () => {
  const scope = $("btScope").value, cur = window.CUR_STOCK;
  if (scope === "one" && !cur) { $("btOut").innerHTML = `<div class="err">請先在左邊選一檔股票</div>`; return; }
  $("btRun").disabled = true;
  $("btOut").innerHTML = `<div class="k">回測中…${scope === "one" ? "" : "（全部股票、期間越長越久，全部歷史可能要幾分鐘）"}</div>`;
  const res = await post("/api/backtest", {source: $("btCode").value, scope, code: cur && cur.code,
    fees: $("btFees").checked, capital: Number($("btCap").value), years: Number($("btYears").value)}).catch(e => ({error: String(e)}));
  $("btRun").disabled = false;
  if (res.error) { $("btOut").innerHTML = `<div class="err">${esc(res.error)}</div>`; return; }
  LAST_BT = {...res, scope, code: cur && cur.code};
  // 交易標到 K 線上
  window.BT_TRADES = {};
  [...res.trades, ...res.opens].forEach(t => (window.BT_TRADES[t.code] ||= []).push(t));
  renderBt(res, scope);
  const v = cur && (cur.page === "disposal" ? DISP_CV : MAIN_CV);
  if (v && cur) v.redraw({trades: window.BT_TRADES[cur.code] || []});
};

// 取消回測：清掉結果與 K 線上的買賣標記
$("btClear").onclick = () => {
  window.BT_TRADES = {};
  LAST_BT = null;
  $("btOut").innerHTML = `<div class="k">已取消回測，K 線圖已恢復正常</div>`;
  [MAIN_CV, DISP_CV].forEach(v => v && v.redraw({trades: []}));
};

function renderBt(res, scope){
  const m = res.summary, money = v => v == null ? "–" : `<span class="${cls(v)}">${v.toLocaleString()}</span>`;
  if (!m.trades) {
    $("btOut").innerHTML = `<div class="k">期間 ${res.period[0] || ""} ~ ${res.period[1] || ""}：沒有任何交易</div>` + errHtml(res);
    return;
  }
  const cells = [
    ["總損益", money(m.net) + " 元"], ["報酬率", `<span class="${cls(m.ret_pct)}">${fmt(m.ret_pct)}%</span>`],
    ["獲利因子", m.pf == null ? "∞" : fmt(m.pf)], ["交易次數", m.trades],
    ["勝率", `${fmt(m.win_rate)}%`], ["獲利次數", `${m.wins} / ${m.trades}`],
    ["平均獲利", money(m.avg_win)], ["平均虧損", money(m.avg_loss)],
    ["平均每筆報酬", `<span class="${cls(m.avg_ret)}">${fmt(m.avg_ret)}%</span>`], ["平均持有", `${m.avg_bars} 天`],
    ...(m.max_dd != null ? [["最大回撤", `${money(-m.max_dd)}（${fmt(m.max_dd_pct)}%）`]] : []), ["最大連續虧損", `${m.max_loss_streak} 筆`],
  ];
  const name = c => (ROWS.find(r => r.code === c) || {}).name || "";
  $("btOut").innerHTML =
    `<div class="k">期間 ${res.period[0]} ~ ${res.period[1]}｜${scope === "one" ? `${LAST_BT.code}` : `${res.stocks} 檔股票`}｜每筆 1 張</div>
     <div class="mgrid">${cells.map(([l, v]) => `<div><span class="k">${l}</span><b>${v}</b></div>`).join("")}</div>` +
    (scope !== "one" && res.per.length ? `<div class="ntitle">各股績效（前 15 / 後 5）</div><table class="bt">
      <tr><th>代號</th><th>名稱</th><th>次數</th><th>勝率</th><th>損益</th></tr>` +
      [...res.per.slice(0, 15), ...(res.per.length > 20 ? res.per.slice(-5) : [])].map(p =>
        `<tr class="r" data-c="${p.code}"><td>${p.code}</td><td>${esc(p.name)}</td><td>${p.trades}</td><td>${fmt(p.win_rate, 0)}%</td><td>${money(p.net)}</td></tr>`).join("") + `</table>` : "") +
    `<div class="ntitle">交易明細${scope === "one" ? "" : "（最近 300 筆）"}</div><table class="bt">
      <tr>${scope === "one" ? "" : "<th>代號</th>"}<th>進場</th><th>出場</th><th>原因</th><th>報酬</th></tr>` +
      [...res.opens, ...res.trades.slice().reverse()].slice(0, 300).map(t => `<tr class="r" data-c="${t.code}">
        ${scope === "one" ? "" : `<td>${t.code}</td>`}<td>${md(t.entry_date)} ${esc(t.label)}<br><span class="k">${t.entry}</span></td>
        <td>${t.reason === "持有中" ? "持有中" : md(t.exit_date)}<br><span class="k">${t.exit}</span></td>
        <td>${esc(t.reason)}</td><td>${pctCell(t.ret)}%<br><span class="k">${t.pnl.toLocaleString()}</span></td></tr>`).join("") + `</table>` + errHtml(res);
  // 點交易 → 在目前頁面打開那一檔
  document.querySelectorAll("#btOut tr.r").forEach(tr => tr.onclick = () => openStockInPage(tr.dataset.c));
}
const errHtml = res => res.errors && res.errors.length ? `<div class="err">部分股票執行錯誤：<br>${res.errors.map(esc).join("<br>")}</div>` : "";

function openStockInPage(code){
  if (window.CUR_PAGE === "disposal") {
    const rec = DISP.find(x => x.code === code);
    if (rec) return dispSelect(rec);
  }
  select(code);
}

$("btPine").onclick = () => {
  const pine = prompt("把 TradingView 的 Pine Script 貼在這裡（之後會交給 Claude 轉換成回測格式）：");
  if (!pine) return;
  openSide("ai");
  sendAi(`請把下面這段 TradingView Pine Script 轉換成本 App 的回測程式碼格式：\n\n${pine}`);
};
$("btAsk").onclick = () => {
  if (!LAST_BT) { alert("請先執行一次回測"); return; }
  openSide("ai");
  sendAi("請幫我解讀這次的回測結果：整體表現如何、主要的獲利/虧損來源、策略可能的弱點，以及可以怎麼改進。");
};

// ===== 問 AI =====
function context(){
  if (!$("aiCtx").checked) return null;
  const cur = window.CUR_STOCK, ctx = {page: window.CUR_PAGE === "disposal" ? "處置歷史" : "MACD(3,7,3) 選股", date: S && S.date};
  if (cur) {
    const r = cur.r, c = cur.c, last = a => a.slice(-20);
    ctx.stock = {code: r.code, name: r.name, market: r.market, close: r.close, chg_pct: r.chg, lots: r.lots,
      signals_today: r.hits, tomorrow_shrink_price: r.shrink, tomorrow_cross_price: r.cross, dif_pct: r.dif_pct,
      disposal: r.disp || null, attention: r.attn || null};
    ctx.last20_bars = last(c.bars).map(([d,o,h,l,cl,v]) => ({d, o, h, l, c: cl, v}));
    ctx.macd_last5 = c.dif.slice(-5).map(([d, v], i) => ({d, dif: v, macd: c.dea.slice(-5)[i][1], osc: c.hist.slice(-5)[i][1]}));
    if (c.notice) ctx.notice = {need_to_disposal: c.notice.min_need, today_clauses: c.notice.today, disposal_now: c.notice.disp,
      tomorrow_triggers: c.notice.triggers.filter(t => t.status !== "no").slice(0, 6), forecast: c.notice.fc};
    if (cur.disposals) ctx.disposal_history = cur.disposals;
  }
  if (LAST_BT) ctx.backtest = {scope: LAST_BT.scope, code_tested: LAST_BT.code, summary: LAST_BT.summary, period: LAST_BT.period,
    strategy_source: $("btCode").value.slice(0, 6000), recent_trades: LAST_BT.trades.slice(-15), top_stocks: LAST_BT.per.slice(0, 10)};
  return ctx;
}

function mdLite(text){
  // 簡易 Markdown：程式碼區塊（附套用按鈕）、粗體、換行
  const parts = String(text).split(/```(?:python|py)?\n?([\s\S]*?)```/g);
  return parts.map((p, i) => i % 2
    ? `<div class="codeblk"><pre>${esc(p)}</pre><button class="btn ghost apply">套用到回測</button></div>`
    : esc(p).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")).join("");
}

function renderAi(pending){
  $("aiMsgs").innerHTML = (AI_MSGS.length ? "" : `<div class="k hint">可以問：這檔明天會不會被處置？回測結果怎麼看？幫我寫一個 KD 黃金交叉的策略？<br>（第一次使用請先到「⚙ 設定」填 Claude API 金鑰）</div>`) +
    AI_MSGS.map(m => `<div class="msg ${m.role}">${m.role === "user" ? esc(m.content).replace(/\n/g, "<br>") : mdLite(m.content)}</div>`).join("") +
    (pending ? `<div class="msg assistant k">Claude 思考中…</div>` : "");
  $("aiMsgs").querySelectorAll(".codeblk .apply").forEach(b => b.onclick = () => {
    $("btCode").value = b.previousElementSibling.textContent; lsSet("btCode", $("btCode").value);
    openSide("bt"); $("btOut").innerHTML = `<div class="k">已套用 Claude 的程式碼，按「▶ 執行回測」試試看</div>`;
  });
  $("aiMsgs").scrollTop = $("aiMsgs").scrollHeight;
}

async function sendAi(text){
  text = (text || "").trim();
  if (!text) return;
  AI_MSGS.push({role: "user", content: text});
  renderAi(true);
  $("aiSend").disabled = true;
  const res = await post("/api/chat", {messages: AI_MSGS, context: context()}).catch(e => ({error: String(e)}));
  $("aiSend").disabled = false;
  if (res.error) { AI_MSGS.pop(); renderAi(); $("aiMsgs").insertAdjacentHTML("beforeend", `<div class="err">${esc(res.error)}</div>`); $("aiIn").value = text; return; }
  AI_MSGS.push({role: "assistant", content: res.text});
  renderAi();
}
$("aiSend").onclick = () => { const t = $("aiIn").value; $("aiIn").value = ""; sendAi(t); };
$("aiIn").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("aiSend").click(); } };
renderAi();
