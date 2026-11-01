const LW = LightweightCharts;
const TABS = [["signal","今日訊號"],["watch","明日觀察"],["mine","自選"],["fc","處置預測"],["disp","處置股"],["attn","注意股"],
              ["turn","周轉率排行"],["gain","漲幅排行"],["vsurge","成交激增"],["vgrow","成交緩增"],["scr","🔎 篩選"]];
const RANK_TABS = ["turn", "gain", "vsurge", "vgrow"];
const NOTICE_TABS = ["fc", "disp", "attn"];
let S = null, ROWS = [], tab = "signal", sortKey = null, sortDir = -1, selCode = null, chart = null, lastJobRunning = false;
let expanded = null, lastNotice = null;
let STATS_ON = (() => { try { return !!localStorage.getItem("statsOn"); } catch(e) { return false; } })();   // 左邊清單要不要顯示統計數據欄

const $ = id => document.getElementById(id);
const api = (url, opt) => fetch(url, opt).then(r => r.json());
const post = (url, body) => api(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body || {})});
const fmt = (v, d=2) => v == null ? "–" : Number(v).toLocaleString("zh-TW",{minimumFractionDigits:d,maximumFractionDigits:d});
const cls = v => v > 0 ? "up" : v < 0 ? "down" : "";

// ---------- 狀態 / 更新 ----------
async function refreshState(){
  try {
    S = await api("/api/state");
  } catch(e) {   // 程式重新啟動中／連不上 → 3 秒後再試，連上後自動重新載入清單
    $("status").textContent = "⚠ 連線中…（App 可能正在重新啟動）";
    refreshState.lost = true;
    setTimeout(refreshState, 3000);
    return;
  }
  if (refreshState.lost) { refreshState.lost = false; setTimeout(() => { loadList(); if (window.CUR_PAGE === "disposal") { DISP = null; dispShow(); } }, 300); }
  const p = S.settings, j = S.job;
  $("sub").textContent = S.date ? `${S.date} 收盤｜MACD(${p.macd_fast},${p.macd_slow},${p.macd_signal})` : "尚無資料";
  let st = j.running ? j.msg : (j.error ? "⚠ " + j.msg + "：" + j.error : (j.last ? `上次更新 ${j.last}` : ""));
  const bf = S.backfill;   // 歷史資料下載進度
  if (bf && !bf.done && bf.markets) st += "　📥 歷史資料下載中 " + Object.entries(bf.markets).map(([m, x]) =>
    `${m} ${x.current || ""}（剩約${x.eta_min ?? "?"}分）`).join("　");
  if (j.running) {
    const pr = Object.entries(j.progress).map(([m,[k,n]]) => `${m} ${k}/${n}`).join("　");
    if (pr) st += "　" + pr;
  }
  $("status").textContent = st;
  $("btnUpdate").disabled = j.running;
  renderTabs();
  if (lastJobRunning && !j.running) await loadList();   // 更新剛完成 → 重新載入
  lastJobRunning = j.running;
  setTimeout(refreshState, j.running ? 2000 : 30000);
}

async function loadList(){
  try {
    ROWS = await api("/api/list");
    S = await api("/api/state");
  } catch(e) { setTimeout(loadList, 3000); return; }
  renderTabs(); renderList();
  if (selCode) select(selCode, false);
}

// ---------- 左側清單 ----------
function tags(r){
  let s = "";
  if (r.entry) s += `<span class="tag t-sig">${r.hits.join("/")}</span>`;
  if (r.disp) s += `<span class="tag t-disp">處置</span>`;
  if (r.attn) s += `<span class="tag t-attn">注意</span>`;
  return s;
}

