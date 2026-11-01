// ---------- PTT 市場情緒頁 ----------
let MOOD = null, mdSel = null, mdKind = "intra", mdDetail = null, mdDailyChart = null, mdIntraChart = null;
const moodColor = s => s >= 40 ? "#f23645" : s >= 12 ? "#ff8a80" : s > -12 ? "#9e9e9e" : s > -40 ? "#4db6ac" : "#089981";
const KIND_NAME = {intra: "盤中閒聊", after: "盤後閒聊"};

async function moodShow(){
  if (!MOOD) await moodLoad();
  moodStatus();
}

async function moodLoad(){
  $("mdStatus").textContent = "讀取中…";
  MOOD = await api("/api/sentiment");
  const days = MOOD.days;
  $("mdDate").innerHTML = days.slice().reverse().map(d => `<option value="${d.date}">${d.date}</option>`).join("");
  if (!mdSel || !days.some(d => d.date === mdSel)) mdSel = days.length ? days[days.length - 1].date : null;
  $("mdDate").value = mdSel;
  $("mdStatus").textContent = days.length ? `共 ${days.length} 天資料（${days[0].date} ~ ${days[days.length - 1].date}）` : "還沒有資料，按「⟳ 計算最新情緒」";
  drawValid(); drawRebound(); drawTaiex();
  if (mdSel) await moodSelect(mdSel);
}

async function moodSelect(d){
  mdSel = d; $("mdDate").value = d;
  const day = MOOD.days.find(x => x.date === d) || {};
  mdDetail = await api(`/api/sentiment/day/${d}`);
  // 卡片：盤中（當天情緒）、盤後（隔天看法）
  const card = (kind, sub) => {
    const a = day[kind];
    if (!a) return `<div class="mcard"><div class="k">${KIND_NAME[kind]}</div><div class="k">沒有資料</div></div>`;
    const tags = mdDetail[kind] ? mdDetail[kind].tags : {};
    // PTT 用語本來就偏負面，所以跟 3 個月平均比較才看得出「比平常樂觀或悲觀」
    const all = MOOD.days.filter(x => x[kind]).map(x => x[kind].score);
    const avg = all.reduce((s, x) => s + x, 0) / Math.max(1, all.length);
    const rank = all.filter(x => x < a.score).length / Math.max(1, all.length) * 100;
    const diff = a.score - avg;
    return `<div class="mcard"><div class="k">${KIND_NAME[kind]}　${sub}</div>
      <div class="mscore" style="color:${moodColor(a.score)}">${a.score > 0 ? "+" : ""}${fmt(a.score, 1)}</div>
      <div class="mlabel" style="background:${moodColor(a.score)}">${a.label}</div>
      <span class="k">　3 個月平均 ${fmt(avg, 1)}，今天${diff >= 0 ? "高" : "低"} <b class="${cls(diff)}">${fmt(Math.abs(diff), 1)}</b> 分｜比 ${fmt(rank, 0)}% 的日子樂觀</span>
      <div class="k">推文 ${a.n.toLocaleString()} 則（推${tags["推"] || 0}／噓${tags["噓"] || 0}／→${tags["→"] || 0}）｜情緒強度 ${fmt(a.heat)}</div></div>`;
  };
  const chg = (v, txt) => v == null ? "" : `<div class="k">${txt} <span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v)}%</span></div>`;
  $("mdCards").innerHTML =
    card("intra", `→ ${md(d)} 當天日盤`) + card("after", `→ 對 ${day.next_date ? md(day.next_date) : "下一個交易日"} 的看法`) +
    `<div class="mcard"><div class="k">加權指數</div><div class="mscore">${day.taiex ? fmt(day.taiex, 0) : "–"}</div>
      ${chg(day.taiex_chg, `${md(d)} 漲跌`)}${chg(day.next_chg, `${day.next_date ? md(day.next_date) : "隔天"} 漲跌`)}</div>`;
  drawIntra(); drawKw();
  if (mdDailyChart) mdDailyChart.markerApi.setMarkers([{time: d, position: "aboveBar", color: "#2962ff", shape: "arrowDown", text: "選取"}]);
  if (TX_CV && TX_CV.chart) { TX_CV.redraw({shades: [[d, d, "情緒日"]]}); txFit(); }
}

