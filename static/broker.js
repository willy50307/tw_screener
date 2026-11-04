// ---------- 主力進出（券商分點）：右側面板＋點分點看他在這檔的每日買賣超 ----------
let BR = null, BR_CHART = null, brCur = null, brYear = 1;
const brAutoOn = () => lsGet("brAuto", "1") === "1";
$("brAuto").checked = brAutoOn();
$("brAuto").onchange = () => lsSet("brAuto", $("brAuto").checked ? "1" : "0");
$("brDays").value = lsGet("brDays", "1");
$("brDays").onchange = () => { lsSet("brDays", $("brDays").value); brShow(); };

// 點開股票：面板開著就更新；沒開而且有勾「自動顯示」就打開
// 只有「使用者親手點了股票」才自動打開（App 一打開或頁面自動選第一檔時不要跳出來）
let BR_CLICK_T = 0;
document.addEventListener("click", e => {
  if (e.target.closest("#pages")) { BR_CLICK_T = 0; return; }          // 切換大頁面不算點股票
  if (e.target.closest("tr.r, .ch-c, .lu-cand, #sugg div, .r[data-c], [data-c]")) BR_CLICK_T = Date.now();
}, true);
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "q") BR_CLICK_T = Date.now(); }, true);
function brOnStock(){
  const okPage = window.CUR_PAGE === "strategy" || window.CUR_PAGE === "disposal";
  if (sidePanel === "br") { if (okPage) brShow(); return; }
  if (!sidePanel && brAutoOn() && okPage && Date.now() - BR_CLICK_T < 5000) openSide("br");
}

async function brShow(){
  const cur = window.CUR_STOCK;
  if (!cur) { $("brBody").innerHTML = `<div class="k">先點一檔股票</div>`; return; }
  if (cur.code === "TX" || cur.code === "TXD" || cur.code === "TAIEX") { $("brBody").innerHTML = `<div class="k">指數／期貨沒有分點資料</div>`; return; }
  const code = cur.code, days = +$("brDays").value;
  $("brBody").innerHTML = `<div class="k">查詢 ${code} 主力進出中…</div>`;
  let d;
  try { d = await api(`/api/broker/${code}?days=${days}`); } catch(e) { d = {error: "查詢失敗"}; }
  if (!window.CUR_STOCK || window.CUR_STOCK.code !== code) return;
  BR = d;
  if (d.error) { $("brBody").innerHTML = `<div class="k">${d.error}</div>`; return; }
  const name = (cur.r && cur.r.name) || "";
  const range = d.days > 1 ? `${d.start.slice(5).replace("-", "/")}～${d.date.slice(5).replace("-", "/")}` : d.date.slice(5).replace("-", "/");
  const tb = (rows, buy) => `<table class="lu-t br-t"><tr><th>${buy ? "買超" : "賣超"}券商</th><th>${buy ? "買超" : "賣超"}</th><th>買進</th><th>賣出</th><th>佔比</th></tr>
    ${rows.map((r, i) => `<tr class="br-row" data-i="${buy ? "B" : "S"}${i}" title="點一下看 ${r.branch} 在 ${name} 的每日買賣超">
      <td>${r.dt ? "🎯" : ""}${r.branch}</td><td class="${buy ? "up" : "down"}"><b>${Math.abs(r.net).toLocaleString()}</b></td>
      <td>${r.buy.toLocaleString()}</td><td>${r.sell.toLocaleString()}</td><td class="k">${r.pct}</td></tr>`).join("")}</table>`;
  const sb = d.buy.reduce((a, r) => a + r.net, 0), ss = d.sell.reduce((a, r) => a + r.net, 0);
  $("brBody").innerHTML = `<div class="br-title"><b>${code} ${name}</b> <span class="k">${range}｜單位：張</span></div>
    ${brInstHtml(d.inst, d.date)}
    <div class="k" style="margin-bottom:4px">前15大買超合計 <span class="up">${sb.toLocaleString()}</span>｜前15大賣超合計 <span class="down">${Math.abs(ss).toLocaleString()}</span>｜🎯＝隔日沖分點</div>
    ${tb(d.buy, true)}<div style="height:8px"></div>${tb(d.sell, false)}
    <div class="k" style="margin-top:6px">點任一分點，可以看他在這檔股票最近一年的每日買賣超。資料：富邦 e 點通，每天約傍晚更新。</div>`;
  if (d.inst && d.inst.end) brInstBind(code, d.inst.end);
  document.querySelectorAll("#brBody .br-row").forEach(tr => tr.onclick = () => {
    const k = tr.dataset.i, r = (k[0] === "B" ? d.buy : d.sell)[+k.slice(1)];
    brOpen(code, name, r);
  });
}