// 分頁清單：內建的 TABS，自己新增的自選清單（設定 watchlists）接在「自選」後面，key = wl_<id>
function allTabs(){
  const wls = ((S && S.settings.watchlists) || []).map(w => ["wl_" + w.id, "⭐" + w.name]);
  const i = TABS.findIndex(t => t[0] === "mine") + 1;
  return [...TABS.slice(0, i), ...wls, ...TABS.slice(i)];
}
const wlOf = k => k && k.startsWith("wl_") ? ((S && S.settings.watchlists) || []).find(w => "wl_" + w.id === k) : null;
async function wlOp(body){
  const j = await post("/api/watchlists", body);
  if (j && j.error) { alert(j.error); return null; }
  await loadList();
  return j;
}
// 「＋ 加股票」：key = mine（內建自選）或 wl_<id>（自己的清單）；個股K 和看盤 › 證券共用。回傳有沒有加
async function wlAddCodes(key){
  const w = wlOf(key), name = w ? w.name : "自選";
  const s = prompt(`加入「${name}」的股票代號（可以一次貼多檔，用空白或逗號隔開）`);
  const add = (s || "").split(/[\s,，]+/).filter(Boolean);
  if (!add.length) return false;
  if (w) return !!(await wlOp({op: "codes", id: w.id, add}));
  const have = S.settings.watchlist || [];
  for (const c of add.filter(c => !have.includes(c))) await post("/api/watch/" + encodeURIComponent(c));   // 這支是切換：已經在裡面的跳過
  await loadList();
  return true;
}
function renderTabs(){
  if (!S) return;
  if (tab.startsWith("wl_") && !wlOf(tab)) tab = "mine";   // 清單被刪掉了
  $("tabs").innerHTML = allTabs().map(([k,l]) =>
    `<button data-k="${k}" class="${k===tab?"on":""}" ${k.startsWith("wl_") ? `title="右鍵：改名／刪除這個清單"` : ""}>${l}<span class="n">${k === "scr" ? (window.SCR ? scrRows().length : "") : S.counts[k] ?? 0}</span></button>`).join("") +
    `<button class="wl-new" id="wlNew" title="新增一個自選清單（可以取名字，看盤 › 證券也會出現）">＋</button>` +
    (tab === "mine" || wlOf(tab) ? `<button class="wl-new" id="wlAddCode" title="把股票加進這個清單">＋ 加股票</button>` : "") +
    `<button class="stbtn ${STATS_ON ? "on" : ""}" id="stToggle" title="在清單和 K 線上方顯示／隱藏統計數據（連漲、均量比、月線斜率、外資連買…）">📊 數據</button>`;
  document.querySelectorAll("#tabs button[data-k]").forEach(b => b.onclick = () => { tab = b.dataset.k; sortKey = null; renderTabs(); renderList(); if (window.renderPages) renderPages(); });
  document.querySelectorAll("#tabs button[data-k^='wl_']").forEach(b => b.oncontextmenu = async e => {
    e.preventDefault();
    const w = wlOf(b.dataset.k);
    const name = prompt(`改名「${w.name}」（清空名字按確定 = 刪除這個清單）`, w.name);
    if (name === null) return;
    if (!name.trim()) { if (confirm(`確定刪除「${w.name}」？（裡面 ${w.codes.length} 檔股票不會影響其他清單）`)) await wlOp({op: "del", id: w.id}); }
    else await wlOp({op: "rename", id: w.id, name});
  });
  $("wlNew").onclick = async () => {
    const name = prompt("新的自選清單名稱（例如：AI 伺服器、觀察中）");
    if (!name || !name.trim()) return;
    const j = await wlOp({op: "add", name});
    if (j) { tab = "wl_" + j.id; renderTabs(); renderList(); }
  };
  if ($("wlAddCode")) $("wlAddCode").onclick = () => wlAddCodes(tab);
  $("stToggle").onclick = () => {
    STATS_ON = !STATS_ON;
    try { localStorage.setItem("statsOn", STATS_ON ? "1" : ""); } catch(e) {}
    renderTabs(); renderList(); ChartView.all.forEach(v => v.redraw());
  };
}

