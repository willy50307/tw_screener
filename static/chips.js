// ---------- 籌碼整理頁 ----------
let CH = null, chDate = "";
const CH_TABS = [["brief", "🧭 今日盤勢分析"], ["wave", "🌊 波浪"], ["setl", "📅 結算日"], ["warr", "🎫 權證分點"], ["opt", "📈 選擇權未平倉"], ["inst", "🏦 三大法人"], ["dt", "🎯 隔日沖分點"], ["trend", "🌊 資金流向"], ["margin", "💳 融資券／借券"], ["tuyang", "🤝 土洋同步"]];
let chTab = (() => { const u = new URLSearchParams(location.search).get("ch"); if (u) return u;   // 網址 ?page=chips&ch=setl 可以直接開某個分頁
  try { return localStorage.getItem("chTab") || "inst"; } catch(e) { return "inst"; } })();
let chWho = "fi", chEtf = false;
const chN = (v, d = 0) => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${Number(v).toLocaleString(undefined, {minimumFractionDigits: d, maximumFractionDigits: d})}</span>`;
const chP = (v, d = 2) => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, d)}%</span>`;
const chL = v => v == null ? "–" : Number(v).toLocaleString(undefined, {maximumFractionDigits: 0});
const chCode = r => `<td class="ch-c" data-c="${r.code}"><b>${r.code}</b></td>`;
const chName = r => `<td class="ch-c" data-c="${r.code}">${r.market === "上櫃" ? "<span class='k'>(櫃)</span>" : ""}${r.name || ""}</td>`;
const chIsEtf = c => !/^[1-9]\d{3}$/.test(c);

function chTable(cols, rows, cls_ = ""){
  return `<table class="lu-t ${cls_}"><tr>${cols.map(c => `<th>${c[0]}</th>`).join("")}</tr>
    ${rows.map((r, i) => `<tr>${cols.map(c => c[1](r, i)).join("")}</tr>`).join("") || `<tr><td colspan="${cols.length}" class="k">沒有資料</td></tr>`}</table>`;
}

async function chShow(){
  $("chTabs").innerHTML = `<select class="sub-sel">${CH_TABS.map(([k, n]) => `<option value="${k}" ${k === chTab ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  $("chTabs").querySelector("select").onchange = e => { chTab = e.target.value; try { localStorage.setItem("chTab", chTab); } catch(err) {} chShow(); };
  if (window.renderPages) renderPages();
  if (chTab === "brief") { briefShow(); chStatus(); return; }
  if (chTab === "wave") { waveShow(); chStatus(); return; }
  if (chTab === "setl") { setlShow(); chStatus(); return; }
  if (chTab === "warr") { warrShow(); chStatus(); return; }
  if (chTab === "opt") { optShow(); chStatus(); return; }
  if (!CH || (chDate && CH.date !== chDate)) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">整理資料中…</div>`;
    try { CH = await api("/api/chips" + (chDate ? "?date=" + chDate : "")); } catch(e) { setTimeout(chShow, 3000); return; }
  }
  if (["brief", "wave", "setl", "opt", "warr"].includes(chTab)) return;   // CH 載入期間已經切到別的分頁
  chRender();
  chStatus();
}