function drawDaily(){
  const el = $("mdDaily");
  if (mdDailyChart) mdDailyChart.chart.remove();
  const chart = LW.createChart(el, {width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: "#131722"}, textColor: "#d1d4dc", panes: {separatorColor: "#2a2e39"}},
    grid: {vertLines: {color: "#1e222d"}, horzLines: {color: "#1e222d"}},
    rightPriceScale: {borderColor: "#2a2e39"}, timeScale: {borderColor: "#2a2e39"}, localization: TW_LOCALE});
  const tx = chart.addSeries(LW.LineSeries, {color: "#d1d4dc", lineWidth: 2, priceLineVisible: false, title: "加權指數"}, 0);
  tx.setData(MOOD.days.filter(d => d.taiex).map(d => ({time: d.date, value: d.taiex})));
  const hi = chart.addSeries(LW.HistogramSeries, {priceLineVisible: false, lastValueVisible: false, title: "盤中"}, 1);
  hi.setData(MOOD.days.filter(d => d.intra).map(d => ({time: d.date, value: d.intra.score, color: moodColor(d.intra.score)})));
  const af = chart.addSeries(LW.LineSeries, {color: "#ffd600", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
    pointMarkersVisible: true, title: "盤後"}, 1);
  af.setData(MOOD.days.filter(d => d.after).map(d => ({time: d.date, value: d.after.score})));
  try { chart.panes()[0].setStretchFactor(55); chart.panes()[1].setStretchFactor(45); } catch(e) {}
  chart.timeScale().fitContent();
  chart.subscribeClick(p => { if (p.time) moodSelect(p.time); });
  mdDailyChart = {chart, markerApi: LW.createSeriesMarkers(hi, [])};
}

function drawIntra(){
  const el = $("mdIntra");
  if (mdIntraChart) mdIntraChart.remove();
  const pts = k => ((mdDetail[k] || {}).timeline || []).filter(x => x.n >= 5).map(x => ({
    time: Date.UTC(+x.t.slice(0, 4), +x.t.slice(5, 7) - 1, +x.t.slice(8, 10), +x.t.slice(11, 13), +x.t.slice(14, 16)) / 1000,
    value: x.score, n: x.n}));
  const chart = mdIntraChart = LW.createChart(el, {width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: "#131722"}, textColor: "#d1d4dc"}, grid: {vertLines: {color: "#1e222d"}, horzLines: {color: "#1e222d"}},
    rightPriceScale: {borderColor: "#2a2e39"}, timeScale: {borderColor: "#2a2e39", timeVisible: true, secondsVisible: false},
    localization: TW_LOCALE});
  [["intra", "#2962ff"], ["after", "#ffd600"]].forEach(([k, color]) => {
    const s = chart.addSeries(LW.HistogramSeries, {priceLineVisible: false, lastValueVisible: false, title: KIND_NAME[k]});
    s.setData(pts(k).map(p => ({time: p.time, value: p.value, color: moodColor(p.value)})));
  });
  chart.timeScale().fitContent();
}

function drawKw(){
  document.querySelectorAll(".mdKind button").forEach(b => b.classList.toggle("on", b.dataset.k === mdKind));
  const a = mdDetail[mdKind];
  if (!a) { $("mdKw").innerHTML = `<div class="k">沒有資料</div>`; $("mdTop").innerHTML = ""; return; }
  const kws = a.keywords || [];
  const col = (title, list, color) => `<div><div class="kw-h" style="color:${color}">${title}</div>` +
    list.slice(0, 18).map(k => `<div class="kw-r"><span>${esc(k.w)}</span><span class="k">權重 ${k.weight > 0 ? "+" : ""}${k.weight}</span><b>${k.n}</b>
      <i style="width:${Math.min(100, k.n / Math.max(1, list[0] ? list[0].n : 1) * 100)}%;background:${color}"></i></div>`).join("") + `</div>`;
  $("mdKw").innerHTML = col("偏多關鍵字", kws.filter(k => k.weight > 0), "#f23645") + col("偏空關鍵字", kws.filter(k => k.weight < 0), "#089981");
  const list = (title, arr, color) => `<div class="kw-h" style="color:${color}">${title}</div>` +
    arr.map(x => `<div class="tp"><b style="color:${color}">${x.s > 0 ? "+" : ""}${x.s}</b> ${esc(x.c)} <span class="k">${x.t.slice(5)}</span></div>`).join("");
  $("mdTop").innerHTML = list("最偏多", a.top_bull || [], "#f23645") + list("最偏空", a.top_bear || [], "#089981");
}