// 各分頁的欄位：[key, 標題, 顯示內容, 排序值]
const circ = n => "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭"[n-1] || n;
const md = d => d ? `${+d.slice(5,7)}/${+d.slice(8,10)}` : "";
const leftTxt = d => !d.started ? `${md(d.start)}起` : d.left === 0 ? "明日出關" : `${d.left}天`;
function columns(){
  const cols = baseColumns();
  return STATS_ON || tab === "scr" ? [...cols, ...statColumns()] : cols;   // 按「📊 數據」才把統計欄加在後面
}
function baseColumns(){
  const base = [["code","代號", r => r.code], ["name","名稱", r => r.name + tags(r), r => r.name]];
  const px = [["close","收盤", r => fmt(r.close)], ["chg","漲跌%", r => `<span class="${cls(r.chg)}">${fmt(r.chg)}</span>`, r => r.chg]];
  if (tab === "disp") return [...base,
    ["cond","處置條件", r => `<span class="cond">${r.notice.disp.cond}</span><span class="k"> ${r.notice.disp.measure.replace("處置","")}</span>`, r => r.notice.disp.cond],
    ["left","剩餘", r => `${leftTxt(r.notice.disp)}<br><span class="k sm">${md(r.notice.disp.out)}出關</span>`, r => r.notice.disp.started ? r.notice.disp.left : -1],
    px[0],
    ["dip","明日-6%", r => r.notice.disp.dip_ok ? `<b class="down">${fmt(r.notice.disp.dip_price)}</b>` : `<span class="k">–</span>`,
     r => r.notice.disp.dip_ok ? 0 : 1]];
  if (tab === "fc") return [...base,
    ["need","差", r => `<b class="${r.notice.min_need === 1 ? "up" : ""}">${r.notice.min_need}次</b>`, r => r.notice.min_need],
    ["trig","明日注意價", r => `<span class="sm">${r.notice.trig.join("<br>") || "–"}</span>`, r => r.notice.min_need],
    ["first","最快處置", r => `${md(r.notice.fc.first_day)} ${r.notice.fc.nth}`, r => r.notice.fc.first_day], px[0]];
  if (tab === "attn") return [...base,
    ["cl","今日款別", r => (r.notice?.today || []).map(circ).join(""), r => (r.notice?.today || [])[0]],
    ["need","處置倒數", r => r.notice ? (r.notice.disp ? "處置中" : `差${r.notice.min_need}次`) : "–", r => r.notice?.min_need ?? 9], ...px];
  const pc = v => v == null ? "–" : `${fmt(v)}%`;
  if (tab === "scr") return [...base, ...px, ["lots","量(張)", r => r.lots == null ? "–" : r.lots.toLocaleString()]];
  if (tab === "turn" || tab === "gain") return [...base, ...px, ["lots","量(張)", r => r.lots.toLocaleString()],
    ["turnover","周轉率", r => pc(r.turnover)]];
  if (tab === "vsurge") return [...base, ...px, ["lots","量(張)", r => r.lots.toLocaleString()],
    ["vratio","量/5日均", r => r.vratio == null ? "–" : `<b class="up">${fmt(r.vratio, 1)}倍</b>`]];
  if (tab === "vgrow") return [...base, ...px, ["lots","量(張)", r => r.lots.toLocaleString()],
    ["vgrow_pct","3日量增", r => r.vgrow_pct == null ? "–" : `<span class="up">+${fmt(r.vgrow_pct, 0)}%</span>`]];
  return [...base, ...px, ["lots","量(張)", r => r.lots.toLocaleString()],
    tab === "watch" ? ["need_pct","需漲%", r => `<span class="${cls(r.need_pct)}">${fmt(r.need_pct)}</span>`]
                    : ["hist","柱值", r => `<span class="${cls(r.hist)}">${fmt(r.hist)}</span>`]];
}