function chRender(){
  if (chTab === "brief") return briefShow();
  if (chTab === "wave") return waveShow();
  if (chTab === "setl") return setlShow();
  if (chTab === "warr") return warrShow();
  if (chTab === "opt") return optShow();
  if (!CH || CH.error) { $("chBody").innerHTML = `<div class="k" style="padding:20px">${CH ? CH.error : ""}</div>`; return; }
  $("chDate").innerHTML = CH.dates.map(d => `<option ${d === CH.date ? "selected" : ""}>${d}</option>`).join("");
  const f = {inst: chInst, dt: chDt, trend: chTrend, margin: chMargin, tuyang: chTuyang}[chTab] || chInst;
  $("chBody").innerHTML = f();
  document.querySelectorAll("#chBody .ch-c").forEach(e => e.onclick = () => { showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
  document.querySelectorAll("#chBody [data-who]").forEach(b => b.onclick = () => { chWho = b.dataset.who; chRender(); });
  const etf = $("chEtf"); if (etf) etf.onchange = () => { chEtf = etf.checked; chRender(); };
  const ed = $("chDtEdit"); if (ed) ed.onclick = chEditDt;
  if (chTab === "inst") chRngBind();
}

// ① 三大法人
function chInst(){
  const s = CH.summary, x = CH.inst[chWho];
  const flt = k => chEtf ? (x[k + "_x"] || x[k].filter(r => !chIsEtf(r.code))) : x[k];   // 後端另給排除 ETF 的前 100
  const col = (label) => [["#", (r, i) => `<td>${i + 1}</td>`], ["代號", chCode], ["名稱", chName],
    [label, r => `<td>${chN(r[chWho])}</td>`], ["金額(億)", r => `<td>${chN(r[chWho + "_amt"], 2)}</td>`],
    ["收盤", r => `<td>${fmt(r.close)}</td>`], ["漲跌%", r => `<td>${chP(r.chg)}</td>`]];
  return `<div class="ch-cards">${["fi", "it", "dh", "dp"].map(k => [k, s[k]]).map(([k, v]) => `<div class="mcard ${k === chWho ? "on" : ""}" data-who="${k}">
      <span class="k">${v.name}</span><b>${v.official != null ? chN(v.official, 2) : chN(v.twse, 2)} 億</b>
      <span class="k">上市${v.official != null ? "（證交所公布）" : "（估算）"}｜上市＋上櫃估算 ${chN(v.amt, 2)} 億</span></div>`).join("")}</div>
    <div class="k" style="margin:-4px 0 8px">${CH.summary_all != null ? `上市三大法人合計 ${chN(CH.summary_all, 2)} 億｜` : ""}個股金額＝張數 × 收盤價估算。點上面的卡片切換法人</div>
    <div class="lu-box"><div class="lu-title">${x.name}　買超／賣超 前 100 名（${CH.date}）
      <label class="k" style="margin-left:12px"><input type="checkbox" id="chEtf" ${chEtf ? "checked" : ""}> 排除 ETF／債券</label></div>
    <div class="lu-row"><div class="grow ch-scroll">${chTable(col(x.name + "買超(張)"), flt("buy"))}</div>
      <div class="grow ch-scroll">${chTable(col(x.name + "賣超(張)"), flt("sell"))}</div></div></div>
    <div id="chRngBox">${chRngHtml()}</div>`;
}

// ①-2 某一類法人的區間買賣超（每天市場合計＋個股累計排行）
let CHR = {start: "", end: "", by: "lots", data: null, loading: false, err: ""}, CHR_CH = null;
function chRngDef(n){ const ds = CH.dates; return [ds[Math.min(n - 1, ds.length - 1)], CH.date]; }
function chRngSpans(daily){
  // 連續缺資料的日子合併成一段：[起, 迄, "上市、上櫃"]
  const out = [];
  daily.filter(d => d.miss.length).forEach(d => {
    const m = d.miss.join("、"), l = out[out.length - 1];
    if (l && l[2] === m && l[3] === daily.indexOf(d) - 1) { l[1] = d.date; l[3]++; } else out.push([d.date, d.date, m, daily.indexOf(d)]);
  });
  return out;
}
function chRngHtml(){
  const nm = CH.inst[chWho].name;
  if (!CHR.start) [CHR.start, CHR.end] = chRngDef(20);
  const D = CHR.data && CHR.data.who === chWho ? CHR.data : null;
  let h = `<div class="lu-box"><div class="lu-title">📅 ${nm}　區間買賣超
      <input type="date" id="chRs" value="${CHR.start}" min="2023-05-02"> ～ <input type="date" id="chRe" value="${CHR.end}">
      <button id="chRgo">查詢</button>
      ${[[5, "5日"], [20, "20日"], [60, "60日"], [120, "120日"], [0, "今年"]].map(([n, t]) => `<button class="chRq" data-n="${n}">${t}</button>`).join("")}
      <span class="k" style="margin-left:8px">${CHR.loading ? "計算中…" : CHR.err}</span></div>`;
  if (!D) return h + `<div class="k">選好日期按「查詢」。點上面的卡片換法人，區間會沿用</div></div>`;
  const full = D.n_full, spans = chRngSpans(D.daily);
  const miss = spans.length ? `<div class="k" style="color:#f0b429;margin:4px 0">⚠ 缺資料：${spans.map(s => `${s[0]}${s[1] !== s[0] ? "～" + s[1] : ""} 缺${s[2]}`).join("；")}。
      缺一邊的日子只加有資料的市場（圖上黃色柱），兩邊都缺的日子留白；區間合計只算兩市場都齊的 ${full} 天</div>` : "";
  h += `<div class="k" style="margin:4px 0">${D.start} ～ ${D.end}，共 ${D.n_days} 個交易日（資料齊全 ${full} 天）｜
      區間合計 ${chN(D.tot.amt, 2)} 億（${chN(D.tot.lots)} 張）｜金額＝張數 × 收盤價估算，含 ETF；資料庫最早 ${D.first}</div>${miss}
    <div id="chRngChart" style="height:280px;margin:6px 0"></div>`;
  const by = CHR.by, b = by === "amt" ? D.buy_amt : D.buy, s = by === "amt" ? D.sell_amt : D.sell;
  const col = lab => [["#", (r, i) => `<td>${i + 1}</td>`], ["代號", chCode], ["名稱", chName],
    [lab + "(張)", r => `<td>${chN(r.lots)}</td>`], ["金額(億)", r => `<td>${chN(r.amt, 2)}</td>`],
    ["買超天數", r => `<td>${r.buy_days}/${r.days}</td>`], ["收盤", r => `<td>${fmt(r.close)}</td>`], ["區間漲跌%", r => `<td>${chP(r.chg)}</td>`]];
  h += `<div class="lu-title" style="margin-top:8px">個股區間累計 前 100 名　排序：
      <label class="k"><input type="radio" name="chRby" value="lots" ${by === "lots" ? "checked" : ""}> 張數</label>
      <label class="k"><input type="radio" name="chRby" value="amt" ${by === "amt" ? "checked" : ""}> 金額</label>
      <label class="k" style="margin-left:12px"><input type="checkbox" id="chEtf2" ${chEtf ? "checked" : ""}> 排除 ETF／債券</label></div>
    <div class="lu-row"><div class="grow ch-scroll">${chTable(col(nm + "買超"), b)}</div>
      <div class="grow ch-scroll">${chTable(col(nm + "賣超"), s)}</div></div>
    <details style="margin-top:8px"><summary class="k">每日明細（${D.daily.length} 天）</summary><div class="ch-scroll">
      ${chTable([["日期", r => `<td>${r.date}</td>`], ["上市(億)", r => `<td>${r["上市"] ? chN(r["上市"].amt, 2) : "<span class='k'>缺</span>"}</td>`],
        ["上櫃(億)", r => `<td>${r["上櫃"] ? chN(r["上櫃"].amt, 2) : "<span class='k'>缺</span>"}</td>`],
        ["合計(億)", r => `<td>${chN(r.amt, 2)}</td>`], ["合計(張)", r => `<td>${chN(r.lots)}</td>`]], D.daily.slice().reverse())}</div></details></div>`;
  return h;
}
async function chRngLoad(){
  CHR.start = $("chRs").value; CHR.end = $("chRe").value;
  if (!CHR.start || !CHR.end) return;
  CHR.loading = true; CHR.err = ""; $("chRngBox").innerHTML = chRngHtml(); chRngBind();
  const who = chWho;
  try {
    const d = await api(`/api/chips/inst_range?who=${who}&start=${CHR.start}&end=${CHR.end}&etf=${chEtf ? 0 : 1}`);
    if (d.error) CHR.err = d.error; else CHR.data = d;
  } catch(e) { CHR.err = "讀取失敗（後端還沒重開？）"; }
  CHR.loading = false;
  if (chTab === "inst" && $("chRngBox")) { $("chRngBox").innerHTML = chRngHtml(); chRngBind(); }
}
function chRngBind(){
  if (!$("chRngBox")) return;
  $("chRgo").onclick = chRngLoad;
  document.querySelectorAll("#chRngBox .chRq").forEach(b => b.onclick = () => {
    const n = +b.dataset.n;
    if (n) [CHR.start, CHR.end] = chRngDef(n); else { CHR.end = CH.date; CHR.start = CH.date.slice(0, 4) + "-01-01"; }
    $("chRs").value = CHR.start; $("chRe").value = CHR.end; chRngLoad();
  });
  document.querySelectorAll("#chRngBox [name=chRby]").forEach(r => r.onchange = () => { CHR.by = r.value; $("chRngBox").innerHTML = chRngHtml(); chRngBind(); });
  const e2 = $("chEtf2"); if (e2) e2.onchange = () => { chEtf = e2.checked; chRender(); if (CHR.data) chRngLoad(); };
  document.querySelectorAll("#chRngBox .ch-c").forEach(e => e.onclick = () => { showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
  // 換了法人但還是舊資料 → 自動用同一段區間重查
  if (CHR.data && CHR.data.who !== chWho && !CHR.loading) { chRngLoad(); return; }
  chRngChart();
}
function chRngChart(){
  const el = $("chRngChart"), D = CHR.data;
  if (CHR_CH) { try { CHR_CH.remove(); } catch(e) {} CHR_CH = null; }
  if (!el || !D) return;
  const ch = CHR_CH = LW.createChart(el, {autoSize: true, layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc"},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    leftPriceScale: {visible: true, borderColor: "#2a2e39"}, timeScale: {borderColor: "#2a2e39"}, crosshair: {mode: 0}, localization: TW_LOCALE});
  const bar = ch.addSeries(LW.HistogramSeries, {priceLineVisible: false, title: "每日(億)"});
  bar.setData(D.daily.map(d => d.amt == null ? {time: d.date}
    : {time: d.date, value: d.amt, color: d.miss.length ? "rgba(240,180,41,.8)" : d.amt >= 0 ? "rgba(242,54,69,.75)" : "rgba(8,153,129,.75)"}));
  let cum = 0;
  const line = ch.addSeries(LW.LineSeries, {priceScaleId: "left", color: "#42a5f5", lineWidth: 2, priceLineVisible: false, title: "累計(億)"});
  line.setData(D.daily.map(d => { if (d.amt != null && !d.miss.length) cum += d.amt; return {time: d.date, value: Math.round(cum * 100) / 100}; }));
  const fit = () => { try { ch.timeScale().fitContent(); } catch(e) {} };
  fit(); [80, 400].forEach(ms => setTimeout(fit, ms));
}

// ② 隔日沖
function chDt(){
  const d = CH.daytrade;
  if (!d || d.error) return `<div class="lu-box k">${d ? d.error : "沒有資料"}</div>`;
  const st = d.stats, tag = (t, good) => `<span class="ch-tag ${good ? "g" : ""}">${t}</span>`;
  const heavy = d.today.filter(r => r.dt_pct >= 10);
  const bd = Object.fromEntries((st.by_dt || []).map(r => [r.dt_b, r]));
  const g = [];
  if (bd["沒有隔日沖"] && bd["隔日沖 ≧10%"]) g.push(`<li>隔日沖買超 ≧10% 成交量的漲停股，隔天平均開 ${chP(bd["隔日沖 ≧10%"].gap)}、收 ${chP(bd["隔日沖 ≧10%"].cl)}；沒有隔日沖的開 ${chP(bd["沒有隔日沖"].gap)}、收 ${chP(bd["沒有隔日沖"].cl)}（${st.period[0]} ~ ${st.period[1]}，${st.n.toLocaleString()} 次）</li>`);
  const top = d.score.filter(r => r.n >= 15).slice(0, 5);
  if (top.length) g.push(`<li>數據認定隔天最會倒貨的分點：${top.map(r => `<b>${r.branch}</b>（${r.sold}%）`).join("、")}</li>`);
  g.push(`<li>今天 ${d.today.length} 檔漲停股，其中 <b>${heavy.length}</b> 檔隔日沖買超超過成交量 10%：${heavy.slice(0, 12).map(r => r.name).join("、") || "無"}</li>`);
  const lots = r => `<td>${chL(r.lots)}</td>`;
  const cols = [["代號", chCode], ["名稱", chName],
    ["收盤", r => `<td>${fmt(r.close)}</td>`], ["成交張", lots], ["連板", r => `<td>${r.streak}</td>`], ["型態", r => `<td>${r.lu_type}</td>`],
    ["量比", r => `<td>${fmt(r.vr, 1)}倍</td>`], ["技術面", r => `<td style="text-align:left">${tag(r.brk, r.brk !== "未突破")}${tag(r.ma_st, r.ma_st === "均線多頭排列")}${tag(r.vol_st, false)}</td>`],
    ["20日漲幅", r => `<td>${chP(r.r20, 1)}</td>`], ["隔日沖買超", r => `<td>${chL(r.dt_lots)}</td>`],
    ["佔成交量", r => `<td class="${r.dt_pct >= 10 ? "up" : ""}"><b>${fmt(r.dt_pct, 1)}%</b></td>`],
    ["隔日沖分點", r => `<td style="text-align:left;white-space:normal;min-width:180px">${r.dt_names || "–"}</td>`],
    ["買超前三名", r => `<td style="text-align:left;white-space:normal;min-width:200px" class="k">${r.top3}</td>`]];
  const sc = (title, rows, extra = []) => `<div class="lu-box grow"><div class="lu-title">${title}</div>${chTable([
    ["分組", r => `<td>${[r.dt_b, r.top1, r.vol_st, r.lu_type, r.brk, r.ma_st, r.streak].filter(Boolean).join("｜")}</td>`],
    ["次數", r => `<td>${r.n.toLocaleString()}</td>`], ["隔天開盤", r => `<td>${chP(r.gap)}</td>`], ["隔天最高", r => `<td>${chP(r.hi)}</td>`],
    ["隔天收盤", r => `<td>${chP(r.cl)}</td>`], ["開盤→收盤", r => `<td>${chP(r.o2c)}</td>`], ["收紅機率", r => `<td>${fmt(r.red, 0)}%</td>`],
    ["續漲停", r => `<td>${fmt(r.lu, 0)}%</td>`]], rows)}</div>`;
  return `<div class="lu-box"><div class="lu-title">🎯 ${CH.date} 漲停股 × 隔日沖分點（依隔日沖佔成交量排序）</div>
      <div class="lu-guide"><ul>${g.join("")}</ul></div>
      <div class="ch-scroll" style="margin-top:8px">${chTable(cols, d.today)}</div>
      <div class="k" style="margin-top:6px">隔日沖分點＝名單內分點的買超張數；總公司（${d.hq.join("、")}）沒有地點，只有當天「買超第一名」才算。
        資料來源：每檔前 15 大買超／賣超分點。<button class="btn ghost" id="chDtEdit" style="padding:2px 8px;margin-left:6px">✏️ 編輯隔日沖名單</button></div></div>
    <div class="lu-row"><div class="lu-box grow"><div class="lu-title">🏆 今天鎖漲停分點排行（買超的漲停股檔數）</div><div class="ch-scroll">
      ${chTable([["分點", r => `<td>${r.dt ? "🎯 " : ""}${r.branch}</td>`], ["漲停股", r => `<td>${r.n}檔</td>`], ["買超張", r => `<td>${chL(r.lots)}</td>`],
        ["股票（買超張）", r => `<td style="text-align:left;white-space:normal" class="k">${r.stocks}</td>`]], d.rank_today)}</div></div>
      <div class="lu-box side"><div class="lu-title">🔍 數據認定的隔日沖分點（買超漲停股 ≧30 張，隔天出現在賣超名單的比例）</div><div class="ch-scroll">
      ${chTable([["分點", r => `<td>${r.dt ? "🎯 " : ""}${r.branch}</td>`], ["次數", r => `<td>${r.n}</td>`], ["隔天賣出", r => `<td><b>${fmt(r.sold, 0)}%</b></td>`],
        ["賣掉幾成", r => `<td>${fmt(r.sold_pct, 0)}%</td>`], ["平均買張", r => `<td>${chL(r.lots)}</td>`], ["隔天開", r => `<td>${chP(r.n_gap)}</td>`], ["隔天收", r => `<td>${chP(r.n_cl)}</td>`]], d.score)}</div>
      <div class="k">🎯＝在你的隔日沖名單內。外資券商隔天賣出比例低，代表是真的在買</div></div></div>
    <div class="lu-title" style="margin:4px 0 8px">📊 歷史統計：漲停股被隔日沖買進後，隔天怎麼走？（${st.period ? st.period[0] + " ~ " + st.period[1] : ""}，${st.n.toLocaleString()} 次）</div>
    <div class="lu-row">${sc("隔日沖買超佔成交量", st.by_dt)}${sc("買超第一名是不是隔日沖", st.by_top1)}</div>
    <div class="lu-row">${sc("隔日沖比重 × 量價", st.by_vol)}${sc("隔日沖比重 × 漲停型態", st.by_type)}</div>
    <div class="lu-row">${sc("隔日沖比重 × 是否突破", st.by_brk)}${sc("隔日沖比重 × 均線", st.by_ma)}</div>
    <div class="lu-row">${sc("隔日沖比重 × 連板數", st.by_streak)}</div>
    <div class="k">只列 15 次以上的分組。分點資料只有每檔前 15 名，小分點可能沒被算到。</div>`;
}

async function chEditDt(){
  const cur = (S.settings.dt_branches && S.settings.dt_branches.length) ? S.settings.dt_branches : CH.daytrade.dt_list;
  const v = prompt("隔日沖分點名單（用逗號分開，例如：凱基台北, 統一城中）\n留空 = 恢復內建名單", cur.join(", "));
  if (v === null) return;
  const list = v.split(/[,，、\s]+/).map(x => x.trim()).filter(Boolean);
  await post("/api/settings", {dt_branches: list});
  S = await api("/api/state");
  CH = null; chShow();
}

// ③ 資金流向
function chTrend(){
  const t = CH.trend, nm = {fi: "外資", it: "投信"};
  const indT = who => {
    const rows = t[who + "_ind"], mx = Math.max(...rows.map(r => Math.abs(r.d5)), 1);
    return chTable([["產業", r => `<td>${r.ind}</td>`], ["今天(億)", r => `<td>${chN(r.d1, 2)}</td>`],
      ["近5日(億)", r => `<td><div class="ch-bar"><i style="width:${Math.abs(r.d5) / mx * 50}%;${r.d5 >= 0 ? "left:50%;background:var(--up)" : `right:50%;background:var(--down)`}"></i><span>${chN(r.d5, 2)}</span></div></td>`],
      ["近20日(億)", r => `<td>${chN(r.d20, 2)}</td>`], ["今天買超家數", r => `<td>${r.nbuy}/${r.n}</td>`]], rows);
  };
  const stk = rows => chTable([["代號", chCode], ["名稱", chName],
    ["產業", r => `<td class="k">${r.ind}</td>`], ["今天(億)", r => `<td>${chN(r.s1, 2)}</td>`], ["近5日(億)", r => `<td>${chN(r.s5, 2)}</td>`],
    ["近20日(億)", r => `<td>${chN(r.s20, 2)}</td>`], ["連續", r => `<td>${r.streak > 0 ? `<span class="up">連買${r.streak}天</span>` : r.streak < 0 ? `<span class="down">連賣${-r.streak}天</span>` : "–"}</td>`],
    ["漲跌%", r => `<td>${chP(r.chg)}</td>`]], rows.slice(0, 20));
  const sum = who => {
    const r = t[who + "_ind"], inn = r.filter(x => x.d5 > 0).slice(0, 3), out = r.filter(x => x.d5 < 0).slice(-3).reverse();
    return `<li><b>${nm[who]}</b>近 5 日資金流入：${inn.map(x => `${x.ind}（${chN(x.d5, 1)}億）`).join("、") || "無"}；
      流出：${out.map(x => `${x.ind}（${chN(x.d5, 1)}億）`).join("、") || "無"}；
      加碼最多：${t[who + "_in5"].slice(0, 3).map(x => x.name).join("、")}；調節最多：${t[who + "_out5"].slice(0, 3).map(x => x.name).join("、")}</li>`;
  };
  const both = t.fi_ind.filter(a => a.d5 > 0 && t.it_ind.find(b => b.ind === a.ind && b.d5 > 0)).map(a => a.ind);
  const panel = who => `<div class="lu-box grow"><div class="lu-title">${nm[who]}：產業資金流向（依近 5 日排序）</div><div class="ch-scroll">${indT(who)}</div>
    <div class="lu-title" style="margin-top:10px">${nm[who]}：近 5 日加碼最多</div>${stk(t[who + "_in5"])}
    <div class="lu-title" style="margin-top:10px">${nm[who]}：近 5 日調節最多</div>${stk(t[who + "_out5"])}
    <div class="lu-title" style="margin-top:10px">${nm[who]}：近 20 日累計買超最多</div>${stk(t[who + "_in20"])}
    <div class="lu-title" style="margin-top:10px">${nm[who]}：近 20 日累計賣超最多</div>${stk(t[who + "_out20"])}
    <div class="lu-title" style="margin-top:10px">${nm[who]}：連續買超最多天</div>${stk(t[who + "_streak"])}</div>`;
  return `<div class="lu-box"><div class="lu-title">🌊 資金流向重點（排除 ETF；資料 ${t.n_days} 個交易日）</div>
      <div class="lu-guide"><ul>${sum("fi")}${sum("it")}<li>外資、投信<b>同步流入</b>的產業：${both.join("、") || "無"}</li></ul></div>
      ${t.n_days < 20 ? `<div class="k" style="margin-top:6px">⚠ 歷史資料還在補抓，近 20 日的數字目前只有 ${t.n_days} 天</div>` : ""}</div>
    <div class="lu-row">${panel("fi")}${panel("it")}</div>`;
}

// ④ 融資券／借券
function chMargin(){
  const m = CH.margin, tt = m.tot, mk = m.mkt || {};
  const mcard = nm => { const x = mk[nm];
    return `<div class="mcard"><span class="k">${nm}融資增減</span>${x
      ? `<b class="${x.amt > 0 ? "up" : x.amt < 0 ? "down" : ""}">${x.amt > 0 ? "+" : ""}${fmt(x.amt)} 億</b><span class="k">${chN(x.chg)} 張｜餘額 ${fmt(x.amt_bal)} 億</span>`
      : `<b class="k">尚未公布</b><span class="k">約晚上 9 點公布，會自動抓</span>`}</div>`; };
  const mkt = `<div class="ch-cards">${mcard("上市")}${mcard("上櫃")}</div>`;
  if (!m.tot.has) return `${mkt}<div class="lu-box k">${CH.date} 的個股融資券資料還沒抓（每天晚上 10 點自動抓）</div>`;
  const col = (label, k, bal, ex) => [["#", (r, i) => `<td>${i + 1}</td>`], ["代號", chCode], ["名稱", chName],
    [label, r => `<td>${chN(r[k])}</td>`], ["餘額", r => `<td>${chL(r[bal])}</td>`], ...(ex ? [[ex[0], r => `<td>${chL(r[ex[1]])}</td>`]] : []),
    ["收盤", r => `<td>${fmt(r.close)}</td>`], ["漲跌%", r => `<td>${chP(r.chg)}</td>`]];
  const pair = (title, up, dn, k, bal, exu, exd) => `<div class="lu-box"><div class="lu-title">${title}</div><div class="lu-row">
    <div class="grow ch-scroll">${chTable(col("增加(張)", k, bal, exu), up)}</div><div class="grow ch-scroll">${chTable(col("減少(張)", k, bal, exd), dn)}</div></div></div>`;
  return `${mkt}<div class="ch-cards"><div class="mcard"><span class="k">融資增減（全市場）</span><b>${chN(tt.m_chg)} 張</b></div>
      <div class="mcard"><span class="k">融券增減</span><b>${chN(tt.s_chg)} 張</b></div>
      <div class="mcard"><span class="k">借券賣出餘額增減</span><b>${chN(tt.l_chg)} 張</b></div></div>
    ${pair("💳 融資　增加／減少 前 100 名", m.m_up, m.m_dn, "m_chg", "m_bal")}
    ${pair("🐻 融券　增加／減少 前 100 名", m.s_up, m.s_dn, "s_chg", "s_bal")}
    ${m.tot.has_sbl ? pair("📉 借券賣出　增加／減少 前 100 名", m.l_up, m.l_dn, "l_chg", "bal", ["當日賣出", "sold"], ["當日還券", "ret"]) : `<div class="lu-box k">借券賣出資料還沒公布</div>`}`;
}

// ⑤ 土洋同步
function chTuyang(){
  const t = CH.tuyang;
  const col = label => [["#", (r, i) => `<td>${i + 1}</td>`], ["代號", chCode], ["名稱", chName],
    ["外資(張)", r => `<td>${chN(r.fi)}</td>`], ["投信(張)", r => `<td>${chN(r.it)}</td>`], [label, r => `<td><b>${chN(r.fiit_amt, 2)}</b></td>`],
    ["收盤", r => `<td>${fmt(r.close)}</td>`], ["漲跌%", r => `<td>${chP(r.chg)}</td>`]];
  return `<div class="lu-box"><div class="lu-title">🤝 土洋同步：外資＋投信 同買／同賣 前 100 名（排除 ETF，${CH.date}）
      <span class="k">同買 ${t.n_buy} 檔｜同賣 ${t.n_sell} 檔｜依兩者合計金額排序</span></div>
    <div class="lu-row"><div class="grow ch-scroll">${chTable(col("同買合計(億)"), t.buy)}</div><div class="grow ch-scroll">${chTable(col("同賣合計(億)"), t.sell)}</div></div></div>`;
}

async function chStatus(){
  let s;
  try { s = await api("/api/chips/status"); } catch(e) { return; }
  const p = Object.entries(s.progress || {}).filter(([k]) => k !== "msg").map(([k, v]) => `${k} ${v[0]}/${v[1]}`).join("｜");
  const r = s.range || {};
  $("chStatus").innerHTML = s.running ? `⏳ ${s.progress.msg || s.msg} ${p}`
    : `資料庫：法人 ${r.inst ? r.inst[2] : 0} 天｜融資券 ${r.margin ? r.margin[2] : 0} 天｜借券 ${r.sbl ? r.sbl[2] : 0} 天｜分點 ${r.broker ? r.broker[2] : 0} 天` +
      `｜今天：法人＋分點 ${s.eve_done ? "✅" : "⏳ 晚上 7 點自動抓"}、融資券＋借券 ${s.night_done ? "✅" : "⏳ 晚上 10 點自動抓"}${s.error ? "｜❌ " + s.error : ""}`;
  if (s.running) { setTimeout(chStatus, 3000); chWasRunning = true; }
  else if (chWasRunning) { chWasRunning = false; CH = null; if (window.CUR_PAGE === "chips") chShow(); }
}
let chWasRunning = false;

$("chDate").onchange = () => { if (chTab === "warr") { warrDate = $("chDate").value; WARR = null; } if (chTab === "opt") optDate = $("chDate").value; else if (chTab === "brief") briefDate = $("chDate").value; else chDate = $("chDate").value; chShow(); };
$("chFetch").onclick = async () => { await post("/api/chips/update", {days: 7}); setTimeout(chStatus, 800); };
$("chBack").onclick = async () => {
  if (!confirm("補抓過去一年的法人／融資券／借券，和近半年漲停股的券商分點？\n第一次大約 1~2 小時，會在背景跑，可以繼續用 App。")) return;
  await post("/api/chips/update", {days: 365}); setTimeout(chStatus, 800);
};


// ---------- 選擇權未平倉 ----------
let OPT = null, optDate = "", optWin = 5, optGrp = "t10s", optCt = 0, OPT_CHART = null;   // optCt 0＝最近的月選
let OPT_ST = null;   // 載入 OPT 時的 /api/options/status，用來判斷背景更新後要不要重載
const optStamp = s => s ? [s.inst && s.inst[1], s.strike && s.strike[1], s.tx].join("|") : "";
// 每分鐘看一次：背景排程（或別的視窗）抓完新資料就丟掉舊的 OPT；開著這個分頁才重畫
setInterval(async () => {
  if (!OPT || !OPT_ST) return;
  let s; try { s = await api("/api/options/status"); } catch(e) { return; }
  if (s.running || (optStamp(s) === optStamp(OPT_ST) && !OPT_ST.running)) return;
  const ds = OPT.dates || [];
  if (optDate === ds[ds.length - 1]) optDate = "";   // 原本看最新一天 → 跳到新的一天
  OPT = null;
  if (window.CUR_PAGE === "chips" && chTab === "opt") optShow();
}, 60000);
let optSess = lsGet("optSess", "TX"), optTf = lsGet("optTf", "D");
const OPT_G = {foreign: "外資", t10s: "十大特定法人", t10x: "十大非特定法人", dealer: "自營商"};
const viewCls = v => v === "偏多" ? "up" : v === "偏空" ? "down" : "";

async function optShow(){
  if (chTab !== "opt") return;        // 重試／計時器觸發時已經切到別的分頁，不要蓋掉別頁的內容
  if (!OPT || (optDate && OPT.date !== optDate)) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">整理選擇權資料中…</div>`;
    try { OPT = await api("/api/options" + (optDate ? "?date=" + optDate : "")); } catch(e) { setTimeout(optShow, 3000); return; }
    try { OPT_ST = await api("/api/options/status"); } catch(e) {}
  }
  if (chTab !== "opt") return;       // 載入期間已經切到別的分頁
  if (OPT.error) { $("chBody").innerHTML = `<div class="k" style="padding:20px">${OPT.error}</div>`; return; }
  $("chDate").innerHTML = OPT.dates.map(d => `<option ${d === OPT.date ? "selected" : ""}>${d}</option>`).join("");
  $("chBody").innerHTML = `<div class="opt-layout"><div class="opt-main">${optHtml()}</div><aside class="opt-side" id="optSide">${oiPanel()}</aside></div>`;
  oiBind();
  document.querySelectorAll("#chBody [data-win]").forEach(b => b.onclick = () => { optWin = +b.dataset.win; optShow(); });
  document.querySelectorAll("#chBody [data-grp]").forEach(b => b.onclick = () => { optGrp = b.dataset.grp; optShow(); });
  document.querySelectorAll("#chBody [data-sess]").forEach(b => b.onclick = () => { optSess = b.dataset.sess; lsSet("optSess", optSess); optShow(); });
  document.querySelectorAll("#chBody [data-tf]").forEach(b => b.onclick = () => { optTf = b.dataset.tf; lsSet("optTf", optTf); optShow(); });
  optChart();
}

function optHtml(){
  const o = OPT, t = o.tx, sm = o.summary, st = o.strikes, pc = o.pc[o.pc.length - 1];
  const reads = o.reads[optWin] || [];
  const ct = st && st.contracts[Math.min(optCt, st.contracts.length - 1)];
  const card = (k, v, s) => `<div class="mcard"><span class="k">${k}</span><b>${v}</b><span class="k">${s || ""}</span></div>`;
  const chg = (v) => v == null ? "" : `<span class="k">${v > 0 ? "+" : ""}${Math.round(v).toLocaleString()}</span>`;
  const row = r => `<tr><td>${r.name}</td>${["bc", "sc"].map(k => `<td>${chL(r[k])}${chg(r[k + "_" + optWin])}</td>`).join("")}
    <td><b>${chN(r.bc - r.sc)}</b></td>${["bp", "sp"].map(k => `<td>${chL(r[k])}${chg(r[k + "_" + optWin])}</td>`).join("")}
    <td><b>${chN(r.bp - r.sp)}</b></td><td>${chN(r.fut)}${chg(r["fut_" + optWin])}</td><td>${r.bull_amt != null ? chN(r.bull_amt, 2) + " 億" : "–"}</td></tr>`;
  const mx = ct ? Math.max(...ct.dist.map(x => Math.max(x.c, x.p)), 1) : 1;
  const resK = new Set(ct ? (ct.s_res.length ? ct.s_res : ct.res).map(x => x.k) : []), supK = new Set(ct ? (ct.s_sup.length ? ct.s_sup : ct.sup).map(x => x.k) : []);
  const sv = v => v ? `<span class="${v > 0 ? "opt-sell" : "opt-cover"}">${v > 0 ? "賣+" : "補"}${Math.abs(v).toLocaleString()}</span>` : "";
  const latest = o.dates[o.dates.length - 1], ss = OPT_ST;
  return `<div class="k" style="margin:2px 0 6px">📅 資料日期 <b>${o.date}</b>${o.date !== latest ? `（最新 ${latest}）` : ""}${ss ? `｜資料庫：未平倉 ${ss.inst[1] || "–"}、履約價 ${ss.strike[1] || "–"}、台指期 ${ss.tx || "–"}${ss.running ? "｜⏳ 更新中…" : ""}` : ""}</div>
    <div class="ch-cards">
      ${card("台指期（近月）", fmt(t.close, 0), `5日 ${chP(t.chg5)}｜10日 ${chP(t.chg10)}${t.night ? `｜夜盤 ${chP(t.night.chg)}` : ""}`)}
      ${card("綜合判斷（大戶）", `<span class="${viewCls(sm.view)}">${sm.view}</span>`, `分數 ${sm.score > 0 ? "+" : ""}${sm.score}（外資＋十大，近 1 週權重最高）`)}
      ${card("Put/Call 未平倉比", pc ? pc.oi + "%" : "–", `成交量比 ${pc ? pc.vol + "%" : "–"}｜>100% 代表 Put 比較多`)}
      ${card("近 20 日區間", `${fmt(t.lo20, 0)} ~ ${fmt(t.hi20, 0)}`, "台指期日盤最高／最低")}</div>
    <div class="lu-box"><div class="lu-title">🧠 大戶們在做什麼？（${o.date}）
      <span class="lu-studies" style="margin-left:10px">${[[5, "近 1 週"], [10, "近 2 週"], [20, "近 1 個月"]].map(([w, n]) => `<button data-win="${w}" class="${w === optWin ? "on" : ""}">${n}</button>`).join("")}</span></div>
      <div class="opt-reads">${reads.map(x => `<div class="opt-read"><div><b>${x.group}</b> <span class="opt-view ${viewCls(x.view)}">${x.view}</span>
        <span class="k">淨Call ${chN(x.nc)}（${x.dnc > 0 ? "+" : ""}${x.dnc.toLocaleString()}）｜淨Put ${chN(x.np)}（${x.dnp > 0 ? "+" : ""}${x.dnp.toLocaleString()}）</span></div>
        <ul>${x.notes.map(n => `<li>${n}</li>`).join("")}</ul>
        ${x.settle.length ? `<div class="k">⚠ 期間內有月選結算（${x.settle.join("、")}），未平倉減少可能是到期，不一定是主動回補</div>` : ""}</div>`).join("")}</div>
      <div class="lu-guide" style="margin-top:8px"><b>📍 支撐壓力（依選擇權未平倉）</b><ul>${sm.lines.map(l => `<li>${l}</li>`).join("")}</ul></div>
      <div class="k" style="margin-top:6px">🔎 怎麼推估「賣方新增」：每天每個履約價的未平倉變化，配合隱含波動率（IV）變化——
        未平倉增加＋IV 下降＝賣方主動壓價新增；未平倉增加＋IV 上升＝買方追價；未平倉減少＋IV 上升＝賣方回補。用 IV 而不是權利金，是為了排除大盤漲跌的影響。<br>
        淨Call／淨Put＝買方未平倉 − 賣方未平倉（負的＝淨賣方）。賣方通常是大戶：賣 Call 的履約價是他們認為漲不過去的位置，賣 Put 的是認為跌不破的位置。
        十大交易人已扣掉週選，只看月選部位。</div></div>
    <div class="lu-box"><div class="lu-title">📈 台指期 × 大戶選擇權淨部位
      <span class="lu-studies" style="margin-left:10px">${[["TX", "日夜盤"], ["TXD", "日盤"]].map(([k, n]) => `<button data-sess="${k}" class="${k === optSess ? "on" : ""}">${n}</button>`).join("")}</span>
      <span class="lu-studies">${[["D", "日K"], ["W", "週K"], ["M", "月K"], ["60", "60分"], ["5", "5分"]].map(([k, n]) => `<button data-tf="${k}" class="${k === optTf ? "on" : ""}">${n}</button>`).join("")}</span>
      <span class="lu-studies" style="margin-left:10px">${Object.entries(OPT_G).map(([g, n]) => `<button data-grp="${g}" class="${g === optGrp ? "on" : ""}">${n}</button>`).join("")}</span>
      <span class="k" style="margin-left:auto">K 線上的虛線：<span style="color:#f23645">紅＝Call 壓力</span>、<span style="color:#26a69a">綠＝Put 支撐</span></span></div>
      <div id="optChart" style="height:520px"></div>
      <div class="k">日K 第二格：<span style="color:#f23645">淨 Call</span>、<span style="color:#26a69a">淨 Put</span>（往下＝賣方增加）；第三格：台指期淨部位（口）。日夜盤＝前一晚 15:00 夜盤＋當天日盤；分K 為期交所逐筆成交整理（近 30 個交易日）</div></div>
    <div class="lu-row"><div class="lu-box grow"><div class="lu-title">🏦 大戶分類　選擇權／期貨未平倉（口）　<span class="k">小字＝${{5: "近 1 週", 10: "近 2 週", 20: "近 1 個月"}[optWin]}變化</span></div>
      <div class="ch-scroll"><table class="lu-t"><tr><th>身份</th><th>買 Call</th><th>賣 Call</th><th>淨 Call</th><th>買 Put</th><th>賣 Put</th><th>淨 Put</th><th>台指期淨部位</th><th>選擇權偏多金額</th></tr>
        ${o.table.map(row).join("")}</table></div>
      <div class="k">選擇權偏多金額＝（買Call−賣Call）−（買Put−賣Put）的權利金市值，正的＝偏多。十大交易人（非特定法人）＝十大交易人 − 其中的特定法人，多半是大戶自然人／私人公司。</div></div>
    </div>`;
}

async function optChart(){
  const el = $("optChart"); if (!el) return;
  let c;
  try { c = await api(`/api/stock/${optSess}?tf=${optTf}&n=${optTf === "D" ? 120 : (optTf === "5" || optTf === "60") ? -1 : 0}`); } catch(e) { return; }
  if (!$("optChart")) return;
  if (OPT_CHART) { try { OPT_CHART.remove(); } catch(e) {} }
  const intra = optTf === "5" || optTf === "60";
  const ch = OPT_CHART = LW.createChart(el, {autoSize: true,
    layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc", panes: {separatorColor: "#2a2e39"}},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    timeScale: {borderColor: "#2a2e39", rightOffset: 3, timeVisible: intra, secondsVisible: false}, crosshair: {mode: 0}, localization: TW_LOCALE});
  if (!c || !c.bars || !c.bars.length) { el.innerHTML = `<div class="k" style="padding:20px">${(c && c.error) || "沒有資料"}</div>`; return; }
  const k = ch.addSeries(LW.CandlestickSeries, {upColor: "#f23645", downColor: "#089981", borderUpColor: "#f23645", borderDownColor: "#089981",
    wickUpColor: "#f23645", wickDownColor: "#089981", priceLineVisible: false});
  k.setData(c.bars.map(([t, o, h, l, cl]) => ({time: t, open: o, high: h, low: l, close: cl})));
  if (c.ma20) ch.addSeries(LW.LineSeries, {color: "#e040fb", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
    .setData(c.ma20.map(([t, v]) => ({time: t, value: v})));
  if (c.ma60) ch.addSeries(LW.LineSeries, {color: "#26c6da", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
    .setData(c.ma60.map(([t, v]) => ({time: t, value: v})));
  const ct = OPT.strikes && (OPT.strikes.contracts.find(c => c.kind === "monthly") || OPT.strikes.contracts[0]);
  if (ct) {
    (ct.s_res.length ? ct.s_res : ct.res).slice(0, 2).forEach((x, i) => k.createPriceLine({price: x.k, color: "#f23645", lineWidth: i ? 1 : 2, lineStyle: 2, axisLabelVisible: true, title: `壓 ${x.k}`}));
    (ct.s_sup.length ? ct.s_sup : ct.sup).slice(0, 2).forEach((x, i) => k.createPriceLine({price: x.k, color: "#26a69a", lineWidth: i ? 1 : 2, lineStyle: 2, axisLabelVisible: true, title: `撐 ${x.k}`}));
  }
  const vol = ch.addSeries(LW.HistogramSeries, {priceLineVisible: false, priceFormat: {type: "volume"}}, 1);
  vol.setData(c.bars.map(([t, o, h, l, cl, v]) => ({time: t, value: v, color: cl >= o ? "rgba(242,54,69,.5)" : "rgba(8,153,129,.5)"})));
  if (optTf === "D") {           // 日K 才有每天的大戶部位
    const L = OPT.lines[optGrp] || OPT.lines.foreign, days = c.bars.map(b => b[0]);
    const m = key => Object.fromEntries(L[key]);
    const bc = m("bc"), sc = m("sc"), bp = m("bp"), sp = m("sp"), fu = m("fut");
    const pts = f => days.filter(d => f(d) != null && !isNaN(f(d))).map(d => ({time: d, value: f(d)}));
    const line = (data, color, pane) => ch.addSeries(LW.LineSeries, {color, lineWidth: 2, priceLineVisible: false}, pane).setData(data);
    line(pts(d => bc[d] == null || sc[d] == null ? null : bc[d] - sc[d]), "#f23645", 2);
    line(pts(d => bp[d] == null || sp[d] == null ? null : bp[d] - sp[d]), "#26a69a", 2);
    const fs = ch.addSeries(LW.HistogramSeries, {priceLineVisible: false}, 3);
    fs.setData(pts(d => fu[d]).map(p => ({...p, color: p.value >= 0 ? "rgba(242,54,69,.6)" : "rgba(8,153,129,.6)"})));
    try { const pn = ch.panes(); [52, 10, 22, 16].forEach((f, i) => pn[i].setStretchFactor(f)); } catch(e) {}
  } else {
    try { const pn = ch.panes(); [80, 20].forEach((f, i) => pn[i].setStretchFactor(f)); } catch(e) {}
  }
  const n = c.bars.length, show = optTf === "5" ? (optSess === "TX" ? 230 : 120) : optTf === "60" ? 90 : 0;
  const fit = () => { if (show && n > show) ch.timeScale().setVisibleLogicalRange({from: n - show, to: n + 2}); else ch.timeScale().fitContent(); };
  fit(); [60, 300].forEach(ms => setTimeout(fit, ms));     // 圖剛建立時還沒有寬度，晚一點再設一次
}


// ---------- 🧭 今日盤勢分析 ----------
let BRIEF = null, briefDate = "", BRIEF_CHART = null;
async function briefShow(){
  if (chTab !== "brief") return;      // 重試／計時器觸發時已經切到別的分頁，不要蓋掉別頁的內容
  if (!BRIEF || (briefDate && BRIEF.date !== briefDate)) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">整理今日盤勢中…（第一次大約 10~20 秒）</div>`;
    try { BRIEF = await api("/api/brief" + (briefDate ? "?date=" + briefDate : "")); } catch(e) { setTimeout(briefShow, 3000); return; }
  }
  if (chTab !== "brief") return;       // 載入期間已經切到別的分頁
  const B = BRIEF;
  if (B.error) { $("chBody").innerHTML = `<div class="k" style="padding:20px">${B.error}</div>`; return; }
  if (OPT && OPT.dates) $("chDate").innerHTML = OPT.dates.map(d => `<option ${d === B.date ? "selected" : ""}>${d}</option>`).join("");
  else if (CH && CH.dates) $("chDate").innerHTML = CH.dates.map(d => `<option ${d === B.date ? "selected" : ""}>${d}</option>`).join("");
  else $("chDate").innerHTML = `<option>${B.date}</option>`;
  const S = B.summary, tx = B.tx;
  const ul = (arr, empty) => arr && arr.length ? `<ul>${arr.map(x => `<li>${x}</li>`).join("")}</ul>` : `<div class="k">${empty || "資料還沒齊"}</div>`;
  const stk = (rows, cols) => chTable([["代號", chCode], ["名稱", r => `<td class="ch-c" data-c="${r.code}">${r.name}</td>`], ["族群", r => `<td class="k">${r.ind}</td>`], ...cols], rows || []);
  const ncols = who => [["連續", r => `<td>${r.streak > 0 ? `<span class="up">連買${r.streak}天</span>` : r.streak < 0 ? `<span class="down">連賣${-r.streak}天</span>` : "–"}</td>`],
    ["今天(億)", r => `<td>${chN(r.today, 2)}</td>`], ["5日(億)", r => `<td>${chN(r.a5, 2)}</td>`], ["20日(億)", r => `<td>${chN(r.a20, 2)}</td>`],
    ["20日佔量", r => `<td>${r.pct20 == null ? "–" : fmt(r.pct20, 1) + "%"}</td>`], ["今天", r => `<td>${chP(r.r1)}</td>`], ["5日", r => `<td>${chP(r.r5, 1)}</td>`], ["20日", r => `<td>${chP(r.r20, 1)}</td>`]];
  const h = [];
  // ===== 概要 =====
  h.push(`<div class="lu-box brief-sum"><div class="lu-title">🧭 ${B.date} 今日盤勢概要</div>
    <div class="brief-grid">
      <div><b>📈 台指期走勢</b>${ul(S.tx)}</div>
      <div><b>🔍 為什麼這樣走（籌碼推論，依重要性排序）</b>${ul(S.why, "籌碼資料還沒齊（期貨選擇權約下午 4 點、法人約 4~5 點）")}</div>
      <div><b>🏭 族群與個股</b>${ul(S.stocks, "三大法人資料還沒公布")}</div>
      <div><b>👀 接下來觀察</b>${ul(S.watch)}</div>
    </div>
    <div class="k" style="margin-top:6px">以上是依籌碼資料用固定規則自動整理的推論，不是確定的因果；詳細數據在下方。</div></div>`);
  // ===== 台指期 =====
  if (tx) {
    const us = tx.us || {};
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">① 台指期走勢（近月）<span class="k" style="margin-left:8px">5 分K：前一晚夜盤＋今天日盤</span></div>
      <div id="briefChart" style="height:360px"></div></div>
      <div class="lu-box side"><div class="lu-title">盤中波段</div>
      ${chTable([["時間", r => `<td>${r.from}~${r.to}</td>`], ["價位", r => `<td>${fmt(r.a, 0)} → ${fmt(r.b, 0)}</td>`], ["漲跌", r => `<td>${chN(r.chg)}</td>`]], (tx.intra || {}).waves || [])}
      <div class="lu-title" style="margin-top:10px">關鍵數字</div>
      ${chTable([["項目", r => `<td>${r[0]}</td>`], ["數值", r => `<td style="text-align:left">${r[1]}</td>`]], [
        ["日盤", `開 ${fmt(tx.open, 0)}｜高 ${fmt(tx.high, 0)}｜低 ${fmt(tx.low, 0)}｜收 ${fmt(tx.close, 0)}（${chN(tx.chg)}）`],
        ["全盤（含夜盤）", `開 ${fmt(tx.full.open, 0)}｜高 ${fmt(tx.full.high, 0)}｜低 ${fmt(tx.full.low, 0)}`],
        tx.night ? ["夜盤", `${fmt(tx.night.open, 0)} → ${fmt(tx.night.close, 0)}（高 ${fmt(tx.night.high, 0)} ${tx.night.hi_t}、低 ${fmt(tx.night.low, 0)} ${tx.night.lo_t}）`] : ["夜盤", "–"],
        ["均線", `5日 ${fmt(tx.ma[5], 0)}｜10日 ${fmt(tx.ma[10], 0)}｜20日 ${fmt(tx.ma[20], 0)}｜60日 ${fmt(tx.ma[60], 0)}`],
        tx.taiex ? ["加權指數／價差", `${fmt(tx.taiex.close)}（${chP(tx.taiex.chg_pct)}）｜期現貨價差 ${chN(tx.taiex.basis)}`] : ["加權指數", "–"],
        ["成交量（口，每小時）", Object.entries((tx.intra || {}).vol_hour || {}).map(([k, v]) => `${k}點 ${v.toLocaleString()}`).join("｜")],
        ...[["^SOX", "費半"], ["^IXIC", "那斯達克"], ["^GSPC", "標普500"]].filter(([k]) => us[k]).map(([k, n]) => [`前一晚${n}（${us[k].date}）`, `${chP(us[k].chg)}｜開→收 ${chP(us[k].o2c)}`])])}
      </div></div>`);
  }
  // ===== 現貨法人 =====
  const sp = B.spot || {};
  if (!sp.error && sp.summary) {
    const s = sp.summary;
    const rowsI = [["fi", "外資"], ["it", "投信"], ["dh", "自營商(避險)"], ["dp", "自營商(自行買賣)"]].map(([k, n]) => [n, s[k].official, s[k].amt]);
    const col = (k) => [["#", (r, i) => `<td>${i + 1}</td>`], ["代號", chCode], ["名稱", chName], ["張數", r => `<td>${chN(r[k])}</td>`], ["金額(億)", r => `<td>${chN(r[k + "_amt"], 2)}</td>`], ["漲跌", r => `<td>${chP(r.chg)}</td>`]];
    h.push(`<div class="lu-box"><div class="lu-title">② 現貨三大法人</div>
      ${chTable([["身份", r => `<td>${r[0]}</td>`], ["上市（證交所公布）", r => `<td>${r[1] == null ? "–" : chN(r[1], 2) + " 億"}</td>`], ["上市＋上櫃（估算）", r => `<td>${chN(r[2], 2)} 億</td>`]], rowsI)}
      <div class="lu-row" style="margin-top:8px">
        <div class="grow"><div class="lu-title">外資買超</div>${chTable(col("fi"), sp.fi_buy)}</div><div class="grow"><div class="lu-title">外資賣超</div>${chTable(col("fi"), sp.fi_sell)}</div></div>
      <div class="lu-row"><div class="grow"><div class="lu-title">投信買超</div>${chTable(col("it"), sp.it_buy)}</div><div class="grow"><div class="lu-title">投信賣超</div>${chTable(col("it"), sp.it_sell)}</div></div>
      </div>`);
  } else h.push(`<div class="lu-box k">② 現貨三大法人：${sp.error || "還沒公布"}</div>`);
  // ===== 期貨選擇權大戶 =====
  const o = B.opt;
  if (o) {
    const cg = (r, k) => `<td>${chL(r[k])}<span class="k">${r[k + "_1"] ? (r[k + "_1"] > 0 ? " +" : " ") + Math.round(r[k + "_1"]).toLocaleString() : ""}</span></td>`;
    const td = o.today || {};
    const lv = (arr, f) => (arr || []).map(x => `${fmt(x.k, 0)}（${f}${x.n.toLocaleString()}）`).join("、") || "–";
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">③ 期貨／選擇權大戶（口，小字＝今天變化）</div>
      <div class="ch-scroll"><table class="lu-t"><tr><th>身份</th><th>買 Call</th><th>賣 Call</th><th>買 Put</th><th>賣 Put</th><th>台指期淨部位</th><th>選擇權偏多金額</th></tr>
      ${o.table.map(r => `<tr><td>${r.name}</td>${cg(r, "bc")}${cg(r, "sc")}${cg(r, "bp")}${cg(r, "sp")}${cg(r, "fut")}<td>${r.bull_amt != null ? chN(r.bull_amt, 2) + " 億" : "–"}</td></tr>`).join("")}</table></div>
      <div class="k" style="margin-top:6px">Put/Call 未平倉比 ${o.pc.length ? o.pc[o.pc.length - 1].oi + "%" : "–"}｜成交量比 ${o.pc.length ? o.pc[o.pc.length - 1].vol + "%" : "–"}${o.iv ? `｜次月價平 IV ${o.iv.prev}% → ${o.iv.now}%` : ""}</div></div>
      <div class="lu-box side"><div class="lu-title">今天各履約價的賣方動作（推估）</div>
      ${chTable([["", r => `<td>${r[0]}</td>`], ["價位（口數）", r => `<td style="text-align:left;white-space:normal">${r[1]}</td>`]], [
        ["<span class='up'>Call 賣方新增</span>", lv(td.call_add, "+")], ["Call 賣方回補", lv(td.call_cover, "")],
        ["<span class='down'>Put 賣方新增</span>", lv(td.put_add, "+")], ["Put 賣方回補", lv(td.put_cover, "")]])}
      ${o.settle ? `<div class="lu-title" style="margin-top:10px">最近的月選結算</div><div class="k" style="line-height:1.7">${o.settle.contract}：${o.settle.date}（還有 ${o.settle.days} 個交易日）<br>
        最大痛點 <b>${fmt(o.settle.max_pain, 0)}</b>｜Call 牆 ${fmt(o.settle.call_wall, 0)}｜Put 牆 ${fmt(o.settle.put_wall, 0)}</div>` : ""}
      <div class="lu-title" style="margin-top:10px">支撐壓力（下個月份起）</div><div class="k" style="line-height:1.7">${(o.levels || []).join("<br>")}</div></div></div>`);
  }
  // ===== 族群 =====
  const st = B.stocks;
  if (st) {
    const indT = who => chTable([["族群", r => `<td>${r.ind}</td>`], ["今天(億)", r => `<td>${chN(r.today, 2)}</td>`], ["近5日(億)", r => `<td>${chN(r.a5, 2)}</td>`],
      ["近20日(億)", r => `<td>${chN(r.a20, 2)}</td>`], ["今天買超家數", r => `<td>${r.n_buy}/${r.n}</td>`]], st[who].ind);
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">④ 外資：族群資金（依近 5 日排序）</div><div class="ch-scroll" style="max-height:380px">${indT("fi")}</div></div>
      <div class="lu-box grow"><div class="lu-title">④ 投信：族群資金</div><div class="ch-scroll" style="max-height:380px">${indT("it")}</div></div></div>`);
    const box = (title, rows, note) => `<div class="lu-box grow"><div class="lu-title">${title}</div><div class="ch-scroll" style="max-height:420px">${stk(rows, ncols())}</div>${note ? `<div class="k">${note}</div>` : ""}</div>`;
    h.push(`<div class="lu-row">${box("⑤ 外資默默買進", st.fi.quiet, "連買 ≥4 天、20 日累計買超、股價 20 日漲幅在 −6%~+8%（還沒大漲）")}${box("⑤ 投信默默買進", st.it.quiet)}</div>`);
    h.push(`<div class="lu-row">${box("⑥ 外資持續賣出（連賣 ≥4 天）", st.fi.sell)}${box("⑥ 投信持續賣出（連賣 ≥4 天）", st.it.sell)}</div>`);
    h.push(`<div class="lu-row">${box("⑦ 外資轉向：連賣後今天轉買", st.fi.turn_buy, "前 5 天至少 4 天賣超，今天第一天買超")}${box("⑦ 外資轉向：連買後今天轉賣", st.fi.turn_sell)}</div>`);
    h.push(`<div class="lu-row">${box("⑧ 投信新進場（前 10 天都沒買）", st.it.new)}${box("⑧ 外資＋投信都在默默買", st.both_quiet)}</div>`);
  }
  // ===== 融資券／借券、隔日沖 =====
  const m = B.margin;
  if (m && m.tot && m.tot.has) {
    const mc = (k, bal) => [["代號", chCode], ["名稱", chName], ["增減(張)", r => `<td>${chN(r[k])}</td>`], ["餘額", r => `<td>${chL(r[bal])}</td>`], ["漲跌", r => `<td>${chP(r.chg)}</td>`]];
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">⑨ 融資增加最多（散戶追進）</div>${chTable(mc("m_chg", "m_bal"), m.m_up.filter(r => !chIsEtf(r.code)).slice(0, 10))}</div>
      <div class="lu-box grow"><div class="lu-title">⑨ 融券增加最多</div>${chTable(mc("s_chg", "s_bal"), m.s_up.filter(r => !chIsEtf(r.code)).slice(0, 10))}</div>
      <div class="lu-box grow"><div class="lu-title">⑨ 借券賣出增加最多</div>${chTable(mc("l_chg", "bal"), m.l_up.filter(r => !chIsEtf(r.code)).slice(0, 10))}</div></div>`);
  } else h.push(`<div class="lu-box k">⑨ 融資券／借券：還沒公布（每天晚上 10 點自動抓）</div>`);
  const dtv = B.daytrade;
  if (dtv && dtv.heavy.length) {
    h.push(`<div class="lu-box"><div class="lu-title">⑩ 今天被隔日沖大買的漲停股（明天容易開高被倒）</div>
      ${chTable([["代號", chCode], ["名稱", chName], ["收盤", r => `<td>${fmt(r.close)}</td>`], ["隔日沖佔量", r => `<td class="up"><b>${fmt(r.dt_pct, 1)}%</b></td>`],
        ["隔日沖分點", r => `<td style="text-align:left;white-space:normal">${r.dt_names}</td>`]], dtv.heavy)}</div>`);
  }
  $("chBody").innerHTML = h.join("");
  document.querySelectorAll("#chBody .ch-c").forEach(e => e.onclick = () => { showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
  briefChart();
}

async function briefChart(){
  const el = $("briefChart"); if (!el) return;
  let c; try { c = await api("/api/stock/TX?tf=5&n=-1"); } catch(e) { return; }
  if (!$("briefChart") || !c.bars || !c.bars.length) return;
  if (BRIEF_CHART) { try { BRIEF_CHART.remove(); } catch(e) {} }
  const ch = BRIEF_CHART = LW.createChart(el, {autoSize: true, layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc", panes: {separatorColor: "#2a2e39"}},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    timeScale: {borderColor: "#2a2e39", rightOffset: 3, timeVisible: true, secondsVisible: false}, crosshair: {mode: 0}, localization: TW_LOCALE});
  const k = ch.addSeries(LW.CandlestickSeries, {upColor: "#f23645", downColor: "#089981", borderUpColor: "#f23645", borderDownColor: "#089981",
    wickUpColor: "#f23645", wickDownColor: "#089981", priceLineVisible: false});
  // 只畫到這一天收盤
  const end = Date.UTC(+BRIEF.date.slice(0, 4), +BRIEF.date.slice(5, 7) - 1, +BRIEF.date.slice(8, 10), 13, 45) / 1000;
  const bars = c.bars.filter(b => b[0] <= end);
  k.setData(bars.map(([t, o, h, l, cl]) => ({time: t, open: o, high: h, low: l, close: cl})));
  const o = BRIEF.opt, tx = BRIEF.tx;
  const pl = (p, col, t) => p && k.createPriceLine({price: p, color: col, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: t});
  if (o && o.settle) { pl(o.settle.call_wall, "#f23645", "Call牆"); pl(o.settle.put_wall, "#26a69a", "Put牆"); pl(o.settle.max_pain, "#9e9e9e", "最大痛點"); }
  if (tx) pl(tx.ma[60], "#ab47bc", "60日線");
  const v = ch.addSeries(LW.HistogramSeries, {priceLineVisible: false, priceFormat: {type: "volume"}}, 1);
  v.setData(bars.map(([t, o, h, l, cl, vv]) => ({time: t, value: vv, color: cl >= o ? "rgba(242,54,69,.5)" : "rgba(8,153,129,.5)"})));
  try { const pn = ch.panes(); [80, 20].forEach((f, i) => pn[i].setStretchFactor(f)); } catch(e) {}
  const n = bars.length, fit = () => n > 230 ? ch.timeScale().setVisibleLogicalRange({from: n - 230, to: n + 2}) : ch.timeScale().fitContent();
  fit(); [80, 400].forEach(ms => setTimeout(fit, ms));
}


// ---------- 🌊 波浪理論 ----------
let WAVE = null, waveAlt = false, WAVE_CH = [];
async function waveShow(){
  if (chTab !== "wave") return;       // 重試／計時器觸發時已經切到別的分頁，不要蓋掉別頁的內容
  if (!WAVE) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">數浪中…</div>`;
    try { WAVE = await api("/api/waves"); } catch(e) { setTimeout(waveShow, 3000); return; }
  }
  if (chTab !== "wave") return;       // 載入期間已經切到別的分頁
  const W = WAVE;
  if (W.error || !W.daily) { $("chBody").innerHTML = `<div class="k" style="padding:20px">${W.error || "資料不足"}</div>`; return; }
  $("chDate").innerHTML = `<option>${W.daily.last.date}</option>`;
  const T = W.text, ul = a => `<ul>${(a || []).map(x => `<li>${x}</li>`).join("")}</ul>`;
  $("chBody").innerHTML = wlHtml() + `
    <div class="lu-box brief-sum"><div class="lu-title">🌊 波浪理論：台指期現在在哪個位置？（${W.daily.last.date}）</div>
      <div class="lu-guide">${ul(T.summary)}</div></div>
    <div class="lu-box"><div class="lu-title">日K（全盤，近月連續）
      <span class="lu-studies" style="margin-left:10px"><button data-wa="0" class="${!waveAlt ? "on" : ""}">主要劇本</button><button data-wa="1" class="${waveAlt ? "on" : ""}">備選劇本（擴張平台）</button></span>
      <span class="k" style="margin-left:auto">${waveAlt ? "紅虛線＝C 浪目標" : "灰虛線＝整段漲幅的費波南希回檔；綠＝第 4 浪低點；紅實線＝失效價"}</span></div>
      <div id="waveD" style="height:460px"></div></div>
    <div class="lu-row">
      <div class="lu-box grow"><div class="lu-title">📈 日K 數浪（主要劇本）</div>${ul(T.daily)}
        <div class="lu-title" style="margin-top:8px">🔀 備選劇本</div>${ul(T.alt)}</div>
      <div class="lu-box grow"><div class="lu-title">⏱ 60 分K：高點之後的下跌</div>${ul(T.h60)}</div></div>
    <div class="lu-box"><div class="lu-title">60 分K（全盤，近 30 個交易日）<span class="k" style="margin-left:8px">綠虛線＝B 浪反彈目標（A 浪的 38.2/50/61.8%）、紫線＝A 浪低點</span></div>
      <div id="waveH" style="height:400px"></div></div>
    <div class="lu-row"><div class="lu-box grow"><div class="lu-title">📍 關鍵價位</div>${ul(T.levels)}</div>
      <div class="lu-box grow"><div class="lu-title">⚠ 注意</div>${ul(T.notes)}</div></div>`;
  document.querySelectorAll("#chBody [data-wa]").forEach(b => b.onclick = () => { waveAlt = b.dataset.wa === "1"; waveShow(); });
  waveCharts();
  waveLive(false);
}

function waveChart(el, bars, intra){
  const ch = LW.createChart(el, {autoSize: true, layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc"},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    timeScale: {borderColor: "#2a2e39", rightOffset: 4, timeVisible: intra, secondsVisible: false}, crosshair: {mode: 0}, localization: TW_LOCALE});
  const k = ch.addSeries(LW.CandlestickSeries, {upColor: "#f23645", downColor: "#089981", borderUpColor: "#f23645", borderDownColor: "#089981",
    wickUpColor: "#f23645", wickDownColor: "#089981", priceLineVisible: false});
  k.setData(bars.map(([t, o, h, l, c]) => ({time: t, open: o, high: h, low: l, close: c})));
  WAVE_CH.push(ch);
  return {ch, k};
}

function waveCharts(){
  WAVE_CH.forEach(c => { try { c.remove(); } catch(e) {} }); WAVE_CH = [];
  const W = WAVE, D = W.daily;
  const {ch: cd, k: kd} = waveChart($("waveD"), D.bars, false);
  const sc = waveAlt && D.alt ? D.alt : D.primary;
  const marks = sc.marks.map(m => ({time: m.time, position: m.pos, color: "#ffd600", shape: m.pos === "aboveBar" ? "arrowDown" : "arrowUp", text: m.text}));
  if (waveAlt && D.alt && D.alt.flat) {
    marks.push({time: D.alt.flat.a_date, position: "belowBar", color: "#4fc3f7", shape: "arrowUp", text: "A"});
    marks.push({time: D.top.date, position: "aboveBar", color: "#4fc3f7", shape: "arrowDown", text: "B"});
    marks.push({time: D.bars[D.bars.length - 1][0], position: "belowBar", color: "#f23645", shape: "arrowDown", text: "C 進行中"});
    D.alt.flat.c_targets.forEach(x => kd.createPriceLine({price: x.price, color: "#f23645", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `C=${x.r}A`}));
  } else {
    marks.push({time: D.bars[D.bars.length - 1][0], position: "belowBar", color: "#4fc3f7", shape: "arrowUp", text: "A→B"});
  }
  LW.createSeriesMarkers(kd, marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  cd.addSeries(LW.LineSeries, {color: "rgba(255,214,0,.7)", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
    .setData(sc.points.map(p => ({time: p.date, value: p.price})));
  if (!waveAlt) {
    D.fib_all.filter(x => x.r <= 0.5).forEach(x => kd.createPriceLine({price: x.price, color: "#90a4ae", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `回檔${(x.r * 100).toFixed(1)}%`}));
    kd.createPriceLine({price: D.primary.points[4].price, color: "#26a69a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "第4浪低點"});
    kd.createPriceLine({price: D.top.price, color: "#f23645", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "失效價"});
  }
  const n = D.bars.length, start = sc.points[0].date;
  const fitD = () => cd.timeScale().setVisibleLogicalRange({from: Math.max(0, D.bars.findIndex(b => b[0] >= start) - 10), to: n + 5});
  fitD(); [80, 400].forEach(ms => setTimeout(fitD, ms));
  const H = W.h60;
  if (H) {
    const {ch: chh, k: kh} = waveChart($("waveH"), H.bars, true);
    const im = H.impulse;
    if (im) {
      LW.createSeriesMarkers(kh, im.marks.map(m => ({time: m.time, position: m.pos, color: "#ffd600", shape: m.pos === "aboveBar" ? "arrowDown" : "arrowUp", text: m.text}))
        .concat([{time: im.end.time, position: "belowBar", color: "#4fc3f7", shape: "circle", text: "A浪完成"}]).sort((a, b) => a.time - b.time));
      chh.addSeries(LW.LineSeries, {color: "rgba(255,214,0,.7)", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
        .setData(im.points.map(p => ({time: p.time, value: p.price})));
      im.b_targets.forEach(x => kh.createPriceLine({price: x.price, color: "#26a69a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `B ${(x.r * 100).toFixed(1)}%`}));
      kh.createPriceLine({price: im.end.price, color: "#ab47bc", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "A浪低點"});
    }
    const m = H.bars.length, i0 = Math.max(0, H.bars.findIndex(b => b[0] >= H.top.time) - 60);
    const fitH = () => chh.timeScale().setVisibleLogicalRange({from: i0, to: m + 3});
    fitH(); [80, 400].forEach(ms => setTimeout(fitH, ms));
  }
}

// ---------- 🌊 波浪：上方「最新波浪／細浪」＋主劇本／細浪紀錄（wavelive.py）----------
let WL = null, WL_SCR = null, WL_SUBS = null, WL_CH = null, wlScrSel = null, wlSubSel = null;
const wlUl = a => `<ul>${(a || []).map(x => `<li>${x}</li>`).join("")}</ul>`;
const wlEsc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

function wlHtml(){
  return `<div class="lu-box wl-box" id="wlBox"><div class="k" style="padding:6px">分析最新走勢中…</div></div>
    <details class="st-fold wl-fold" id="wlScrFold"><summary>📜 主劇本（依日期）</summary><div id="wlScr" class="wl-in"></div></details>
    <details class="st-fold wl-fold" id="wlSubFold"><summary>🔍 細浪紀錄（依日期）</summary><div id="wlSub" class="wl-in"></div></details>`;
}

async function waveLive(force){
  if (chTab !== "wave" || !$("wlBox")) return;
  if (force) { WL = null; $("wlBox").innerHTML = `<div class="k" style="padding:6px">抓最新走勢（含夜盤）重新分析中…</div>`; }
  try {
    WL = await api("/api/wave_live" + (force ? "?force=1" : ""));   // 不帶 force：後端 1 分鐘內算過就直接給
    [WL_SCR, WL_SUBS] = await Promise.all([api("/api/wave_scripts"), api("/api/wave_subs")]);
  } catch(e) { if ($("wlBox")) $("wlBox").innerHTML = `<div class="k">最新波浪載入失敗：${e}</div>`; return; }
  if (chTab !== "wave" || !$("wlBox")) return;
  wlRender(); wlScrRender(); wlSubRender();
}
window.waveLiveRefresh = () => { if (window.CUR_PAGE === "chips" && chTab === "wave") waveLive(true); };
// 停在波浪頁時每 60 秒自動重算一次（夜盤、盤中都會跟著更新）；展開中的主劇本／細浪下拉區不重畫
setInterval(() => { if (window.CUR_PAGE === "chips" && chTab === "wave" && $("wlBox") && !document.hidden) waveLiveAuto(); }, 60000);
async function waveLiveAuto(){
  try { const x = await api("/api/wave_live?force=1"); if (!x || !$("wlBox")) return; WL = x; wlRender(); } catch(e) {}
}

function wlCells(x){
  return `<div class="lu-row wl-row">
      <div class="lu-box grow"><div class="lu-title">🌊 細浪計數</div>${wlUl(x.count)}</div>
      <div class="lu-box grow"><div class="lu-title">👀 看法</div>${wlUl(x.view)}</div>
      <div class="lu-box grow wl-long"><div class="lu-title">📈 做多建議</div>${wlUl(x.long)}</div>
      <div class="lu-box grow wl-short"><div class="lu-title">📉 做空建議</div>${wlUl(x.short)}</div></div>
    <div class="k wl-lv">關鍵價：${(x.levels || []).join("　")}</div>`;
}

function wlRender(){
  const el = $("wlBox"), x = WL;
  if (!el) return;
  if (!x || x.error) { el.innerHTML = `<div class="lu-title">⚡ 最新波浪／細浪</div><div class="k">${x ? x.error : ""}</div>`; return; }
  el.innerHTML = `<div class="lu-title">⚡ 最新波浪／細浪　<span class="${x.broke_inv ? "up" : ""}">${x.now}</span>
      <span class="k" style="margin-left:8px">${x.date} ${x.session} ${x.time} 分析｜最新 ${fmt(x.price, 0)}（${x.asof}）｜資料庫到 ${x.db_to}${x.src ? "，之後用" + x.src : "（沒有即時走勢：群益沒開或期交所連不上）"}</span>
      <button class="btn ghost" id="wlRe" style="margin-left:auto">🔄 抓最新走勢重新分析</button></div>
    ${wlCells(x)}
    <div class="k" style="margin:6px 0 2px">5 分K（${x.pivots[0].label} 之後；黃＝細浪、紫＝轉折、灰虛線＝${x.pivots[0].label}→${x.pivots[1].label} 的回檔、紅＝失效價）</div>
    <div id="waveL" style="height:340px"></div>`;
  $("wlRe").onclick = () => waveLive(true);
  wlChart();
}

function wlChart(){
  if (WL_CH) { try { WL_CH.remove(); } catch(e) {} WL_CH = null; }
  const x = WL, el = $("waveL"); if (!el || !x.bars || !x.bars.length) return;
  const {ch, k} = waveChart(el, x.bars, true);
  WL_CH = ch; WAVE_CH = WAVE_CH.filter(c => c !== ch);
  const mk = [];
  const pmax = Math.max(...x.pivots.map(q => q.price));
  x.pivots.forEach(p => mk.push({time: p.ts, position: p.price >= pmax ? "aboveBar" : "belowBar", color: "#ce93d8", shape: "circle", text: p.label}));
  x.swings.slice(1).forEach((s, i, a) => {
    const prev = i ? a[i - 1].price : x.swings[0].price, top = s.price > prev;
    mk.push({time: s.ts, position: top ? "aboveBar" : "belowBar", color: "#ffd600", shape: top ? "arrowDown" : "arrowUp", text: s.label + (s.open ? "?" : "")});
  });
  const seen = new Set();
  LW.createSeriesMarkers(k, mk.sort((a, b) => a.time - b.time).filter(m => { const key = m.time + m.text; if (seen.has(key)) return false; seen.add(key); return true; }));
  ch.addSeries(LW.LineSeries, {color: "rgba(255,214,0,.7)", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
    .setData(x.swings.map(s => ({time: s.ts, value: s.price})).filter((p, i, a) => !i || p.time > a[i - 1].time));
  x.fibs.filter(f => f.r >= 0.236 && f.r <= 0.618).forEach(f => k.createPriceLine({price: f.price, color: "#90a4ae", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `${(f.r * 100).toFixed(1)}%`}));
  if (x.invalid) k.createPriceLine({price: x.invalid, color: "#f23645", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "失效價"});
  const n = x.bars.length, fit = () => ch.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 260), to: n + 4});
  fit(); [80, 400].forEach(ms => setTimeout(fit, ms));
}

function wlScrBody(s){
  const pv = (s.pivots || []).map(p => `${p.label} <b>${fmt(p.price, 0)}</b>（${p.t}）`).join(" → ");
  const alt = s.alt || {};
  return `<div class="wl-meta">${s.date} ${s.time || ""}｜${s.author || ""}${s.change ? `<div class="wl-chg">🔁 改版原因：${s.change}</div>` : ""}</div>
    <div class="lu-title">${s.title || ""}</div>${wlUl(s.big)}
    <div class="wl-kv"><b>轉折點：</b>${pv}</div>
    <div class="wl-kv"><b>現在：</b>${s.now || ""}（${s.now_dir === "up" ? "往上" : "往下"}）　<b>下一步：</b>${s.next || ""}</div>
    ${s.invalid ? `<div class="wl-kv"><b>失效價：</b><span class="up">${fmt(s.invalid.price, 0)}</span>（${s.invalid.dir === "below" ? "跌破" : "突破"}）${s.invalid.why || ""}</div>` : ""}
    ${(s.targets || []).length ? `<div class="wl-kv"><b>目標：</b>${s.targets.map(t => `${fmt(t.price, 0)}（${t.label || ""}）`).join("、")}</div>` : ""}
    ${(s.zones || []).length ? `<div class="wl-kv"><b>區間：</b>${s.zones.map(z => `${fmt(z.lo, 0)}~${fmt(z.hi, 0)}（${z.label || ""}）`).join("、")}</div>` : ""}
    ${alt.title ? `<div class="lu-title" style="margin-top:6px">🔀 備選劇本：${alt.title}</div>${wlUl(alt.lines)}` : ""}`;
}

function wlScrRender(){
  const el = $("wlScr"); if (!el) return;
  const L = WL_SCR || [];
  if (!L.length) { el.innerHTML = `<div class="k">還沒有主劇本</div>`; return; }
  const cur = L[L.length - 1];
  $("wlScrFold").querySelector("summary").innerHTML = `📜 主劇本（目前：${cur.date} 版｜${cur.title || ""}｜共 ${L.length} 版）`;
  if (wlScrSel == null || wlScrSel >= L.length) wlScrSel = L.length - 1;
  el.innerHTML = `<div class="wl-pick">版本：<select id="wlScrPick">${L.map((s, i) => `<option value="${i}" ${i === wlScrSel ? "selected" : ""}>${s.date} ${s.time || ""}｜${wlEsc(s.title)}${i === L.length - 1 ? "（目前）" : ""}</option>`).reverse().join("")}</select>
      <button class="btn ghost" id="wlScrEdit">✏ 以這版為底、新增今天的版本</button></div>
    <div id="wlScrView">${wlScrBody(L[wlScrSel])}</div><div id="wlScrForm"></div>`;
  $("wlScrPick").onchange = e => { wlScrSel = +e.target.value; $("wlScrView").innerHTML = wlScrBody(L[wlScrSel]); };
  $("wlScrEdit").onclick = () => wlScrForm(L[wlScrSel]);
}

function wlScrForm(s){
  const pv = (s.pivots || []).map(p => `${p.label},${p.price},${p.t}`).join("\n");
  $("wlScrForm").innerHTML = `<div class="wl-form">
    <label>標題 <input id="wfTitle" value="${wlEsc(s.title)}"></label>
    <label>改版原因 <input id="wfChg" placeholder="例如：今天日盤 V 轉，C-4 提早展開"></label>
    <label>大架構說明（一行一點）<textarea id="wfBig" rows="5">${wlEsc((s.big || []).join("\n"))}</textarea></label>
    <label>已確認轉折點（一行一個：名稱,價位,日期 時間）<textarea id="wfPv" rows="5">${wlEsc(pv)}</textarea></label>
    <div class="wl-f2"><label>現在第幾浪 <input id="wfNow" value="${wlEsc(s.now)}"></label>
      <label>方向 <select id="wfDir"><option value="up" ${s.now_dir === "up" ? "selected" : ""}>往上</option><option value="down" ${s.now_dir !== "up" ? "selected" : ""}>往下</option></select></label>
      <label>大方向 <select id="wfTrend"><option value="down" ${s.trend !== "up" ? "selected" : ""}>空（下跌浪）</option><option value="up" ${s.trend === "up" ? "selected" : ""}>多（上漲浪）</option></select></label>
      <label>下一浪 <input id="wfNext" value="${wlEsc(s.next)}"></label>
      <label>失效價 <input id="wfInv" type="number" value="${s.invalid ? s.invalid.price : ""}"></label>
      <label>失效方向 <select id="wfInvDir"><option value="above" ${!s.invalid || s.invalid.dir !== "below" ? "selected" : ""}>突破</option><option value="below" ${s.invalid && s.invalid.dir === "below" ? "selected" : ""}>跌破</option></select></label></div>
    <label>失效原因 <input id="wfInvWhy" value="${wlEsc(s.invalid && s.invalid.why)}"></label>
    <div><button class="btn" id="wfSave">💾 存成今天的主劇本</button> <button class="btn ghost" id="wfCancel">取消</button> <span class="k" id="wfMsg"></span></div></div>`;
  $("wfCancel").onclick = () => { $("wlScrForm").innerHTML = ""; };
  $("wfSave").onclick = async () => {
    const pivots = $("wfPv").value.split("\n").map(l => l.split(",").map(x => x.trim())).filter(a => a.length >= 3 && +a[1])
      .map(([label, price, t]) => ({label, price: +price, t}));
    if (pivots.length < 2) { $("wfMsg").textContent = "轉折點至少要兩個"; return; }
    const inv = +$("wfInv").value;
    const body = Object.assign({}, s, {title: $("wfTitle").value, change: $("wfChg").value, big: $("wfBig").value.split("\n").filter(x => x.trim()),
      pivots, now: $("wfNow").value, now_dir: $("wfDir").value, trend: $("wfTrend").value, next: $("wfNext").value,
      invalid: inv ? {price: inv, dir: $("wfInvDir").value, why: $("wfInvWhy").value} : null, author: "willy"});
    delete body.date; delete body.time;
    const r = await post("/api/wave_scripts", body);
    if (r.error) { $("wfMsg").textContent = r.error; return; }
    wlScrSel = null; waveLive(true);
  };
}

function wlSubRender(){
  const el = $("wlSub"); if (!el) return;
  const L = WL_SUBS || [];
  if (!L.length) { el.innerHTML = `<div class="k">還沒有紀錄</div>`; return; }
  $("wlSubFold").querySelector("summary").innerHTML = `🔍 細浪紀錄（最新：${L[L.length - 1].date} ${L[L.length - 1].session}｜共 ${L.length} 筆）`;
  if (wlSubSel == null || wlSubSel >= L.length) wlSubSel = L.length - 1;
  const lab = s => `${s.date} ${s.session} ${s.time}${s.author && s.author !== "auto" ? "｜" + s.author : ""}｜${s.now || ""} ${s.price ? fmt(s.price, 0) : ""}`;
  el.innerHTML = `<div class="wl-pick">紀錄：<select id="wlSubPick">${L.map((s, i) => `<option value="${i}" ${i === wlSubSel ? "selected" : ""}>${wlEsc(lab(s))}</option>`).reverse().join("")}</select></div>
    <div id="wlSubView"></div>`;
  const show = () => { const s = L[wlSubSel];
    $("wlSubView").innerHTML = `<div class="wl-meta">${s.date} ${s.session} ${s.time} 分析｜${s.author === "auto" || !s.author ? "程式自動" : s.author}｜資料到 ${s.asof || ""}｜依主劇本 ${s.script_date || ""} 版</div>
      ${s.note ? `<div class="wl-kv">${s.note}</div>` : ""}${wlCells(s)}`; };
  $("wlSubPick").onchange = e => { wlSubSel = +e.target.value; show(); };
  show();
}


// ---------- 📅 結算日 ----------
// 子頁：一次只顯示一個主題，左邊是目錄；記住上次看的子頁
let SETL = null, SETT = null, SETTR = null, setlLong = false;
const SETL_SUBS = [["home", "📋 總覽"], ["day", "📆 當天漲跌與振幅"], ["intra", "⏱ 盤中慣性與高低點"], ["tail13", "🎯 尾盤 13:00~13:30"],
  ["weekly", "📊 週選尾盤波動時段"], ["night", "🌙 夜盤效應與隔日"], ["lotto", "🎰 樂透單策略"], ["trades", "📝 實單紀錄與檢討"]];
let setlSub = new URLSearchParams(location.search).get("st") || lsGet("setlSub", "home");   // ?st=lotto 直接開子頁
if (!SETL_SUBS.some(s => s[0] === setlSub)) setlSub = "home";
const stUl = a => `<ul>${a.map(x => `<li>${x}</li>`).join("")}</ul>`;
const stKey = (lines, title = "重點結論") => `<div class="lu-box brief-sum"><div class="lu-title">💡 ${title}</div><div class="lu-guide">${stUl(lines)}</div></div>`;
const stPt = v => v == null ? "–" : Math.round(v).toLocaleString();
const stX = v => v == null ? "–" : `<span class="${v > 1 ? "up" : v < 1 ? "down" : ""}">${fmt(v, 2)} 倍</span>`;
const stFold = (title, html, open = false) => `<details class="st-fold" ${open ? "open" : ""}><summary>${title}</summary>${html}</details>`;

async function setlShow(){
  if (chTab !== "setl") return;       // 重試／計時器觸發時已經切到別的分頁，不要蓋掉別頁的內容
  if (!SETL || !SETT) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">統計結算日中…</div>`;
    try {
      [SETL, SETT, SETTR] = await Promise.all([SETL || api("/api/settlement"), SETT || api("/api/settle_tail"), SETTR || api("/api/settle_trades")]);
    } catch(e) { setTimeout(setlShow, 3000); return; }
  }
  if (chTab !== "setl") return;       // 載入期間已經切到別的分頁
  const O = SETL;
  if (O.error) { $("chBody").innerHTML = `<div class="k" style="padding:20px">${O.error}</div>`; return; }
  $("chDate").innerHTML = `<option>${O.next.today}</option>`;
  $("chBody").innerHTML = `<div class="st-wrap"><nav class="st-nav">${SETL_SUBS.map(([k, n]) => `<button data-st="${k}" class="${k === setlSub ? "on" : ""}">${n}</button>`).join("")}</nav>
    <div class="st-main" id="stMain"></div></div>`;
  document.querySelectorAll("#chBody [data-st]").forEach(b => b.onclick = () => setlGo(b.dataset.st));
  setlPage();
}

function setlGo(k){
  setlSub = k; lsSet("setlSub", k);
  document.querySelectorAll("#chBody [data-st]").forEach(b => b.classList.toggle("on", b.dataset.st === k));
  setlPage();
  const m = $("stMain"); if (m) m.scrollTop = 0;
}

function setlPage(){
  const el = $("stMain"); if (!el) return;
  const f = {home: setlHome, day: setlDay, intra: setlIntra, tail13: setlTail13, weekly: setlWeekly, night: setlNightPage, lotto: setlLotto, trades: setlTrades}[setlSub] || setlHome;
  const tailPages = ["weekly", "lotto"];
  if (tailPages.includes(setlSub) && (!SETT || SETT.error)) { el.innerHTML = `<div class="k" style="padding:20px">${SETT ? SETT.error : "尾盤統計載入失敗"}</div>`; return; }
  el.innerHTML = f();
  el.querySelectorAll("[data-go]").forEach(b => b.onclick = () => setlGo(b.dataset.go));
  el.querySelectorAll("[data-sl]").forEach(b => b.onclick = () => { setlLong = b.dataset.sl === "1"; setlPage(); });
  if (setlSub === "night") setlNight5Chart(SETL);
  if (setlSub === "trades") setlTradesBind();
}

// ---- 各子頁的一句話（總覽用），數字都從 API 來 ----
function setlOneLiners(){
  const O = SETL, S = SETT && !SETT.error ? SETT : null, D = O.daily_recent, h = {}; O.intra.hours.forEach(x => h[x.h.slice(0, 5)] = x);
  const n5 = O.night5 ? O.night5.days : [];
  const R = S && S.exit.all.length ? Object.fromEntries(S.exit.all.map(r => [r.key, r])) : null;
  return {
    day: `月結算日當天近期平均 ${chP(D.chg.settle.avg)}、上漲 ${fmt(D.chg.settle.up, 0)}%（非結算週三 ${chP(D.chg.base.avg)}）；振幅 ${fmt(D.rng.settle)}% vs ${fmt(D.rng.wed)}%`,
    intra: `09 點最常是高點（${O.hilo.settle_hi[9] || 0}/${O.intra.n} 次）、13 點最常是低點（${O.hilo.settle_lo[13] || 0} 次）；12:00~13:00 只有 ${fmt(h["12:00"].s_up, 0)}% 上漲；V 型反轉 ${n5.filter(d => d.v).length}/${n5.length} 天`,
    tail13: `13:00~13:30 拉尾盤 ${fmt(O.tail.settle.pull, 0)}%、殺尾盤 ${fmt(O.tail.settle.kill, 0)}%、波動不大 ${fmt(O.tail.settle.flat, 0)}%；跟早盤反向 ${fmt(O.tail.settle.rev, 0)}%`,
    weekly: S ? `${S.n} 個週選／月選結算日：最大 15 分鐘急漲急跌從 12:30 後開始 ${S.mx["15"].after1230}/${S.n} 天，但 12:30 起到收盤單邊平均仍有 ${stPt(S.from_t[1].big)} 點` : "尾盤統計載入失敗",
    night: O.night5 ? `前一晚夜盤漲 ≧0.5% 的隔天：${O.night5.summary.n_up} 天裡 ${O.night5.summary.low_first} 天先低後高；結算隔天平均 ${chP(D.next.settle.avg)}` : "",
    lotto: R ? `抱到結算總損益 ${R.a.pnl > 0 ? "+" : ""}${fmt(R.a.pnl, 1)} 單位，5 倍全出 ${R.b5.pnl > 0 ? "+" : ""}${fmt(R.b5.pnl, 1)}、分批＋回落 40% ${R.d40.pnl > 0 ? "+" : ""}${fmt(R.d40.pnl, 1)}（${S.exit.n} 筆）` : "樣本不足",
    trades: `${(SETTR || []).length} 筆實單紀錄${(SETTR || []).length ? `，最近 ${SETTR[SETTR.length - 1].date}` : ""}`,
  };
}

function setlHome(){
  const L = setlOneLiners(), S = SETT && !SETT.error ? SETT : null;
  return `${stKey([`月結算統計：2025 年起 ${SETL.n.recent} 次（最近 ${SETL.n.last}），日K 另看 2015 年起 ${SETL.n.long} 次`,
      S ? `週選尾盤 1 分K：${S.n} 個結算日（${S.d_from} ~ ${S.d_to}）${S.n_5m ? `，其中 ${S.n_5m} 天只有 5 分K` : ""}${S.missing.length ? `；沒有分K：${S.missing.join("、")}` : ""}` : "",
      `下一次月結算：${SETL.next.date}（還有 ${SETL.next.days} 個交易日）`].filter(x => x), "這一區在看什麼")}
    <div class="lu-box"><div class="lu-title">📚 目錄（點一下進去）</div>
    ${chTable([["主題", r => `<td><button class="btn ghost st-link" data-go="${r[0]}">${r[1]}</button></td>`], ["一句話結論", r => `<td style="text-align:left">${L[r[0]] || ""}</td>`]], SETL_SUBS.slice(1))}</div>`;
}

// ① 結算日當天漲跌與振幅（月結算，加權指數日K）
function setlDay(){
  const O = SETL, per = setlLong ? "long" : "recent", D = setlLong ? O.daily_long : O.daily_recent, pc = v => chP(v);
  const cmpT = chTable([["項目", r => `<td>${r.name}</td>`],
    ["結算日平均", r => `<td>${pc(r.settle.avg)}</td>`], ["結算日上漲%", r => `<td>${fmt(r.settle.up, 0)}%</td>`],
    [`${D.chg.base_name}／基準平均`, r => `<td>${pc(r.base.avg)}</td>`], ["基準上漲%", r => `<td>${fmt(r.base.up, 0)}%</td>`]], [D.chg, D.o2c, D.gap, D.next]);
  const condT = (rows, first) => chTable([[first, r => `<td>${r.cond}</td>`], ["次數", r => `<td>${r.n}</td>`], ["結算日漲跌", r => `<td>${pc(r.chg)}</td>`],
    ["結算日上漲%", r => `<td>${fmt(r.up, 0)}%</td>`], ["開→收", r => `<td>${pc(r.o2c)}</td>`], ["收紅K%", r => `<td>${fmt(r.red, 0)}%</td>`],
    ["結算隔天", r => `<td>${pc(r.next)}</td>`]], rows || []);
  const nx = O.next, mt = (nx.d_2 > 0 ? "一漲" : "一跌") + (nx.d_1 > 0 ? "二漲" : "二跌"), nowPat = (O.montue[per] || []).find(r => r.cond === mt);
  return `${stKey([O.text[0], O.text[1], O.text[2], O.text[6]])}
    <div class="lu-box"><div class="lu-title">🔔 下一次結算：${nx.date}（還有 ${nx.days} 個交易日）
      <span class="lu-studies" style="margin-left:10px"><button data-sl="0" class="${!setlLong ? "on" : ""}">2025 年起（${O.n.recent} 次）</button><button data-sl="1" class="${setlLong ? "on" : ""}">2015 年起（${O.n.long} 次）</button></span></div>
      <div class="k" style="line-height:1.8">結算前一天（${nx.today}）加權 ${pc(nx.d_1)}（開→收 ${pc(nx.d_1_o2c)}）｜前兩天 ${pc(nx.d_2)}｜兩天合計 ${pc(nx.w2)}｜${nx.above20 ? "在月線上" : "在月線下"}<br>
      → 對應組合「${mt}」：${nowPat ? `過去 ${nowPat.n} 次，結算日平均 ${pc(nowPat.chg)}、上漲 ${fmt(nowPat.up, 0)}%、隔天平均 ${pc(nowPat.next)}` : "沒有樣本"}</div></div>
    <div class="lu-box"><div class="lu-title">日K：結算日 vs 一般的星期三</div>${cmpT}
      <div class="k" style="margin-top:6px">振幅：結算日 ${fmt(D.rng.settle)}%｜非結算週三 ${fmt(D.rng.wed)}%｜所有交易日 ${fmt(D.rng.all)}%；收盤在當天區間的位置：結算日 ${fmt(D.clpos.settle * 100, 0)}%、週三 ${fmt(D.clpos.wed * 100, 0)}%（越低＝收在越接近低點）</div>
      <div class="k">結算日＝每月第三個星期三（遇假日順延，用期交所各月合約最後交易日）；結算價＝當天 13:00~13:30 加權指數平均。</div></div>
    <div class="lu-row"><div class="lu-box grow"><div class="lu-title">結算前一天（通常是週二）漲跌 → 結算日</div>${condT(O.tue[per], "前一天")}
        <div style="height:6px"></div>${condT(O.tue_k[per], "前一天 K 棒")}
        <div class="k">前一天和結算日同方向：${fmt(O.tue_same[per].same, 0)}%（50% ＝ 沒有關聯）</div></div>
      <div class="lu-box grow"><div class="lu-title">結算前兩天（週一＋週二）組合 → 結算日</div>${condT(O.montue[per], "前兩天")}
        <div style="height:6px"></div>${condT(O.week2[per], "兩天合計")}</div></div>
    <div class="lu-box"><div class="lu-title">大架構：結算前一天在月線上／下（2015 年起）</div>${condT(O.trend.long, "位置")}</div>`;
}

// ② 盤中慣性與高低點時段（月結算，60 分K）
function setlIntra(){
  const O = SETL, pc = v => chP(v), H = O.intra.hours, mx = Math.max(...H.map(x => Math.max(Math.abs(x.s_avg), Math.abs(x.w_avg))), 0.01);
  const bar = v => `<div class="ch-bar"><i style="width:${Math.abs(v) / mx * 50}%;${v >= 0 ? "left:50%;background:var(--up)" : "right:50%;background:var(--down)"}"></i><span>${pc(v)}</span></div>`;
  const hiLo = k => [9, 10, 11, 12, 13].map(h => `${h}點 ${O.hilo[k][h] || 0}`).join("｜");
  const top = k => { const e = Object.entries(O.hilo[k]).sort((a, b) => b[1] - a[1])[0]; return e ? `${e[0]} 點（${e[1]}/${O.intra.n} 次）` : "–"; };
  const n5 = O.night5 ? O.night5.days : [];
  return `${stKey([`近 ${O.intra.n} 次月結算：最高點最常出現在 ${top("settle_hi")}，最低點最常出現在 ${top("settle_lo")}`, O.text[4],
      n5.length ? `V 型反轉（先壓 ≧0.3% 再拉上去收紅）：近 ${n5.length} 個交易日有 ${n5.filter(d => d.v).length} 天（5 分K，所有日子）` : ""].filter(x => x))}
    <div class="lu-box"><div class="lu-title">各小時漲跌（60 分K，2025 年起 ${O.intra.n} 次結算 vs ${O.intra.n_w} 個一般週三）</div>
      ${chTable([["時段", r => `<td>${r.h}</td>`], ["結算日平均", r => `<td>${bar(r.s_avg)}</td>`], ["結算日上漲%", r => `<td class="${r.s_up >= 65 ? "up" : r.s_up <= 35 ? "down" : ""}"><b>${fmt(r.s_up, 0)}%</b></td>`],
        ["一般週三平均", r => `<td>${bar(r.w_avg)}</td>`], ["一般週三上漲%", r => `<td>${fmt(r.w_up, 0)}%</td>`], ["平均波動", r => `<td>${fmt(r.s_abs)}%／${fmt(r.w_abs)}%</td>`]], H)}
      <div class="k" style="margin-top:6px">當天最高點出現在：${hiLo("settle_hi")}<br>當天最低點出現在：${hiLo("settle_lo")}<br>（一般週三最高：${hiLo("wed_hi")}；最低：${hiLo("wed_lo")}）</div></div>
    <div class="lu-box">${stFold(`每一次月結算日明細（2025 年起 ${O.detail.length} 次，加權指數 %）`, chTable([["結算日", r => `<td>${r.date}</td>`], ["前兩天", r => `<td>${pc(r.mon)}</td>`], ["前一天", r => `<td>${pc(r.tue)}</td>`], ["開盤跳空", r => `<td>${pc(r.gap)}</td>`],
        ["09~11點", r => `<td>${pc(r.am)}</td>`], ["11~13點", r => `<td>${pc(r.pm)}</td>`], ["13:00~13:30", r => `<td><b>${pc(r.last)}</b></td>`],
        ["當天漲跌", r => `<td>${pc(r.chg)}</td>`], ["隔天", r => `<td>${pc(r.next)}</td>`], ["高點／低點時段", r => `<td>${r.hi_h}點／${r.lo_h}點</td>`]], O.detail)
        + `<div class="k">樣本只有 ${O.detail.length} 次，慣性僅供參考；60 分K 是 Yahoo 的加權指數資料（09、10、11、12 點各一根，13 點那根是 13:00~13:30）</div>`)}</div>`;
}

// ③ 尾盤 13:00~13:30（結算價計算區間）
function setlTail13(){
  const O = SETL, t = O.tail;
  return `${stKey([O.text[3], `一般週三：拉尾盤 ${fmt(t.wed.pull, 0)}%、殺尾盤 ${fmt(t.wed.kill, 0)}%、平均波動 ${fmt(t.wed.abs)}%；所有交易日平均波動 ${fmt(t.all.abs)}%`,
      `結算日尾盤延續早盤方向 ${fmt(t.settle.cont, 0)}%、反轉 ${fmt(t.settle.rev, 0)}%`])}
    <div class="lu-box"><div class="lu-title">13:00~13:30：拉尾盤還是殺尾盤？（月結算，60 分K）</div>
      ${chTable([["", r => `<td>${r[0]}</td>`], ["次數", r => `<td>${r[1].n}</td>`], ["拉尾盤（≧+0.15%）", r => `<td class="up">${fmt(r[1].pull, 0)}%</td>`],
        ["殺尾盤（≦-0.15%）", r => `<td class="down">${fmt(r[1].kill, 0)}%</td>`], ["波動不大", r => `<td>${fmt(r[1].flat, 0)}%</td>`],
        ["跟早盤反向", r => `<td>${fmt(r[1].rev, 0)}%</td>`], ["平均波動", r => `<td>${fmt(r[1].abs)}%</td>`]], [["結算日", t.settle], ["一般週三", t.wed], ["所有交易日", t.all]])}
      <div class="k">「跟早盤反向」＝ 13:00 後的走勢方向和 09:00~13:00 相反（尾盤反轉）。週選的 1 分K 版本見「📊 週選尾盤波動時段」。</div></div>`;
}

// ④ 週選尾盤波動時段（1 分K）
function setlWeekly(){
  const S = SETT, n = S.n;
  const segT = chTable([["時段", r => `<td>${r.seg}</td>`], ["分鐘", r => `<td>${r.min}</td>`], ["平均｜漲跌｜", r => `<td>${stPt(r.abs_chg)}</td>`],
    ["平均振幅", r => `<td>${stPt(r.rng)}</td>`], ["換算每 30 分振幅", r => `<td><b>${stPt(r.rng30)}</b></td>`], ["最大振幅", r => `<td>${stPt(r.rng_max)}</td>`]], S.segs);
  const pp = S.prepost, ppT = chTable([["", r => `<td>${r[0]}</td>`], ["最大漲幅（低→後高）", r => `<td>${stPt(r[1].up.avg)}／${stPt(r[1].up.med)}／${stPt(r[1].up.max)}</td>`],
    ["最大跌幅（高→後低）", r => `<td>${stPt(r[1].dn.avg)}／${stPt(r[1].dn.med)}／${stPt(r[1].dn.max)}</td>`], ["振幅", r => `<td>${stPt(r[1].rng.avg)}／${stPt(r[1].rng.med)}／${stPt(r[1].rng.max)}</td>`],
    ["最大 15 分波動", r => `<td><b>${stPt(r[1].mx15.avg)}</b>／${stPt(r[1].mx15.med)}／${stPt(r[1].mx15.max)}</td>`]], [["12:30 前（225 分）", pp.pre], ["12:30 後（60 分）", pp.post]]);
  const dist = chTable([["時段", r => `<td>${r.b}</td>`], ["全天高點", r => `<td>${r.hi}</td>`], ["全天低點", r => `<td>${r.lo}</td>`],
    ["最大 15 分波動起點", r => `<td>${S.mx["15"].dist.find(x => x.b === r.b).n}</td>`], ["最大 30 分波動起點", r => `<td>${S.mx["30"].dist.find(x => x.b === r.b).n}</td>`]], S.hilo);
  const frT = chTable([["起點", r => `<td>${r.t}</td>`], ["到收盤淨漲跌｜平均｜", r => `<td>${stPt(r.net)}</td>`], ["最大上漲", r => `<td class="up">${stPt(r.up)}</td>`],
    ["最大下跌", r => `<td class="down">${stPt(r.dn)}</td>`], ["單邊最大", r => `<td><b>${stPt(r.big)}</b></td>`], ["順向（跟早盤同方向）", r => `<td>${stPt(r.same)}</td>`],
    ["逆向（跟早盤反向）", r => `<td><b>${stPt(r.rev)}</b></td>`], ["≥100 點", r => `<td>${r.ge100}/${r.n}</td>`], ["≥150 點", r => `<td>${r.ge150}/${r.n}</td>`], ["≥200 點", r => `<td>${r.ge200}/${r.n}</td>`]], S.from_t);
  const wkT = chTable([["", r => `<td>${r.name}</td>`], ["天數", r => `<td>${r.n}</td>`], ["全天振幅", r => `<td>${stPt(r.range)}</td>`], ["12:30 前振幅", r => `<td>${stPt(r.pre_rng)}</td>`],
    ["12:30 後振幅", r => `<td>${stPt(r.post_rng)}</td>`], ["13:00 後單邊最大", r => `<td>${stPt(r.big1300)}</td>`], ["尾盤創高或創低", r => `<td>${r.tail}/${r.n}</td>`]], S.week);
  const detT = chTable([["結算日", r => `<td>${r.date}（${r.wd}）</td>`], ["種類", r => `<td>${r.kind}</td>`], ["分K", r => `<td>${r.src}</td>`], ["開", r => `<td>${stPt(r.open)}</td>`],
    ["收", r => `<td>${stPt(r.close)}（${chN(r.chg)}）</td>`], ["振幅", r => `<td>${stPt(r.range)}</td>`], ["高點", r => `<td>${r.high_t}</td>`], ["低點", r => `<td>${r.low_t}</td>`],
    ["12:30 前／後振幅", r => `<td>${stPt(r.pre_rng)}／${stPt(r.post_rng)}</td>`], ["13:00 後↑／↓", r => `<td>${stPt((r.from["13:00"] || {}).up)}／${stPt((r.from["13:00"] || {}).dn)}</td>`],
    ["最大 15 分", r => `<td>${stPt(r.mx15)}${r.mx15_dir}＠${r.mx15_t}</td>`], ["尾盤", r => `<td>${r.tail_hi ? "<span class='up'>新高</span>" : ""}${r.tail_lo ? "<span class='down'>新低</span>" : ""}</td>`],
    ["估計結算價", r => `<td>${stPt(r.settle_est)}</td>`]], S.days);
  return `${stKey(S.text.tail)}
    <div class="lu-box"><div class="lu-title">各時段平均（點，台指期近月）</div>${segT}
      <div class="k">換算每 30 分振幅＝平均振幅 ÷ 分鐘 × 30，方便比較長短不同的時段（振幅不是線性，只當相對參考）</div></div>
    <div class="lu-row"><div class="lu-box grow"><div class="lu-title">12:30 前 vs 12:30 後（點：平均／中位／最大）</div>${ppT}
      <div class="k">12:30 後最大 15 分波動比 12:30 前大的只有 ${S.post_bigger}/${n} 天；12:30 後創當日新高 ${S.tail.hi} 次、新低 ${S.tail.lo} 次（合計 ${S.tail.any}/${n} 天）</div></div>
      <div class="lu-box grow"><div class="lu-title">週三 vs 週五</div>${wkT}</div></div>
    <div class="lu-box"><div class="lu-title">以 12:00／12:30／13:00 為起點到 13:30 收盤（點）</div>${frT}
      <div class="k">單邊最大＝起點後最大上漲、最大下跌取大的；順向／逆向＝跟「開盤到起點」同方向／反方向的最大延伸</div></div>
    <div class="lu-box"><div class="lu-title">全天高低點、最大 15／30 分鐘波動起點出現在哪個時段（次數）</div>${dist}
      <div class="k">最大 15 分波動平均 ${stPt(S.mx["15"].avg)} 點、30 分 ${stPt(S.mx["30"].avg)} 點</div></div>
    <div class="lu-box">${stFold(`每日明細（${n} 天）`, `<div class="ch-scroll">${detT}</div>`)}
      <div class="k">樣本 ${S.d_from} ~ ${S.d_to}；結算日＝各到期合約的實際最後交易日（遇休市順延）。${S.n_5m ? `${S.n_5m} 天只有 5 分K。` : ""}估計結算價＝13:00~13:30 期貨均價 − 基差（選擇權買賣權平價反推），約 ±30 點誤差。統計時間 ${S.made}</div></div>`;
}

// ⑤ 夜盤效應與隔日
function setlNightPage(){
  const O = SETL, s = O.night5 ? O.night5.summary : null;
  return `${stKey([O.text[5], s ? `前一晚夜盤漲 ≧0.5% 的隔天（${s.n_up} 天）：${s.low_first} 天先低後高、開→收平均 ${chP(s.o2c)}、收紅 ${fmt(s.red, 0)}%、11:00 後平均 ${chP(s.pm)}` : "",
      O.text[6]].filter(x => x))}
    ${setlNight(O)}
    ${setlNight5(O)}`;
}

// ⑥ 樂透單策略
function setlLotto(){
  const S = SETT, ex = S.exit;
  const ltT = chTable([["進場", r => `<td>${r.t}</td>`], ["買賣權", r => `<td>${r.cp === "C" ? "<span class='up'>Call</span>" : "<span class='down'>Put</span>"}</td>`], ["價外", r => `<td>${r.otm} 點</td>`],
    ["天數", r => `<td>${r.n}</td>`], ["中位進場價", r => `<td>${fmt(r.px, 1)}</td>`], ["結算還有價值", r => `<td class="${r.settle_ok ? "up" : ""}">${r.settle_ok}/${r.n}</td>`],
    ["盤中 ≥2 倍", r => `<td>${r.x2}</td>`], ["≥3 倍", r => `<td>${r.x3}</td>`], ["≥5 倍", r => `<td>${r.x5}</td>`]], S.lotto);
  const ruleT = rules => chTable([["出場規則", r => `<td style="text-align:left">${r.name}</td>`], ["平均倍數", r => `<td>${stX(r.avg)}</td>`], ["勝率", r => `<td>${fmt(r.win, 0)}%</td>`],
    ["最大單筆", r => `<td>${fmt(r.best, 1)} 倍</td>`], ["總損益（每筆 1 單位）", r => `<td><b>${chN(r.pnl, 1)}</b></td>`]], rules);
  const RN = Object.fromEntries(S.rules.map(r => [r.key, r.name]));
  const trT = chTable([["日期", r => `<td>${r.date}（${r.wd}）</td>`], ["進場", r => `<td>${r.entry}</td>`], ["早盤", r => `<td>${chN(r.morning)}</td>`],
    ["買", r => `<td>${r.strike} ${r.cp === "C" ? "Call" : "Put"}</td>`], ["價外", r => `<td>${stPt(r.otm)}</td>`], ["成本", r => `<td>${fmt(r.px, 1)}</td>`],
    ["盤中最高", r => `<td>${fmt(r.max, 1)}＠${r.max_t}（${fmt(r.max_x, 1)} 倍）</td>`], ["結算價值", r => `<td>${fmt(r.settle_val, 1)}</td>`],
    ...["a", "b5", "d40", "e1325"].map(k => [RN[k], r => `<td>${stX(r[k])}</td>`])], S.trades);
  const tips = ["週五到期的週選一樣用加權指數（現貨）結算；算價外距離要用現貨或選擇權反推的指數，不是台指期" + (S.basis_med ? `（這段期間台指期平均比現貨高約 ${stPt(S.basis_med)} 點）` : ""),
    "勒式（Call、Put 各買一邊，每邊預算約 20 點）：有一邊先翻倍就先賣一半，剩下的當免費單",
    "轉折玩法：每一邊最多試兩次；每一筆只用樂透預算的 1/4~1/3，不要一次全押"];
  return `${stKey(S.text.lotto)}
    ${stKey(S.text.advice, "操作建議（依回測結果）")}
    <div class="lu-box"><div class="lu-title">📌 過去討論的要點</div><div class="lu-guide">${stUl(tips)}</div></div>
    <div class="lu-box"><div class="lu-title">出場規則回測：跟早盤反向、權利金 5~20 點裡最價外的那檔（${ex.n || 0} 筆，${ex.n_days} 個結算日）</div>
      <div class="k" style="margin-bottom:6px">用 1 分K 收盤價成交，到價也看收盤價；價外距離用選擇權反推的加權指數。原條件「價外 300~500 點、5~20 點」只找到 ${ex.strict} 筆（${ex.slots} 個進場時點），價外 300~500 點的權利金中位數 ${fmt(ex.far_px, 1)} 點。</div>
      <div class="lu-title">三個進場時間合計</div>${ruleT(ex.all)}
      <div class="lu-row" style="margin-top:8px">${ex.by_entry.map(e => `<div class="lu-box grow"><div class="lu-title">${e.entry} 進場（${e.n} 筆，價外中位 ${stPt(e.otm)} 點、成本中位 ${fmt(e.px, 1)}）${e.n < 8 ? " <span class='k'>樣本少</span>" : ""}</div><div class="ch-scroll">${ruleT(e.rules)}</div></div>`).join("")}</div>
      ${stFold(`回測明細（${S.trades.length} 筆）`, `<div class="ch-scroll">${trT}</div>`)}</div>
    <div class="lu-box"><div class="lu-title">樂透單：進場時間 × 價外距離（當天到期合約，抱到結算 vs 盤中最高）</div>${ltT}
      <div class="k">履約價取最接近的 50 點；「盤中 ≥2 倍」＝進場後當天最高價達成本的 2 倍（常常只是 0.x 點的跳動）；結算價值用估計結算價算</div></div>`;
}

// ⑦ 實單紀錄與檢討
function setlTrades(){
  const T = SETTR || [];
  const tT = chTable([["日期", r => `<td>${r.date}${r.kind ? `（${r.kind}）` : ""}</td>`], ["進場", r => `<td>${r.entry_t || ""}</td>`],
    ["買", r => `<td>${r.strike ? `${r.strike} ${r.cp === "P" ? "Put" : "Call"}` : (r.cp || "")}</td>`], ["進場時指數", r => `<td>${stPt(r.idx_entry)}</td>`],
    ["成本", r => `<td>${r.cost ?? "–"}</td>`], ["賣出", r => `<td>${r.exit ?? "–"}${r.exit_t ? `＠${r.exit_t}` : ""}</td>`],
    ["倍數", r => `<td>${r.cost && r.exit != null ? stX(r.exit / r.cost) : "–"}</td>`], ["之後最高", r => `<td>${r.peak ?? "–"}${r.idx_peak ? `（指數約 ${stPt(r.idx_peak)}）` : ""}</td>`],
    ["結果", r => `<td>${r.result || ""}</td>`], ["檢討", r => `<td style="text-align:left;max-width:420px;white-space:normal">${r.review || ""}</td>`],
    ["", r => `<td><button class="btn ghost" data-del="${r.id}" style="padding:2px 8px">刪除</button></td>`]], T);
  const inp = (k, ph, w = 90) => `<input data-f="${k}" placeholder="${ph}" style="width:${w}px">`;
  return `${stKey([`共 ${T.length} 筆實單紀錄`, "把每次結算日的實單記下來，對照回測：進場時間、方向（跟早盤同向或反向）、出場是否太早／太晚"])}
    <div class="lu-box"><div class="lu-title">📝 實單紀錄</div><div class="ch-scroll">${tT}</div></div>
    <div class="lu-box st-form"><div class="lu-title">➕ 新增一筆</div>
      ${inp("date", "日期 2026-11-04", 110)}${inp("kind", "週三／週五／月選", 110)}${inp("entry_t", "進場時間", 80)}
      <select data-f="cp"><option value="C">Call</option><option value="P">Put</option></select>
      ${inp("strike", "履約價")}${inp("idx_entry", "進場時指數")}${inp("cost", "成本", 60)}${inp("exit", "賣出價", 60)}${inp("exit_t", "賣出時間", 80)}
      ${inp("peak", "之後最高", 70)}${inp("idx_peak", "最高時指數")}${inp("result", "結果", 140)}<br>
      <textarea data-f="review" placeholder="檢討" rows="2" style="width:100%;margin-top:6px"></textarea>
      <button class="btn" id="stAdd" style="margin-top:6px">新增</button> <span class="k" id="stMsg"></span></div>`;
}

function setlTradesBind(){
  const el = $("stMain");
  el.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("刪除這筆紀錄？")) return;
    await api("/api/settle_trades/" + b.dataset.del, {method: "DELETE"});
    SETTR = await api("/api/settle_trades"); setlPage();
  });
  const add = $("stAdd"); if (!add) return;
  add.onclick = async () => {
    const body = {}; el.querySelectorAll(".st-form [data-f]").forEach(x => { if (x.value.trim()) body[x.dataset.f] = x.value.trim(); });
    const r = await post("/api/settle_trades", body);
    if (r.error) { $("stMsg").textContent = r.error; return; }
    SETTR = await api("/api/settle_trades"); setlPage();
  };
}


function setlNight(O){
  const N = O.night; if (!N) return "";
  const pc = v => chP(v);
  const cols = [["條件", r => `<td>${r.cond}</td>`], ["次數", r => `<td>${r.n}</td>`], ["夜盤漲幅", r => `<td>${pc(r.night)}</td>`],
    ["開盤 vs 夜收", r => `<td>${pc(r.gap_n)}</td>`], ["開盤 vs 前日收", r => `<td>${pc(r.gap_p)}</td>`],
    ["開→收", r => `<td><b>${pc(r.o2c)}</b></td>`], ["收紅K", r => `<td class="${r.red >= 60 ? "up" : r.red <= 40 ? "down" : ""}"><b>${fmt(r.red, 0)}%</b></td>`],
    ["開後最低", r => `<td>${pc(r.dip)}</td>`], ["先跌 ≧0.5%", r => `<td>${fmt(r.dip05, 0)}%</td>`], ["開後最高", r => `<td>${pc(r.run)}</td>`],
    ["突破夜盤高", r => `<td>${fmt(r.brk, 0)}%</td>`], ["跌回前日收", r => `<td>${fmt(r.back, 0)}%</td>`],
    ["收盤 vs 夜收", r => `<td>${pc(r.c_n)}</td>`], ["收盤 vs 前日收", r => `<td>${pc(r.c_p)}</td>`]];
  return `<div class="lu-box"><div class="lu-title">⑧ 結算前一晚夜盤大漲 → 結算日日盤（台指期近月，${N.from} 起）</div>
    <div class="k" style="margin-bottom:6px">${N.def}。夜盤在期交所算在隔天（例如 10/20 晚上的夜盤＝10/21）。「開高／開平／開低」是日盤開盤相對夜盤收盤。</div>
    <div class="lu-title">所有交易日（基準）</div><div class="ch-scroll">${chTable(cols, N.all)}</div>
    <div class="lu-title" style="margin-top:8px">結算日（${N.n_settle} 次結算中符合的）</div><div class="ch-scroll">${chTable(cols, N.settle)}</div>
    <div class="lu-title" style="margin-top:8px">結算日：依前一晚夜盤漲跌分組（不限收高）</div><div class="ch-scroll">${chTable(cols, N.settle_by_night)}</div>
    <div class="lu-title" style="margin-top:8px">結算日前一晚夜盤漲 ≧0.5% 的明細</div><div class="ch-scroll">${chTable([["結算日", r => `<td>${r.date}</td>`],
      ["夜盤漲幅", r => `<td>${pc(r.night)}</td>`], ["夜盤收在區間", r => `<td>${fmt(r.n_pos, 0)}%</td>`], ["開盤 vs 夜收", r => `<td>${pc(r.gap_n)}</td>`],
      ["開→收", r => `<td><b>${pc(r.o2c)}</b></td>`], ["開後最低", r => `<td>${pc(r.dip)}</td>`], ["開後最高", r => `<td>${pc(r.run)}</td>`],
      ["突破夜盤高", r => `<td>${r.brk ? "是" : "否"}</td>`], ["收盤 vs 夜收", r => `<td>${pc(r.c_n)}</td>`], ["收盤 vs 前日收", r => `<td>${pc(r.c_p)}</td>`]], N.detail)}</div>
    <div class="k">「開後最低／最高」＝日盤最低／最高相對開盤；「突破夜盤高」＝日盤最高超過前一晚夜盤最高；「跌回前日收」＝日盤最低跌破前一天日盤收盤</div></div>`;
}


let SETL5_CH = null;
function setlNight5(O){
  const N = O.night5; if (!N) return "";
  const s = N.summary, pc = v => chP(v);
  const up = N.days.filter(d => d.night >= 0.5);
  return `<div class="lu-box"><div class="lu-title">⑨ 5 分K：前一晚夜盤漲 ≧0.5% 的隔天日盤怎麼走（台指期近月，${s.from} ~ ${s.to}，共 ${s.n_up} 天）</div>
    <div class="lu-guide"><ul>
      <li>${s.n_up} 天裡有 <b>${s.low_first} 天「先低後高」</b>（當天低點比高點早出現），${s.n_up - s.low_first} 天「先高後低」；所有日子「先低後高」的比例是 ${fmt(s.all_low_first, 0)}%</li>
      <li>真正「先壓 ≧0.3% 再 V 上去收紅」的有 <b>${s.v} 天</b>；開盤後平均最低 ${pc(s.dip)}，開→收平均 ${pc(s.o2c)}，收紅 ${fmt(s.red, 0)}%</li>
      <li>11:00 之後到收盤平均 ${pc(s.pm)}（下午常常回落）</li></ul></div>
    <div class="k" style="margin:6px 0">每條線＝一天的日盤走勢（以開盤為 0%）。期交所逐筆成交只保留最近 30 個交易日，所以 5 分K 樣本只有這幾天，之後每天會自動累積</div>
    <div id="setl5" style="height:340px"></div>
    <div class="ch-scroll" style="margin-top:8px">${chTable([["日期", r => `<td>${r.date}${r.settle ? " <b class='up'>結算</b>" : ""}</td>`],
      ["夜盤", r => `<td>${pc(r.night)}</td>`], ["夜盤收在區間", r => `<td>${fmt(r.n_pos, 0)}%</td>`], ["開盤vs夜收", r => `<td>${pc(r.gap_n)}</td>`],
      ["低點", r => `<td>${r.lo_t}（${pc(r.lo)}）</td>`], ["高點", r => `<td>${r.hi_t}（${pc(r.hi)}）</td>`], ["路徑", r => `<td>${r.path}${r.v ? "（V轉）" : ""}</td>`],
      ["11點後", r => `<td>${pc(r.pm)}</td>`], ["開→收", r => `<td><b>${pc(r.o2c)}</b></td>`], ["收盤vs夜收", r => `<td>${pc(r.c_n)}</td>`]], up)}</div></div>`;
}
function setlNight5Chart(O){
  const el = $("setl5"), N = O.night5; if (!el || !N) return;
  if (SETL5_CH) { try { SETL5_CH.remove(); } catch(e) {} }
  const ch = SETL5_CH = LW.createChart(el, {autoSize: true, layout: {background: {color: "#1e222d"}, textColor: "#d1d4dc"},
    grid: {vertLines: {color: "#262b38"}, horzLines: {color: "#262b38"}}, rightPriceScale: {borderColor: "#2a2e39"},
    timeScale: {borderColor: "#2a2e39", timeVisible: true, secondsVisible: false}, crosshair: {mode: 0}, localization: TW_LOCALE});
  const t0 = Date.UTC(2000, 0, 3, 8, 45) / 1000;
  const cols = ["#ffd600", "#4fc3f7", "#f48fb1", "#a5d6a7", "#ffb74d", "#ce93d8", "#80cbc4", "#ef9a9a", "#90caf9", "#e6ee9c", "#bcaaa4", "#b0bec5"];
  N.days.filter(d => d.night >= 0.5).forEach((d, i) => {
    const s = ch.addSeries(LW.LineSeries, {color: cols[i % cols.length], lineWidth: d.settle ? 3 : 1.5, priceLineVisible: false, lastValueVisible: false,
      title: d.date.slice(5), priceFormat: {type: "custom", formatter: v => v.toFixed(2) + "%"}});
    s.setData(d.curve.map((v, k) => ({time: t0 + k * 300, value: v})));
  });
  ch.addSeries(LW.LineSeries, {color: "rgba(255,255,255,.35)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false})
    .setData([{time: t0, value: 0}, {time: t0 + 59 * 300, value: 0}]);
  const fit = () => ch.timeScale().fitContent(); fit(); [80, 400].forEach(ms => setTimeout(fit, ms));
}


// ---------- 🎫 權證分點 ----------
let WARR = null, warrDate = "", SNAP = null, warrOpen = null, warrHideCorp = lsGet("warrHideCorp", "0") === "1";
const ptTag = t => t === "隔日沖" ? `<span class="ptype t1">隔日沖</span>` : t === "短波段" ? `<span class="ptype t2">短波段</span>`
  : t === "長波段" ? `<span class="ptype t3">長波段</span>` : t === "混合" ? `<span class="ptype">混合</span>` : `<span class="ptype k">累積中</span>`;
const cpTag = cp => cp === "P" ? `<span class="down">售</span>` : `<span class="up">購</span>`;
const wan = v => v == null ? "–" : `${Math.round(v).toLocaleString()} 萬`;

async function warrShow(){
  if (chTab !== "warr") return;       // 重試／計時器觸發時已經切到別的分頁，不要蓋掉別頁的內容
  if (!WARR || (warrDate && WARR.date !== warrDate)) {
    $("chBody").innerHTML = `<div class="k" style="padding:20px">整理權證分點中…</div>`;
    try { [WARR, SNAP] = await Promise.all([api("/api/warrants" + (warrDate ? "?date=" + warrDate : "")), api("/api/warrants/snap")]); }
    catch(e) { setTimeout(warrShow, 3000); return; }
  }
  if (chTab !== "warr") return;       // 載入期間已經切到別的分頁
  const W = WARR, S = SNAP || {};
  if (W.dates) $("chDate").innerHTML = W.dates.map(d => `<option ${d === W.date ? "selected" : ""}>${d}</option>`).join("");
  const st = S.status || {}, job = S.job || {};
  const stock = (c, n) => `<span class="ch-c" data-c="${c}">${c} ${n || ""}</span>`;
  const brLink = (b) => `<span class="wb-c" data-wb="${b}">${b}</span>`;
  const h = [];
  // ===== 盤中快照 =====
  h.push(`<div class="lu-box"><div class="lu-title">⏰ 盤中快照：熱門標的的權證大單（每天 12:00 自動抓一次）
      <button class="btn ghost" id="snapNow" style="margin-left:auto;padding:3px 10px">⟳ 現在抓一次</button></div>
    ${S.error ? `<div class="k">${S.error}${job.running ? `（${job.msg}）` : ""}</div>` : `
    <div class="k" style="margin-bottom:6px">快照時間 ${S.ts}｜${S.rule}｜比較基準：${S.prev} 全天成交金額${job.running ? `｜⏳ ${job.msg}` : ""}</div>
    <div class="lu-row"><div class="grow ch-scroll" style="max-height:360px">${chTable([["標的", r => `<td>${stock(r.code, r.name)}</td>`],
      ["標的漲跌", r => `<td>${chP(r.chg)}</td>`], ["認購成交", r => `<td>${wan(r.amt_c)}</td>`], ["認售成交", r => `<td>${wan(r.amt_p)}</td>`],
      ["大單權證", r => `<td>${r.n_big ? `<b class="up">${r.n_big} 檔</b>` : "–"}</td>`]], S.unds || [])}</div>
    <div class="grow ch-scroll" style="max-height:360px">${chTable([["權證", r => `<td>${r.code} ${r.name || ""} ${cpTag(r.cp)}</td>`],
      ["標的", r => `<td>${stock(r.und, r.und_name)}</td>`], ["權證漲跌", r => `<td>${chP(r.wchg)}</td>`], ["到 12:00 成交", r => `<td><b>${wan(r.amt)}</b></td>`],
      ["昨天全天", r => `<td>${wan(r.y_amt)}</td>`], ["倍數", r => `<td>${r.x ? fmt(r.x, 1) + " 倍" : "新"}</td>`]], S.warrants || [])}</div></div>
    <div class="k">盤中看不到是哪個分點（分點收盤後才公布）；這裡用「到中午的成交金額」對比「昨天全天」找出異常放大的權證</div>`}</div>`);
  if (W.error) { h.push(`<div class="lu-box k">${W.error}｜資料：${st.broker ? `分點 ${st.broker[2]} 天` : ""}</div>`); $("chBody").innerHTML = h.join(""); warrBind(); return; }
  // ===== 盤後 =====
  const ec = W.ev_count || {};
  h.push(`<div class="ch-cards">
    <div class="mcard"><span class="k">${W.date} 單一分點大量進場</span><b>${W.events.length} 筆</b><span class="k">${W.rule}</span></div>
    <div class="mcard"><span class="k">資料累積</span><b>${W.n_dates} 天</b><span class="k">${st.broker ? `${st.broker[0]} ~ ${st.broker[1]}｜${st.broker[3].toLocaleString()} 檔權證` : ""}</span></div>
    <div class="mcard"><span class="k">大量買進後的去向（全部事件）</span><b>隔日沖 ${ec["隔日沖"] || 0}｜短 ${ec["短波段"] || 0}｜長 ${ec["長波段"] || 0}</b><span class="k">觀察中 ${ec["觀察中"] || 0} 筆</span></div>
    <div class="mcard"><span class="k">分點類型</span><b>${W.profiles.length} 個分點</b><span class="k">至少 3 筆完成的事件才分類</span></div></div>`);
  const evs = warrHideCorp ? W.events.filter(e => !e.corp) : W.events;
  h.push(`<div class="lu-box"><div class="lu-title">🎯 單一分點大量進場（${W.date}，${evs.length} 筆）<span class="k" style="margin-left:8px">點分點名稱可以看他最近在權證的每日買賣</span>
    <label class="k" style="margin-left:auto"><input type="checkbox" id="warrCorp" ${warrHideCorp ? "checked" : ""}> 隱藏券商總公司（常是自營／避險）</label></div>
    <div class="ch-scroll" style="max-height:560px">${chTable([["標的", r => `<td>${stock(r.und, r.und_name)}</td>`], ["權證", r => `<td>${r.code} ${r.name || ""} ${cpTag(r.cp)}</td>`],
      ["分點", r => `<td>${brLink(r.branch)}${r.corp ? "<span class='ptype'>總公司</span>" : ""} ${ptTag(r.ptype)}</td>`], ["買超", r => `<td class="up"><b>${chL(r.net)} 張</b></td>`], ["金額", r => `<td><b>${wan(r.amt)}</b></td>`],
      ["佔成交量", r => `<td>${fmt(r.pct, 0)}%</td>`], ["連續買", r => `<td>${r.streak > 1 ? `<b class="up">連 ${r.streak} 天</b>` : "第 1 天"}</td>`],
      ["權證收盤", r => `<td>${fmt(r.close)}（${chN(r.chg, 2)}）</td>`]], evs)}</div>
    <div class="k">已排除發行商自己的分點（造市）；分點類型：大量買進後 1 天內賣掉一半以上＝隔日沖、2~5 天＝短波段、超過 5 天＝長波段（依過去紀錄）</div></div>`);
  h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">📊 標的排行（依單一分點大量買進金額）<span class="k" style="margin-left:8px">點一列展開權證和分點</span></div>
    <div class="ch-scroll" style="max-height:640px"><table class="lu-t"><tr><th>標的</th><th>大量進場</th><th>金額</th><th>認購成交</th><th>認售成交</th><th>權證數</th></tr>
    ${W.unds.map(u => `<tr class="w-und" data-u="${u.code}"><td>${stock(u.code, u.name)}</td><td>${u.big_n ? `<b class="up">${u.big_n} 筆</b>` : "–"}</td>
      <td>${u.big_amt ? wan(u.big_amt) : "–"}</td><td>${wan(u.amt_c)}</td><td>${wan(u.amt_p)}</td><td>${u.n}</td></tr>
      ${warrOpen === u.code && W.detail[u.code] ? `<tr><td colspan="6" style="text-align:left;white-space:normal;background:var(--bg)">${W.detail[u.code].map(w =>
        `<div style="padding:4px 0;border-bottom:1px solid var(--line)"><b>${w.code} ${w.name || ""}</b> ${cpTag(w.cp)} <span class="k">收 ${fmt(w.close)}｜成交 ${wan(w.amt)}</span><br>
        <span class="k">買超：</span>${w.buys.map(b => `${brLink(b.branch)}${b.hq ? "<span class='k'>(造市)</span>" : ""} <span class="up">${chL(b.net)}張/${wan(b.amt)}</span>`).join("、") || "–"}
        <span class="k">｜賣超：</span>${w.sells.map(b => `${b.branch}${b.hq ? "<span class='k'>(造市)</span>" : ""} <span class="down">${chL(-b.net)}張</span>`).join("、") || "–"}</div>`).join("")}</td></tr>` : ""}`).join("")}
    </table></div></div>
    <div class="lu-box side"><div class="lu-title">🧭 分點類型（慢慢累積）</div><div class="ch-scroll" style="max-height:640px">
    ${chTable([["分點", r => `<td>${brLink(r.branch)}</td>`], ["類型", r => `<td>${ptTag(r.type)}</td>`], ["事件", r => `<td>${r.n_done}/${r.n}</td>`],
      ["隔日沖", r => `<td>${fmt(r["隔日沖"], 0)}%</td>`], ["短波段", r => `<td>${fmt(r["短波段"], 0)}%</td>`], ["長波段", r => `<td>${fmt(r["長波段"], 0)}%</td>`],
      ["平均持有", r => `<td>${r.avg_hold ? fmt(r.avg_hold, 1) + " 天" : "–"}</td>`]], warrHideCorp ? W.profiles.filter(p => !p.corp) : W.profiles)}</div>
    <div class="k">事件＝已經知道結果的筆數／全部大量買進筆數。分點資料只有每檔前 15 名，小量分批賣出可能看不到</div></div></div>`);
  $("chBody").innerHTML = h.join("");
  warrBind();
}

function warrBind(){
  document.querySelectorAll("#chBody .ch-c").forEach(e => e.onclick = ev => { ev.stopPropagation(); showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
  document.querySelectorAll("#chBody [data-wb]").forEach(e => e.onclick = ev => { ev.stopPropagation(); wbOpen(e.dataset.wb); });
  document.querySelectorAll("#chBody .w-und").forEach(tr => tr.onclick = () => { warrOpen = warrOpen === tr.dataset.u ? null : tr.dataset.u; warrShow(); });
  const hc = $("warrCorp"); if (hc) hc.onchange = () => { warrHideCorp = hc.checked; lsSet("warrHideCorp", hc.checked ? "1" : "0"); warrShow(); };
  const b = $("snapNow"); if (b) b.onclick = async () => { await post("/api/warrants/snap"); b.textContent = "⏳ 抓取中…（約 1~3 分鐘）"; setTimeout(async () => { SNAP = await api("/api/warrants/snap"); warrShow(); }, 90000); };
}

async function wbOpen(name){
  $("wbTitle").textContent = `${name}：最近在權證的買賣`;
  $("wbClose").onclick = () => $("dlgWb").close();
  if (!$("dlgWb").open) $("dlgWb").showModal();
  $("wbBody").innerHTML = `<div class="k">查詢中…</div>`;
  const d = await api("/api/warrants/branch?name=" + encodeURIComponent(name));
  const p = (WARR && WARR.profiles || []).find(x => x.branch === name);
  // 依日期 × 標的 排成時間軸
  const days = [...new Set(d.rows.map(r => r.date))];
  $("wbBody").innerHTML = `${p ? `<div class="k" style="margin-bottom:6px">類型：${ptTag(p.type)}｜大量買進 ${p.n} 筆（已知結果 ${p.n_done}）｜隔日沖 ${fmt(p["隔日沖"], 0)}%、短波段 ${fmt(p["短波段"], 0)}%、長波段 ${fmt(p["長波段"], 0)}%｜平均持有 ${p.avg_hold ? fmt(p.avg_hold, 1) + " 天" : "–"}</div>` : ""}
    <div class="lu-row"><div class="lu-box side" style="width:300px"><div class="lu-title">依標的（淨買賣金額）</div>
      ${chTable([["標的", r => `<td>${r.und} ${r.und_name || ""}</td>`], ["淨額", r => `<td>${wan(r.amt)}</td>`], ["天數", r => `<td>${r.days}</td>`]], d.by_und || [])}</div>
    <div class="lu-box grow"><div class="lu-title">每日明細（只含當天成交前幾名的權證；紅＝買超、綠＝賣超）</div><div class="ch-scroll" style="max-height:600px">
      ${chTable([["日期", r => `<td>${r.date}</td>`], ["標的", r => `<td>${r.und} ${r.und_name || ""}</td>`], ["權證", r => `<td>${r.code} ${r.name || ""} ${cpTag(r.cp)}</td>`],
        ["買賣超", r => `<td class="${r.net > 0 ? "up" : "down"}"><b>${r.net > 0 ? "+" : ""}${chL(r.net)} 張</b></td>`], ["金額", r => `<td>${wan(r.amt)}</td>`],
        ["佔成交量", r => `<td>${fmt(r.pct, 0)}%</td>`]], d.rows)}</div>
      <div class="k">共 ${days.length} 個交易日有紀錄</div></div></div>`;
}


// ---------- 右側固定：週累籌碼（各履約價 Sell Call ／ Sell Put）----------
let oiMode = lsGet("oiMode", "week"), oiRange = +lsGet("oiRange", "3"), oiStep = +lsGet("oiStep", "50");
function oiPanel(){
  const o = OPT, st = o.strikes;
  if (!st) return `<div class="k">沒有履約價資料</div>`;
  const ct = st.contracts[Math.min(optCt, st.contracts.length - 1)];
  const px = o.px;
  const M = {
    week: {t: "累計賣方", l: "Sell Call", r: "Sell Put", c: x => x.swc, p: x => x.swp, sub: (x, s) => s === "c" ? x.s1c : x.s1p, note: `數字＝今天（${ct.base_name}）推估賣方淨新增`},
    today: {t: "今日賣方", l: "Sell Call", r: "Sell Put", c: x => x.s1c, p: x => x.s1p, sub: (x, s) => s === "c" ? x.sc : x.sp, note: `數字＝今天（${ct.base_name}）推估賣方淨新增`},
    oi: {t: "未平倉量", l: "Call 未平倉", r: "Put 未平倉", c: x => x.c, p: x => x.p, sub: (x, s) => s === "c" ? x.cw : x.pw, note: `數字＝${ct.base_name}的增減（目前未平倉口數）`},
  }[oiMode];
  const rows = ct.dist.filter(x => Math.abs(x.k / px - 1) * 100 <= oiRange && (x.k % oiStep === 0)).sort((a, b) => b.k - a.k);
  const mx = Math.max(1, ...rows.map(x => Math.max(Math.abs(M.c(x)), Math.abs(M.p(x)))));
  const num = v => v == null ? "" : (v > 0 && oiMode !== "oi" ? "" : "") + Math.round(v).toLocaleString();
  const lab = (x, side) => {
    const main = side === "c" ? M.c(x) : M.p(x), sub = M.sub(x, side);
    if (oiMode === "oi") return `${sub ? `<span class="${sub > 0 ? "oi-add" : "oi-cut"}">${sub > 0 ? "+" : ""}${num(sub)}</span> ` : ""}<span class="oi-tot">(${num(main)})</span>`;
    return `${num(sub)} <span class="oi-tot">(${num(main)})</span>`;
  };
  const maxC = rows.reduce((a, x) => M.c(x) > (a ? M.c(a) : -1e9) ? x : a, null), maxP = rows.reduce((a, x) => M.p(x) > (a ? M.p(a) : -1e9) ? x : a, null);
  const atm = rows.reduce((a, x) => Math.abs(x.k - px) < Math.abs(a.k - px) ? x : a, rows[0] || {k: px});
  const bar = (v, side) => {
    const w = Math.min(100, Math.abs(v) / mx * 100);
    const cls = v >= 0 ? (side === "c" ? "oi-bc" : "oi-bp") : "oi-bn";
    return `<i class="${cls}" style="width:${w}%"></i>`;
  };
  return `<div class="oi-head"><b>📊 ${M.t}</b><span class="k">${st.date}｜${ct.base_name}</span>
      <button class="btn ghost" id="oiUpd" title="從期交所抓最新的選擇權未平倉">⟳ 更新未平倉</button></div>
    <select id="optCt" class="sub-sel" style="width:100%;margin:6px 0">${st.contracts.map((c, i) => `<option value="${i}" ${i === optCt ? "selected" : ""}>${c.name}</option>`).join("")}</select>
    <div class="oi-ctl">
      <span class="lu-studies">${[["week", "累計賣方"], ["today", "今日賣方"], ["oi", "未平倉"]].map(([k, n]) => `<button data-oim="${k}" class="${k === oiMode ? "on" : ""}">${n}</button>`).join("")}</span>
      <span class="lu-studies">${[[2, "±2%"], [3, "±3%"], [5, "±5%"]].map(([k, n]) => `<button data-oir="${k}" class="${k === oiRange ? "on" : ""}">${n}</button>`).join("")}</span>
      <span class="lu-studies">${[[50, "50點"], [100, "100點"]].map(([k, n]) => `<button data-ois="${k}" class="${k === oiStep ? "on" : ""}">${n}</button>`).join("")}</span></div>
    <div class="oi-grid oi-top"><div class="oi-lt">${M.l}</div><div class="oi-k">履約價</div><div class="oi-rt">${M.r}</div></div>
    <div class="oi-body">${rows.map(x => {
      const isAtm = x === atm, c = M.c(x), p = M.p(x);
      return `<div class="oi-grid oi-row ${isAtm ? "oi-atm" : ""}" title="Call 未平倉 ${x.c.toLocaleString()}（今天 ${x.c1 >= 0 ? "+" : ""}${x.c1}）${x.cpx != null ? "，權利金 " + x.cpx : ""}｜Put 未平倉 ${x.p.toLocaleString()}（今天 ${x.p1 >= 0 ? "+" : ""}${x.p1}）${x.ppx != null ? "，權利金 " + x.ppx : ""}">
        <div class="oi-l"><span class="oi-lab">${c || M.sub(x, "c") ? lab(x, "c") : ""}</span>${bar(c, "c")}</div>
        <div class="oi-k ${maxC === x ? "oi-kc" : maxP === x ? "oi-kp" : ""}">${x.k.toLocaleString()}${isAtm ? "<span class='oi-now'>◀ 現價</span>" : ""}</div>
        <div class="oi-r">${bar(p, "p")}<span class="oi-lab">${p || M.sub(x, "p") ? lab(x, "p") : ""}</span></div></div>`;
    }).join("")}</div>
    <div class="oi-axis"><span>${Math.round(mx).toLocaleString()}</span><span>${Math.round(mx / 2).toLocaleString()}</span><span>0</span><span>${Math.round(mx / 2).toLocaleString()}</span><span>${Math.round(mx).toLocaleString()}</span></div>
    ${ct.kind === "month_all" ? `<div class="k" style="color:#ffcc80;margin-top:4px">⚠ 含已到期的週選：累計的是期間賣方新增過的量，到期的部分已經不在了，不代表現在還有這些部位</div>` : ""}
    <div class="k" style="margin-top:6px;line-height:1.6">${M.note}｜現價 ${fmt(px, 0)}｜最大痛點 ${ct.max_pain ? ct.max_pain.toLocaleString() : "–"}<br>
      <span class="oi-sw c"></span>Sell Call（壓力）<span class="oi-sw p"></span>Sell Put（支撐）<span class="oi-sw n"></span>賣方回補｜<span style="color:#ef9a9a">紅字履約價</span>＝Call 最大、<span style="color:#80cbc4">綠字</span>＝Put 最大｜滑鼠移到列上看未平倉、權利金</div>`;
}
function oiBind(){
  document.querySelectorAll("#optSide [data-oim]").forEach(b => b.onclick = () => { oiMode = b.dataset.oim; lsSet("oiMode", oiMode); oiRefresh(); });
  document.querySelectorAll("#optSide [data-oir]").forEach(b => b.onclick = () => { oiRange = +b.dataset.oir; lsSet("oiRange", oiRange); oiRefresh(); });
  document.querySelectorAll("#optSide [data-ois]").forEach(b => b.onclick = () => { oiStep = +b.dataset.ois; lsSet("oiStep", oiStep); oiRefresh(); });
  const sel = $("optCt"); if (sel) sel.onchange = () => { optCt = +sel.value; optShow(); };
  const u = $("oiUpd");
  if (u) u.onclick = async () => {
    u.disabled = true; u.textContent = "⏳ 抓取中…";
    await post("/api/options/update");
    const t0 = Date.now();
    const poll = async () => {
      const s = await api("/api/options/status");
      if (s.running && Date.now() - t0 < 600000) { setTimeout(poll, 3000); return; }
      OPT = null; await optShow();
      const u2 = $("oiUpd"); if (u2) { u2.textContent = "✅ 已更新"; setTimeout(() => { if ($("oiUpd")) $("oiUpd").textContent = "⟳ 更新未平倉"; }, 4000); }
    };
    setTimeout(poll, 2000);
  };
  // 打開時把現價那一列捲到中間
  const atm = document.querySelector("#optSide .oi-atm"), body = document.querySelector("#optSide .oi-body");
  if (atm && body) body.scrollTop = atm.offsetTop - body.offsetTop - body.clientHeight / 2;
}
function oiRefresh(){ $("optSide").innerHTML = oiPanel(); oiBind(); }