// 三大法人買賣超（張）：外資(含外資自營)、投信、自營(避險)、自營(自行)
function brInstHtml(I, brDate){
  if (!I) return "";
  if (!I.days || !I.days.length) return `<div class="k br-inst-none">三大法人：資料庫沒有這檔的法人資料</div>`;
  const v = n => `<td class="${cls(n)}"><b>${n > 0 ? "+" : ""}${n.toLocaleString()}</b></td>`;
  const row = (t, x, c) => `<tr${c ? ` class="${c}"` : ""}><td>${t}</td>${INST_W.map(([k]) => v(x[k]).replace("<td ", `<td data-w="${k}" `)).join("")}</tr>`;
  const md = s => s.slice(5).replace("-", "/");
  const many = I.days.length > 1;
  const body = many
    ? (I.days.length <= 10 ? I.days.slice().reverse().map(x => row(md(x.date), x)).join("") : "") + row("合計", I.sum, "br-inst-sum")
    : row(md(I.end), I.days[0]);
  const late = I.end !== brDate ? `<span class="down">（${md(brDate)} 法人尚未公布，顯示 ${md(I.end)}）</span>` : "";
  return `<div class="br-inst"><div class="k" style="margin-bottom:2px">三大法人買賣超｜單位：張${late}</div>
    <table class="lu-t br-t br-inst-t"><tr><th>日期</th>${INST_W.map(([k, t]) => `<th data-w="${k}" title="點一下看${t}近20天買賣超">${t} ▾</th>`).join("")}</tr>${body}</table>
    <div id="brInstHist"></div></div>`;
}

const INST_W = [["fi", "外資"], ["it", "投信"], ["dh", "自營避險"], ["dp", "自營"], ["tot", "合計"]];
let BR_INST_W = null;
// 點三大法人表的欄位：下方展開該法人近 20 天每日買賣超
function brInstBind(code, end){
  BR_INST_W = null;
  document.querySelectorAll("#brBody .br-inst-t [data-w]").forEach(el => el.onclick = () => {
    const w = el.dataset.w;
    if (BR_INST_W === w) { BR_INST_W = null; $("brInstHist").innerHTML = ""; brInstMark(); return; }
    BR_INST_W = w; brInstMark(); brInstHist(code, w, end);
  });
}
function brInstMark(){
  document.querySelectorAll("#brBody .br-inst-t [data-w]").forEach(el => el.classList.toggle("on", el.dataset.w === BR_INST_W));
}
async function brInstHist(code, w, end){
  const box = $("brInstHist"), t = INST_W.find(x => x[0] === w)[1];
  box.innerHTML = `<div class="k">查詢 ${t} 近20天…</div>`;
  let d;
  try { d = await api(`/api/inst/${code}?n=20&end=${end}`); } catch(e) { d = {error: "查詢失敗"}; }
  if (BR_INST_W !== w || !$("brInstHist")) return;
  if (d.error || !d.days || !d.days.length) { box.innerHTML = `<div class="k">${d.error || "沒有法人資料"}</div>`; return; }
  const days = d.days, mx = Math.max(1, ...days.map(x => Math.abs(x[w])));
  let cum = 0; const cums = days.map(x => cum += x[w]);
  let streak = 0; const sg = Math.sign(days[days.length - 1][w]);
  for (let i = days.length - 1; i >= 0 && sg && Math.sign(days[i][w]) === sg; i--) streak++;
  const buyN = days.filter(x => x[w] > 0).length;
  const sn = n => `${n > 0 ? "+" : ""}${n.toLocaleString()}`;
  const rows = days.map((x, i) => ({x, c: cums[i]})).reverse().map(({x, c}) => {
    const n = x[w], pct = Math.abs(n) / mx * 50;
    const bar = n >= 0 ? `<span class="bi-bar up-bg" style="left:50%;width:${pct}%"></span>` : `<span class="bi-bar down-bg" style="right:50%;width:${pct}%"></span>`;
    return `<tr><td>${x.date.slice(5).replace("-", "/")}</td><td>${x.close != null ? fmt(x.close) : "–"}</td><td class="${cls(n)}"><b>${sn(n)}</b></td>
      <td class="bi-cell"><span class="bi-mid"></span>${bar}</td><td class="${cls(c)}">${sn(c)}</td></tr>`;
  }).join("");
  box.innerHTML = `<div class="br-inst-hist"><div class="br-title"><b>${t}</b> <span class="k">近 ${days.length} 個交易日｜單位：張</span></div>
    <div class="k" style="margin-bottom:4px">合計 <b class="${cls(cums[cums.length - 1])}">${sn(cums[cums.length - 1])}</b>｜買超 ${buyN} 天、賣超 ${days.length - buyN} 天｜${sg ? `目前連${sg > 0 ? "買" : "賣"} ${streak} 天` : ""}</div>
    <table class="lu-t br-t"><tr><th>日期</th><th>收盤</th><th>買賣超</th><th style="width:38%"></th><th>累計</th></tr>${rows}</table></div>`;
}