function currentRows(){
  const cols = columns();
  const defKey = {scr:"amount", watch:"need_pct", fc:"need", disp:"left", attn:"need", turn:"turnover", gain:"chg", vsurge:"vratio", vgrow:"vgrow_pct"}[tab] || "lots";
  const key = sortKey || defKey;
  const dir = sortKey ? sortDir : (["watch","fc","disp","attn"].includes(tab) ? 1 : -1);   // 排行類預設由大到小
  const col = cols.find(c => c[0] === key);
  const val = r => col && col[3] ? col[3](r) : r[key] ?? statVal(r, key);
  const src = tab === "scr" ? (window.SCR ? scrRows() : []) : ROWS.filter(r => r.lists.includes(tab));
  return src.sort((a,b) => ((val(a) ?? 1e9) > (val(b) ?? 1e9) ? 1 : -1) * dir);
}

function renderList(){
  $("scrPanel").style.display = tab === "scr" ? "" : "none";
  if ((tab === "scr" || STATS_ON) && !window.SCR) scrLoad().then(() => { if (window.SCR) { renderTabs(); renderList(); } });
  const cols = columns();
  $("thead").innerHTML = "<tr>" + cols.map(([k,l]) => `<th data-k="${k}">${l}</th>`).join("") + "</tr>";
  document.querySelectorAll("#thead th").forEach(th => th.onclick = () => {
    sortDir = sortKey === th.dataset.k ? -sortDir : 1; sortKey = th.dataset.k; renderList(); });
  const rs = currentRows();
  const emptyMsg = S && !S.date ? "第一次使用，正在下載歷史資料（約 10~15 分鐘），請稍候…" :
                   tab === "mine" ? "還沒有自選股。查詢任一檔後按 ☆ 加入。" : wlOf(tab) ? "這個清單還是空的，按上面「＋ 加股票」加入。" : tab === "scr" && !window.SCR ? "載入數據中…" : "沒有符合的股票";
  $("tbody").innerHTML = rs.length ? rs.slice(0, 400).map(r => `<tr class="r ${r.code===selCode?"sel":""}" data-c="${r.code}">` +
      cols.map(c => `<td>${c[2](r)}</td>`).join("") + `</tr>` +
      (NOTICE_TABS.includes(tab) && expanded === r.code ? `<tr class="det"><td colspan="${cols.length}" id="det"></td></tr>` : "")).join("")
    : `<tr><td colspan="${cols.length}" class="empty">${emptyMsg}</td></tr>`;
  document.querySelectorAll("tr.r").forEach(tr => tr.onclick = () => {
    if (NOTICE_TABS.includes(tab)) { expanded = expanded === tr.dataset.c ? null : tr.dataset.c; renderList(); }
    select(tr.dataset.c);
  });
  if (wlOf(tab)) document.querySelectorAll("tr.r").forEach(tr => tr.oncontextmenu = async e => {   // 自己的清單：右鍵移除
    e.preventDefault();
    const w = wlOf(tab);
    if (confirm(`從「${w.name}」移除 ${tr.dataset.c}？`)) await wlOp({op: "codes", id: w.id, remove: [tr.dataset.c]});
  });
  if (expanded && lastNotice && lastNotice.code === expanded && $("det")) $("det").innerHTML = `<div class="det-inner">${noticeHtml(lastNotice.n, lastNotice.r)}</div>`;
  if (rs.length && !rs.some(r => r.code === selCode)) select(rs[0].code);
}