let TX_CV = null;
async function drawTaiex(){
  const c = await api("/api/taiex");
  if (c.error) { $("mdTx").innerHTML = `<div class="k" style="padding:20px">${c.error}</div>`; return; }
  if (!TX_CV) {   // 跟 MACD 頁同一個 K 線元件；這張圖預設打開「關鍵價預測」
    TX_CV = new ChartView($("mdTx"), {visKey: "vis_taiex", visDefault: {kp: true}});
    TX_CV.bar.style.display = "none";
    TX_CV.onFit = txRange;
  }
  const r = c.row;
  $("mdTxInfo").innerHTML = `<span class="big ${cls(r.chg)}" style="font-size:18px">${fmt(r.close)}</span> <span class="${cls(r.chg)}">${r.chg > 0 ? "+" : ""}${fmt(r.chg)}%</span>
    <span class="k">（${r.date}）　明日摸底價</span> <b style="color:#e040fb">${fmt(r.shrink)}</b> <span class="k">明日金叉價</span> <b style="color:#ffd600">${fmt(r.cross)}</b>`;
  // 預設顯示跟情緒資料同一段期間（往前多 20 天）
  const first = MOOD.days.length ? MOOD.days[0].date : null;
  const sentiment = MOOD.days.map(d => ({time: d.date, intra: d.intra ? d.intra.score : null, after: d.after ? d.after.score : null}));
  TX_CV.draw(c.row, c, {sentiment, ...(mdSel ? {shades: [[mdSel, mdSel, "情緒日"]]} : {})});
  txFit();
}
// 預設顯示跟情緒資料同一段期間（往前多 20 天）
function txRange(){
  if (!TX_CV || !TX_CV.chart || !TX_CV.last || !MOOD) return;
  const bars = TX_CV.last.c.bars, first = MOOD.days.length ? MOOD.days[0].date : null;
  const i = first ? Math.max(0, bars.findIndex(b => b[0] >= first) - 20) : 0;
  TX_CV.chart.timeScale().setVisibleLogicalRange({from: i, to: bars.length + 2});
}
// 綁定「點 K 棒切換日期」（每次重畫後都要重新綁）
function txFit(){
  if (!TX_CV || !TX_CV.chart) return;
  TX_CV.chart.subscribeClick(p => { if (p.time && MOOD.days.some(d => d.date === p.time)) moodSelect(p.time); });
}

