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
    <div class="k" style="margin-bottom:4px">前15大買超合計 <span class="up">${sb.toLocaleString()}</span>｜前15大賣超合計 <span class="down">${Math.abs(ss).toLocaleString()}</span>｜🎯＝隔日沖分點</div>
    ${tb(d.buy, true)}<div style="height:8px"></div>${tb(d.sell, false)}
    <div class="k" style="margin-top:6px">點任一分點，可以看他在這檔股票最近一年的每日買賣超。資料：富邦 e 點通，每天約傍晚更新。</div>`;
  document.querySelectorAll("#brBody .br-row").forEach(tr => tr.onclick = () => {
    const k = tr.dataset.i, r = (k[0] === "B" ? d.buy : d.sell)[+k.slice(1)];
    brOpen(code, name, r);
  });
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