// 處置 / 注意的詳細資料（展開列）
function noticeHtml(n, r){
  if (!n) return `<div class="k">沒有注意 / 處置紀錄</div>`;
  const nd = n.need, h = [];
  if (n.disp) {
    const d = n.disp;
    h.push(`<div class="nbox disp"><b>處置中</b>　${d.cond_full}｜${d.measure}<br>
      處置期間 ${md(d.start)} ~ ${md(d.end)}　${d.started ? (d.left === 0 ? "<b>明日出關</b>" : `剩 <b>${d.left}</b> 個交易日`) : `<b>${md(d.start)} 開始</b>`}　${md(d.out)} 出關<br>
      <span class="k">${d.match}</span></div>`);
    h.push(`<div class="nbox dip">${d.dip_ok
      ? `📉 <b>明日急殺 -6% 掛單價：<span class="down">${fmt(d.dip_price)}</span></b>（今日收盤 ${fmt(d.dip_base)} × 0.94）<br>
         <span class="k">隔日沖改良版：成交後隔天漲到「隔天開盤價 +4%」就賣，沒到就收盤賣｜新制回測約 +2%/筆、勝率 68%</span>`
      : `<span class="k">明日急殺 -6% 策略：${d.dip_note}</span>`}</div>`);
  }
  if (n.fc) {
    const f = n.fc;
    h.push(`<div class="nbox warn">${f.need === 1
      ? `⚠ <b>差 1 次就處置</b>：明日（${md(n.tomorrow)}）若再被注意（${f.clauses.length === 1 ? "第一款" : "第一～八款"}），達「${f.rules.join("、")}」→ <b>${md(f.first_day)} 起處置 ${f.days} 個營業日（${f.nth}）</b>`
      : `差 2 次處置，最快 ${md(f.first_day)} 起處置（${f.nth}）`}</div>`);
  }
  h.push(`<div class="cnt">處置條件累計：
    <span>連續3日第一款 <b>${nd.a1_streak}</b>/3</span><span>連續5日 <b>${nd.a18_streak}</b>/5</span>
    <span>10日內 <b>${nd.a18_10}</b>/6</span><span>30日內 <b>${nd.a18_30}</b>/12</span></div>`);
  const trig = n.triggers.filter(t => t.status !== "no");
  h.push(`<div class="ntitle">明日（${md(n.tomorrow)}）可能觸發注意的價位 <span class="k">（依法規估算，以今日全體/類股平均值試算）</span></div>` +
    (trig.length ? `<table class="ntab"><tr><th>款別</th><th>條件</th><th>狀態</th></tr>` + trig.map(t =>
      `<tr><td>${circ(t.clause)} ${n.clause_name[t.clause]}</td>
       <td>收盤 ${t.dir > 0 ? "≥" : "≤"} <b class="${t.dir > 0 ? "up" : "down"}">${fmt(t.price)}</b> <span class="k">(${t.pct > 0 ? "+" : ""}${fmt(t.pct)}%)</span> ${t.cond}</td>
       <td>${t.status === "already" ? `<b class="up">${t.dir > 0 ? "跌停也符合" : "漲停也符合"}</b>` : "可能"}</td></tr>`).join("") + `</table>`
     : `<div class="k">明日漲跌停範圍內都不會觸發 ①②③④⑪</div>`) +
    `<div class="k" style="margin-top:4px">⑤券商集中、⑥本益比淨值比、⑦券資比、⑨⑩量能、⑫借券、⑬當沖 需要額外資料，未估算</div>`);
  if (n.hist.length) h.push(`<div class="ntitle">最近 30 個營業日注意紀錄（上次處置後）</div>` +
    n.hist.slice().reverse().map(([d, cl, txt]) => `<div class="hist"><b>${md(d)}</b> ${cl.map(circ).join("")} <span class="k">${txt}</span></div>`).join(""));
  return h.join("");
}