function drawRebound(){
  const r = MOOD.rebound;
  if (!r) { $("mdRebound").innerHTML = ""; return; }
  const pc = v => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v)}%</span>`;
  const th = r.thresholds.filter(x => x.n);
  const tbl = (rows, head, first) => `<table class="rb"><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr>` +
    rows.map(x => `<tr><td>${first(x)}</td><td>${x.n}</td><td>${x.up1 ?? "–"}%</td><td>${pc(x.r1)}</td><td>${pc(x.r3)}</td><td>${pc(x.r5)}</td></tr>`).join("") + `</table>`;
  const head = ["條件", "天數", "隔天漲機率", "隔天", "3日後", "5日後"];
  const avg = (arr, k) => { const v = arr.map(x => x[k]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  $("mdRebound").innerHTML =
    `<div class="k">當天收盤買進加權指數，持有到隔天／3日／5日的平均漲跌</div>` +
    `<div class="rb-h">① 盤中分數低於多少</div>` + tbl(th.filter(x => x.kind === "intra"), head, x => `盤中 ≤ ${x.thr}`) +
    `<div class="rb-h">② 盤後（夜盤）分數低於多少</div>` + tbl(th.filter(x => x.kind === "after"), head, x => `盤後 ≤ ${x.thr}`) +
    `<div class="rb-h">③ 連續恐慌第幾天（盤中 ≤ -12）<span class="k">　平均連續 ${r.avg_streak ?? "–"} 天、最長 ${r.max_streak ?? "–"} 天</span></div>` +
    tbl(r.streaks, head, x => `第 ${x.k}${x.k >= 4 ? "+" : ""} 天`) +
    `<div class="rb-h">④ 大盤波段低點／高點那天的情緒</div>
     <div class="vbox">低點 ${r.lows.length} 次：盤中平均 <b>${fmt(avg(r.lows, "intra"), 1)}</b>、盤後平均 ${fmt(avg(r.lows, "after"), 1)}、
       之前已連續恐慌平均 ${fmt(avg(r.lows, "streak"), 1)} 天，5 日後平均 ${pc(avg(r.lows, "r5"))}<br>
       <span class="k">${r.lows.map(x => `${md(x.date)}（${x.intra > 0 ? "+" : ""}${x.intra}）`).join("、")}</span><br>
       高點 ${r.highs.length} 次：盤中平均 <b>${fmt(avg(r.highs, "intra"), 1)}</b>、盤後平均 <b>${fmt(avg(r.highs, "after"), 1)}</b>，5 日後平均 ${pc(avg(r.highs, "r5"))}</div>
     <div class="k">⚠ 資料只有約 3 個半月，每格樣本很少，僅供參考</div>`;
}

function drawValid(){
  const v = MOOD.validation || {};
  const row = x => !x ? "" : `<div class="vbox"><b>${x.name}</b>（${x.n} 天）<br>
    相關係數 <b class="${x.corr > 0 ? "up" : x.corr < 0 ? "down" : ""}">${x.corr > 0 ? "+" : ""}${x.corr}</b>
    <span class="k">${Math.abs(x.corr) < 0.1 ? "（幾乎沒關係）" : x.corr > 0 ? "（情緒越樂觀越漲＝順勢）" : "（情緒越樂觀越跌＝反指標）"}</span><br>
    偏多（≥+12）時：${x.bull_n} 天，上漲 ${x.bull_up ?? "–"}%，平均 ${x.bull_avg != null ? (x.bull_avg > 0 ? "+" : "") + x.bull_avg + "%" : "–"}<br>
    偏空（≤-12）時：${x.bear_n} 天，上漲 ${x.bear_up ?? "–"}%，平均 ${x.bear_avg != null ? (x.bear_avg > 0 ? "+" : "") + x.bear_avg + "%" : "–"}</div>`;
  $("mdValid").innerHTML = (row(v.intra) + row(v.after)) ||
    `<div class="k">資料還不夠（至少要 5 天）</div>`;
}

async function moodStatus(){
  const s = await api("/api/sentiment/status");
  $("mdCompute").disabled = s.running;
  if (s.running) { $("mdStatus").textContent = s.msg; setTimeout(moodStatus, 1500); }
  else if (moodStatus.wasRunning) { moodStatus.wasRunning = false; MOOD = null; await moodLoad(); $("mdStatus").textContent += `｜上次計算 ${s.last || ""}`; return; }
  moodStatus.wasRunning = s.running;
}
$("mdCompute").onclick = async () => { await post("/api/sentiment/compute"); moodStatus.wasRunning = true; setTimeout(moodStatus, 500); };
$("mdDate").onchange = () => moodSelect($("mdDate").value);
document.querySelectorAll(".mdKind button").forEach(b => b.onclick = () => { mdKind = b.dataset.k; drawKw(); });
window.addEventListener("resize", () => {
  if (window.CUR_PAGE !== "sentiment") return;
  if (mdIntraChart) mdIntraChart.resize($("mdIntra").clientWidth, $("mdIntra").clientHeight);
  if (TX_CV) TX_CV.resize();
});