async function brOpen(code, name, r){
  brCur = {code, name, r};
  $("brDlgTitle").innerHTML = `${r.branch} 對 ${name}（${code}） 主力進出`;
  $("brYears").innerHTML = [[0.25, "3月"], [0.5, "半年"], [1, "1年"], [2, "2年"], [3, "3年"]]
    .map(([y, n]) => `<button data-y="${y}" class="${y === brYear ? "on" : ""}">${n}</button>`).join("");
  document.querySelectorAll("#brYears button").forEach(b => b.onclick = () => { brYear = +b.dataset.y; brOpen(code, name, r); });
  $("brDlgClose").onclick = () => $("dlgBr").close();
  if (!$("dlgBr").open) $("dlgBr").showModal();
  $("brDlgSum").innerHTML = `<span class="k">查詢中…</span>`;
  let h;
  try { h = await api(`/api/broker/${code}/hist?b=${encodeURIComponent(r.bid)}&bhid=${encodeURIComponent(r.bhid)}&years=${brYear}`); } catch(e) { h = {error: "查詢失敗"}; }
  if (brCur.r !== r) return;
  if (h.error) { $("brDlgSum").innerHTML = `<span class="k">${h.error}</span>`; return; }
  brRender(h);
}

function brRender(h){
  const rows = h.rows;   // [日期, 收盤, 買進, 賣出, 買賣超, 累計, 均價估算]
  const per = n => {     // 最近 n 天統計
    const x = rows.slice(-n), net = x.reduce((a, r) => a + r[4], 0);
    const buy = x.reduce((a, r) => a + r[2], 0), sell = x.reduce((a, r) => a + r[3], 0);
    const cost = net ? x.reduce((a, r) => a + r[4] * r[6], 0) / net : null;
    return {net, buy, sell, cost};
  };
  const card = (t, p) => `<div class="mcard"><span class="k">${t}</span><b class="${cls(p.net)}">${p.net > 0 ? "+" : ""}${Math.round(p.net).toLocaleString()} 張</b>
    <span class="k">買 ${Math.round(p.buy).toLocaleString()}／賣 ${Math.round(p.sell).toLocaleString()}${p.cost && p.cost > 0 ? `｜成本約 ${fmt(p.cost)}` : ""}</span></div>`;
  const last = rows[rows.length - 1];
  $("brDlgSum").innerHTML = `<div class="ch-cards">${card("最近 1 日", per(1))}${card("近 5 日", per(5))}${card("近 20 日", per(20))}${card("整段期間", per(rows.length))}</div>
    <div class="k">最後資料日 ${last ? last[0] : "–"}｜股價 ${last ? fmt(last[1]) : "–"}｜成本＝買賣超張數 × 當天均價（(高+低+2×收)/4）估算</div>`;
  const el = $("brChart");
  if (BR_CHART) { try { BR_CHART.remove(); } catch(e) {} }
  const ch = BR_CHART = LW.createChart(el, {autoSize: true, layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc", panes: {separatorColor: "#2a2e39"}},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    timeScale: {borderColor: "#2a2e39", rightOffset: 2}, crosshair: {mode: 0}, localization: TW_LOCALE});
  const px = ch.addSeries(LW.LineSeries, {color: "#ffd600", lineWidth: 2, priceLineVisible: false});
  px.setData(rows.filter(r => r[1] != null).map(r => ({time: r[0], value: r[1]})));
  const net = ch.addSeries(LW.HistogramSeries, {priceLineVisible: false}, 1);
  net.setData(rows.map(r => ({time: r[0], value: r[4], color: r[4] >= 0 ? "#f23645" : "#089981"})));
  const cum = ch.addSeries(LW.LineSeries, {color: "#4fc3f7", lineWidth: 1, priceLineVisible: false, priceScaleId: "cum"}, 1);
  cum.setData(rows.map(r => ({time: r[0], value: r[5]})));
  try { const pn = ch.panes(); [62, 38].forEach((f, i) => pn[i].setStretchFactor(f)); } catch(e) {}
  ch.timeScale().fitContent();
  $("brDlgTable").innerHTML = `<table class="lu-t"><tr><th>日期</th><th>收盤</th><th>買進(張)</th><th>賣出(張)</th><th>買賣總額</th><th>買賣超(張)</th><th>期間累計</th></tr>
    ${rows.slice().reverse().filter(r => r[2] || r[3]).map(r => `<tr><td>${r[0]}</td><td>${fmt(r[1])}</td><td>${r[2].toLocaleString()}</td><td>${r[3].toLocaleString()}</td>
      <td>${(r[2] + r[3]).toLocaleString()}</td><td class="${cls(r[4])}"><b>${r[4] > 0 ? "+" : ""}${r[4].toLocaleString()}</b></td><td class="${cls(r[5])}">${Math.round(r[5]).toLocaleString()}</td></tr>`).join("")}</table>
    <div class="k">圖：黃線＝股價；下方柱子＝每日買賣超（紅買綠賣）、藍線＝期間累計買賣超</div>`;
}