// ---------- 右側 K 線 ----------
async function select(code, scroll=true){
  selCode = code;
  document.querySelectorAll("tr.r").forEach(tr => tr.classList.toggle("sel", tr.dataset.c === code));
  if (scroll) document.querySelector(`tr.r[data-c="${code}"]`)?.scrollIntoView({block:"nearest"});
  if (!MAIN_CV) MAIN_CV = new ChartView($("chartbox"));
  const c = await api(MAIN_CV.url(code));
  if (!c.row || code !== selCode) return;
  const r = c.row, p = S.settings;
  const pct = x => x == null ? "" : `<span class="k">(${fmt((x/r.close-1)*100)}%)</span>`;
  $("info").innerHTML = `
    <div><span class="big">${r.code} ${r.name}</span> <span class="k">${r.market}</span>${tags(r)}
      <button class="star ${r.mine?"on":""}" id="star">${r.mine?"★ 自選":"☆ 加自選"}</button></div>
    <div><span class="k">收盤 </span><span class="big ${cls(r.chg)}">${fmt(r.close)}</span> <span class="${cls(r.chg)}">${fmt(r.chg)}%</span></div>
    <div><span class="k">量 </span>${r.lots.toLocaleString()} ${c.vol_unit || "張"}</div>
    <div><span class="k" style="color:var(--pink)">● 明日摸底價 </span>${fmt(r.shrink)} ${pct(r.shrink)}</div>
    <div><span class="k" style="color:var(--yellow)">● 明日金叉價 </span>${fmt(r.cross)} ${pct(r.cross)}</div>
    ${r.gap != null ? `<div><span class="k">明日開盤 > ${fmt(r.cross)} → 跳空進場</span></div>` : ""}
    <div><span class="k">DIF/股價 </span><span class="${r.dif_pct > p.max_dif_pct && p.dif_filter ? "up" : ""}">${fmt(r.dif_pct)}%</span>
      ${p.dif_filter && r.max != null ? `<span class="k">（過熱上限價 ${fmt(r.max)}）</span>` : ""}</div>
    ${r.date !== S.date ? `<div class="note">最後交易日 ${r.date}（可能暫停交易）</div>` : ""}
    ${r.disp ? `<div class="note">處置：${r.disp}${c.notice?.disp ? `｜${leftTxt(c.notice.disp)}` : ""}</div>` : ""}
    ${r.attn ? `<div class="note">注意：${r.attn}</div>` : ""}
    ${c.notice?.fc ? `<div class="note">⚠ 差 ${c.notice.fc.need} 次處置，最快 ${md(c.notice.fc.first_day)} 起（${c.notice.fc.nth}）</div>` : ""}`;
  lastNotice = {code, n: c.notice, r};
  if (expanded === code && $("det")) $("det").innerHTML = `<div class="det-inner">${noticeHtml(c.notice, r)}</div>`;
  $("star").onclick = async () => { await post(`/api/watch/${code}`); await loadList(); select(code); };
  drawChart(r, c);
}

// K 線圖（共用元件在 chart.js）
let MAIN_CV = null;
function drawChart(r, c){
  if (!MAIN_CV) MAIN_CV = new ChartView($("chartbox"));
  MAIN_CV.draw(r, c, {trades: (window.BT_TRADES || {})[r.code]});
  window.CUR_STOCK = {code: r.code, r, c, page: "macd"};
  if (window.brOnStock) brOnStock();
}

// ---------- 查詢任一檔 ----------
let suggIdx = -1;
$("q").oninput = async () => {
  const q = $("q").value.trim();
  if (!q) { $("sugg").style.display = "none"; return; }
  const res = await api(`/api/search?q=${encodeURIComponent(q)}`);
  if ($("q").value.trim() !== q) return;
  suggIdx = res.length ? 0 : -1;
  $("sugg").innerHTML = res.map((s,i) => `<div data-c="${s.code}" class="${i===0?"on":""}">${s.code} ${s.name} <span class="k" style="color:var(--muted)">${s.market}</span></div>`).join("")
    || `<div style="color:var(--muted)">查無股票</div>`;
  $("sugg").style.display = "block";
  document.querySelectorAll("#sugg div[data-c]").forEach(d => d.onmousedown = () => pick(d.dataset.c));
};
$("q").onkeydown = e => {
  const items = [...document.querySelectorAll("#sugg div[data-c]")];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); if (!items.length) return;
    suggIdx = (suggIdx + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((d,i) => d.classList.toggle("on", i === suggIdx));
  } else if (e.key === "Enter" && items[suggIdx]) pick(items[suggIdx].dataset.c);
  else if (e.key === "Escape") $("sugg").style.display = "none";
};
$("q").onblur = () => setTimeout(() => $("sugg").style.display = "none", 150);
function pick(code){ $("q").value = ""; $("sugg").style.display = "none"; select(code); }

// ---------- 設定 ----------
$("btnSettings").onclick = () => {
  const p = S.settings, f = $("form");
  $("stratBox").innerHTML = S.strategies.map(s =>
    `<label class="chk"><input type="checkbox" data-strat="${s.key}" ${p.strategies[s.key] !== false ? "checked" : ""}> ${s.label}</label>`).join("");
  for (const el of f.elements) {
    if (!el.name || !(el.name in p)) continue;
    if (el.type === "checkbox") el.checked = !!p[el.name]; else el.value = p[el.name];
  }
  fetch("/api/capital").then(r => r.json()).then(c => $("capStatus").textContent = c.msg).catch(() => {});
  $("dlg").showModal();
};
$("btnCancel").onclick = () => $("dlg").close();
$("form").onsubmit = async e => {
  e.preventDefault();
  const body = {strategies: {}};
  for (const el of $("form").elements) {
    if (el.dataset.strat) body.strategies[el.dataset.strat] = el.checked;
    else if (el.name) body[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" || el.dataset.num ? Number(el.value) : el.value;
  }
  $("dlg").close();
  $("status").textContent = "重新選股中…";
  await post("/api/settings", body);
  await loadList();
  $("status").textContent = "設定已儲存";
  ChartView.all.forEach(v => v.redraw());   // 主力買賣超累計天數可能改了
};
$("btnQuit").onclick = async () => {
  if (!confirm("確定結束程式？（結束後不會自動更新，下次從桌面捷徑再打開）")) return;
  await post("/api/shutdown").catch(() => {});
  document.body.innerHTML = `<div class="empty" style="padding:40px">程式已結束，可以關閉這個視窗。</div>`;
};

// ---------- 其他 ----------
// 群益 API 開關：綠 = 已連線、黃 = 連線中、紅 = 錯誤、灰 = 關
async function refreshCapital(){
  try {
    const c = await api("/api/capital"), b = $("btnCapital");
    b.className = "btn ghost cap-btn " + c.state;
    $("capLabel").textContent = "群益 API：" + ({ready: "已連線", connecting: "連線中…", error: "錯誤", off: "關"}[c.state] || c.state);
    b.title = c.msg + "（點一下切換開／關）";
    setTimeout(refreshCapital, c.state === "connecting" ? 2000 : 15000);
  } catch(e) { setTimeout(refreshCapital, 5000); }
}
$("btnCapital").onclick = async () => {
  const s = await api("/api/state"), on = !s.settings.capital_enabled;
  if (on && (!s.settings.capital_id || !s.settings.capital_pwd)) { alert("請先在「⚙ 設定」填群益帳號密碼"); $("btnSettings").click(); return; }
  await post("/api/settings", {capital_enabled: on});
  setTimeout(refreshCapital, 500);
};
refreshCapital();
$("btnUpdate").onclick = async () => { await post("/api/update"); setTimeout(refreshState, 300); };
document.addEventListener("keydown", e => {
  if ((e.key !== "ArrowDown" && e.key !== "ArrowUp") || document.activeElement.tagName === "INPUT" || $("dlg").open) return;
  if (window.CUR_PAGE && window.CUR_PAGE !== "strategy") return;   // 其他頁（例如數據篩選）自己處理上下鍵
  const rs = currentRows(), i = rs.findIndex(r => r.code === selCode);
  const n = rs[Math.max(0, Math.min(rs.length-1, i + (e.key === "ArrowDown" ? 1 : -1)))];
  if (n) { e.preventDefault(); select(n.code); }
});

(async () => { await refreshState(); await loadList(); })();
