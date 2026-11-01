// ---------- 即時報價（大分頁）：自選股、四格看盤、錄影重播（小分頁）----------
// 資料來自群益 API（capital.py）：四格看盤每格有五檔、即時明細、盤中走勢圖；錄影 = 把逐筆和五檔變化存檔，盤後在「錄影重播」播放。
const Q_SUBS = [["watch", "⭐ 自選股", "存關注的股票，看即時報價"], ["board", "🔲 四格看盤", "四檔同時看五檔、即時明細、走勢圖，可以錄影"],
                ["replay", "⏯ 錄影重播", "盤後重播錄下來的四格看盤"]];
let qSub = (() => { const u = new URLSearchParams(location.search).get("sub"); if (u) return u;
  try { return localStorage.getItem("qSub") || "watch"; } catch(e) { return "watch"; } })();
let qTimer = null, qPanes = [null, null, null, null], qCharts = [null, null, null, null];
let qRep = null;   // 重播：{name, meta, events, t0, t1, t, playing, speed}

const qHM = (t, sec) => { const d = new Date(t * 1000), p = n => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}${sec ? ":" + p(d.getUTCSeconds()) : ""}`; };
const qCls = (v, ref) => v == null || ref == null ? "" : v > ref ? "up" : v < ref ? "down" : "";
const qPct = (v, ref) => v == null || !ref ? "" : `${v >= ref ? "+" : ""}${((v / ref - 1) * 100).toFixed(2)}%`;
const qNum = v => v == null ? "–" : (+v).toLocaleString(undefined, {maximumFractionDigits: 2});

function qGo(k){
  qSub = k; try { localStorage.setItem("qSub", k); } catch(e) {}
  $("qGridMenu").classList.remove("open");
  qShow();
  if (typeof renderPages === "function") renderPages();
}

function qShow(){
  clearTimeout(qTimer);
  if (qRep && qRep.playing) qRepPause();
  const x = Q_SUBS.find(s => s[0] === qSub) || Q_SUBS[0];
  $("qSubName").textContent = x[1];
  $("qGridMenu").innerHTML = Q_SUBS.map(([k, n, d]) => `<div class="q-tile ${k === qSub ? "on" : ""}" data-k="${k}"><b>${n}</b><span>${d}</span></div>`).join("");
  $("qGridMenu").querySelectorAll(".q-tile").forEach(t => t.onclick = () => qGo(t.dataset.k));
  $("qRecBtn").style.display = qSub === "board" ? "" : "none";
  qCharts.forEach(c => c && c.chart.remove()); qCharts = [null, null, null, null];
  if (qSub === "watch") qWatch();
  else if (qSub === "board") qBoardInit();
  else qReplayList();
}
function qVisible(){ return window.CUR_PAGE === "quote" && $("pageQuote").style.display !== "none"; }

// 頁面上的群益 API 開關：跟右上角那顆同步
function qCapSync(){
  const b = $("btnCapital"), q = $("qCapBtn");
  if (!b || !q) return;
  q.className = b.className; q.innerHTML = b.innerHTML; q.title = b.title;
}
setInterval(qCapSync, 1000);

// ===== 自選股 =====
async function qWatch(){
  const body = $("qBody");
  if (!body.querySelector("#qwTable")) {
    body.innerHTML = `<div class="qw-bar"><input id="qwAdd" placeholder="輸入代號加入自選（Enter），可一次貼多檔用空白隔開" autocomplete="off">
      <span class="k" id="qwSrc"></span></div>
      <table class="qw" id="qwTable"><thead><tr><th>代號</th><th>名稱</th><th>成交</th><th>漲跌</th><th>漲跌%</th><th>開</th><th>高</th><th>低</th><th>量(張)</th><th>時間</th><th></th></tr></thead><tbody></tbody></table>
      <div class="k" style="margin-top:6px">點名稱放進四格看盤（A、B 兩組共 8 格，放到第一個空格，都滿了就換掉 A 組第 1 格）；按 ✕ 移除。</div>`;
    $("qwAdd").onkeydown = async e => {
      if (e.key !== "Enter") return;
      const add = e.target.value.split(/[\s,，]+/).filter(Boolean);
      e.target.value = "";
      const cur = (await api("/api/rt/watch")).rows.map(r => r.code);
      await post("/api/rt/watch", {codes: [...cur, ...add.filter(c => !cur.includes(c))]});
      qWatch();
    };
  }
  let j;
  try { j = await api("/api/rt/watch"); } catch(e) { qTimer = setTimeout(qWatch, 5000); return; }
  $("qwSrc").textContent = "報價來源：" + j.src;
  const tb = $("qwTable").querySelector("tbody");
  tb.innerHTML = j.rows.length ? j.rows.map(r => {
    const c = qCls(r.z, r.y), d = r.z != null && r.y != null ? r.z - r.y : null;
    return `<tr><td>${r.code}</td><td><a class="qw-nm" data-c="${r.code}">${r.name || ""}</a></td>
      <td class="${c}"><b>${qNum(r.z)}</b></td><td class="${c}">${d == null ? "–" : (d > 0 ? "+" : "") + d.toFixed(2)}</td><td class="${c}">${qPct(r.z, r.y)}</td>
      <td class="${qCls(r.o, r.y)}">${qNum(r.o)}</td><td class="${qCls(r.h, r.y)}">${qNum(r.h)}</td><td class="${qCls(r.l, r.y)}">${qNum(r.l)}</td>
      <td>${qNum(r.v)}</td><td class="k">${r.t || ""}</td><td><button class="btn ghost qw-del" data-c="${r.code}">✕</button></td></tr>`;
  }).join("") : `<tr><td colspan="11" class="k" style="text-align:center;padding:20px">還沒有自選股，在上面輸入代號按 Enter</td></tr>`;
  tb.querySelectorAll(".qw-del").forEach(b => b.onclick = async () => {
    await post("/api/rt/watch", {codes: j.rows.map(r => r.code).filter(c => c !== b.dataset.c)}); qWatch();
  });
  tb.querySelectorAll(".qw-nm").forEach(a => a.onclick = () => {
    const codes = qBoardCodes();
    let i = codes.indexOf(a.dataset.c);
    if (i < 0) { i = codes.indexOf("") >= 0 ? codes.indexOf("") : 0; codes[i] = a.dataset.c; }
    S.settings.rt_board = codes;
    qGrp = i >= 4 ? 1 : 0; try { localStorage.setItem("qGrp", qGrp); } catch(e) {}
    qGo("board");
  });
  if (qVisible() && qSub === "watch") qTimer = setTimeout(qWatch, 3000);
}

// ===== 四格看盤（A、B 兩組，共 8 檔；兩組都會訂閱、錄影時一起錄）=====
const qBoardCodes = () => [...((S && S.settings.rt_board) || []), ...Array(8).fill("")].slice(0, 8);
let qGrp = (() => { try { return +localStorage.getItem("qGrp") || 0; } catch(e) { return 0; } })();

// A／B 組切換按鈕：每組顯示裡面的股票代號
function qGrpHTML(slots, cur, id){
  return `<div class="q-grp" id="${id}">` + [0, 1].map(g => {
    const cs = slots.slice(g * 4, g * 4 + 4).filter(Boolean);
    return `<button class="btn ${g === cur ? "" : "ghost"}" data-g="${g}">${"AB"[g]} 組 <span class="k">${cs.join("、") || "（空）"}</span></button>`;
  }).join("") + `</div>`;
}

function qBoardInit(){
  const codes = qBoardCodes(), mine = codes.slice(qGrp * 4, qGrp * 4 + 4);
  qCharts.forEach(c => c && c.chart.remove()); qCharts = [null, null, null, null];
  $("qBody").innerHTML = qGrpHTML(codes, qGrp, "qbGrp") + `<div class="qb-msg k" id="qbMsg"></div><div class="qb" id="qb">` +
    mine.map((c, i) => qPaneHTML(i, c)).join("") + `</div>`;
  $("qbGrp").querySelectorAll("[data-g]").forEach(b => b.onclick = () => {
    qGrp = +b.dataset.g; try { localStorage.setItem("qGrp", qGrp); } catch(e) {} qBoardInit();
  });
  mine.forEach((c, i) => {
    const inp = $("qbIn" + i);
    inp.onkeydown = e => {
      if (e.key !== "Enter") return;
      const cs = qBoardCodes(); cs[qGrp * 4 + i] = inp.value.trim(); S.settings.rt_board = cs;
      qBoardInit();
    };
  });
  qBoardTick();
}
// 版面仿群益新超級贏家「商品盤勢」：左邊走勢圖＋量，右邊統計表、內外盤比例、五檔、即時明細
function qPaneHTML(i, code, ro){
  return `<div class="qp" id="qp${i}">
    <div class="qp-head"><input id="qbIn${i}" value="${code || ""}" placeholder="代號" ${ro ? "readonly" : ""}><span class="qp-name" id="qpName${i}"></span>
      <span class="qp-px" id="qpPx${i}"></span>${qKBtnHTML()}</div>
    <div class="qp-main"><div class="qp-chart" id="qpChart${i}"></div>
      <div class="qp-side"><table class="qp-st" id="qpSt${i}"></table><div class="qp-io" id="qpIo${i}"></div>
        <table class="qp-b5" id="qpB5${i}"></table><div class="qp-ticks" id="qpTk${i}"></div></div></div></div>`;
}

// 逐筆 → 統計（跟 capital.tick_stats 一樣，重播時在網頁算）
function qTickStats(ticks){
  if (!ticks.length) return [{}, []];
  let tot = 0, amt = 0, inner = 0, outer = 0, hi = -Infinity, lo = Infinity; const cum = [];
  for (const [, p, q, b, a] of ticks) {
    tot += q; amt += p * q; hi = Math.max(hi, p); lo = Math.min(lo, p);
    if (a > 0 && p >= a) outer += q; else if (b > 0 && p <= b) inner += q;
    cum.push(tot);
  }
  const l = ticks[ticks.length - 1];
  return [{open: ticks[0][1], high: hi, low: lo, last: l[1], lastq: l[2], t: l[0], total: tot, amount: amt * 1000,
           vwap: tot ? amt / tot : null, inner, outer}, cum];
}

async function qBoardTick(){
  clearTimeout(qTimer);
  if (!qVisible() || qSub !== "board") return;
  let j;
  try { j = await api("/api/rt/board?grp=" + qGrp + "&codes=" + qBoardCodes().join(",")); } catch(e) { qTimer = setTimeout(qBoardTick, 3000); return; }
  qRecShow(j.rec);
  if (!j.ready) {
    $("qbMsg").innerHTML = `群益 API 沒有連線（${j.msg}）。四格看盤需要群益的五檔和逐筆，請按上面的「群益 API」開關。`;
    qTimer = setTimeout(qBoardTick, 3000);
    return;
  }
  $("qbMsg").textContent = "";
  j.panes.forEach((p, i) => qPaneDraw(i, p));
  qTimer = setTimeout(qBoardTick, 1000);
}

// 畫一格：p = {code, name, ref, q, best5, st, ticks:[[秒,價,量,買,賣,毫秒,累計量]], bars:[[秒,開,高,低,收,張]]}
function qPaneDraw(i, p){
  if (!p) {
    ["qpName", "qpPx", "qpSt", "qpIo", "qpB5"].forEach(k => $(k + i).innerHTML = "");
    $("qpTk" + i).innerHTML = `<div class="k" style="padding:8px">輸入代號按 Enter</div>`;
    if (qCharts[i]) { qCharts[i].chart.remove(); qCharts[i] = null; }
    return;
  }
  const st = p.st || {}, q = p.q || {};
  const ref = p.ref || st.open || null, z = st.last ?? q.z;
  const c = v => qCls(v, ref), sgn = v => v == null ? "–" : (v > 0 ? "▲" : v < 0 ? "▼" : "") + Math.abs(v).toFixed(2);
  $("qpName" + i).textContent = `${p.name || ""}(${p.code})`;
  $("qpPx" + i).innerHTML = z == null ? `<span class="k">等待資料…</span>` :
    `<b class="${c(z)}">${qNum(z)}</b> <b class="${c(z)}">${sgn(ref ? z - ref : null)}</b> <b class="${c(z)}">${qPct(z, ref)}</b> <b class="vol">${qNum(st.total ?? q.v)}張</b>`;
  // 統計表（兩欄）
  const amt = st.amount == null ? "–" : st.amount >= 1e8 ? (st.amount / 1e8).toFixed(st.amount >= 1e10 ? 0 : 1) + "億" : (st.amount / 1e4).toFixed(0) + "萬";
  const cell = (k, v, cl = "") => `<td class="k">${k}</td><td class="${cl}">${v}</td>`;
  $("qpSt" + i).innerHTML = [
    [cell("成交", qNum(z), c(z)), cell("時間", st.t ? qHM(st.t, true) : "–")],
    [cell("漲跌", sgn(ref && z != null ? z - ref : null), c(z)), cell("單量", qNum(st.lastq), "yel")],
    [cell("漲跌幅", qPct(z, ref) || "–", c(z)), cell("總量", qNum(st.total ?? q.v))],
    [cell("最高", qNum(st.high ?? q.h), c(st.high ?? q.h)), cell("昨量", qNum(q.yv))],
    [cell("最低", qNum(st.low ?? q.l), c(st.low ?? q.l)), cell("昨收", qNum(ref))],
    [cell("均價", st.vwap ? st.vwap.toFixed(2) : "–", c(st.vwap)), cell("開盤", qNum(st.open ?? q.o), c(st.open ?? q.o))],
    [cell("振幅", ref && st.high != null ? "+" + ((st.high - st.low) / ref * 100).toFixed(2) : "–"), cell("成交值", amt)],
    [cell("內盤量", qNum(st.inner), "down"), cell("外盤量", qNum(st.outer), "up")],
  ].map(r => `<tr>${r.join("")}</tr>`).join("");
  const io = (st.inner || 0) + (st.outer || 0), ip = io ? st.inner / io * 100 : 50;
  $("qpIo" + i).innerHTML = io ? `<span class="down">內${ip.toFixed(2)}%</span><span class="io-bar"><span style="width:${ip}%"></span></span><span class="up">外${(100 - ip).toFixed(2)}%</span>` : "";
  // 五檔：左邊買量（粉紅條）＋買價、右邊賣價＋賣量（藍綠條）
  const b5 = p.best5;
  if (b5) {
    const mx = Math.max(1, ...b5.bid.map(x => x[1]), ...b5.ask.map(x => x[1]));
    const sb = b5.bid.reduce((a, x) => a + x[1], 0), sa = b5.ask.reduce((a, x) => a + x[1], 0);
    $("qpB5" + i).innerHTML = `<tr><th>(${sb})</th><th></th><th>買進</th><th>賣出</th><th></th><th>(${sa})</th></tr>` +
      b5.bid.map((bd, k) => { const ak = b5.ask[k];
        return `<tr><td>${bd[1] || ""}</td><td class="bb"><span style="width:${bd[1] / mx * 100}%"></span></td><td class="${c(bd[0])}">${bd[0] ? qNum(bd[0]) : ""}</td>
          <td class="${c(ak[0])}">${ak[0] ? qNum(ak[0]) : ""}</td><td class="ab"><span style="width:${ak[1] / mx * 100}%"></span></td><td>${ak[1] || ""}</td></tr>`; }).join("");
  } else $("qpB5" + i).innerHTML = `<tr><td class="k">五檔等待中…</td></tr>`;
  // 即時明細：時間、買進、賣出、成交、單量、總量（最新在最下面，跟超級贏家一樣）
  // 內外盤：成交在賣價（或更高）= 外盤（買方主動，紅），成交在買價（或更低）= 內盤（賣方主動，綠）
  const side = t => t[4] > 0 && t[1] >= t[4] ? ["外", "io-o"] : t[3] > 0 && t[1] <= t[3] ? ["內", "io-i"] : ["", ""];
  $("qpTk" + i).innerHTML = `<table><tr><th>時間</th><th>買進</th><th>賣出</th><th>成交</th><th>單量</th><th>總量</th></tr>` +
    p.ticks.slice(-40).map(t => { const sc = side(t)[1];
      return `<tr><td>${qHM(t[0], true)}</td><td class="${c(t[3])}">${t[3] ? qNum(t[3]) : ""}</td><td class="${c(t[4])}">${t[4] ? qNum(t[4]) : ""}</td>
      <td class="${c(t[1])}">${qNum(t[1])}</td><td class="${sc || "yel"}">${t[2]}</td><td>${t[6] ?? ""}</td></tr>`; }).join("") + `</table>`;
  const tk = $("qpTk" + i); tk.scrollTop = tk.scrollHeight;
  qChartDraw(i, p.code, ref, p.bars, p.histq);
}

// 走勢圖模式：走勢（1 分鐘收盤連線）／1分K／5分K（今天的逐筆組成）／60分K、日K、週K、月K（歷史從 /api/fut/hist 拿，今天這根用即時 1 分K 接上）。
// 所有格子共用（四格看盤、錄影重播、看盤），記在瀏覽器
let qKMode = (() => { try { return localStorage.getItem("qKMode") || "line"; } catch(e) { return "line"; } })();
const Q_KMODES = [["line", "走勢"], ["1", "1分K"], ["5", "5分K"], ["60", "60分K"], ["D", "日K"], ["W", "週K"], ["M", "月K"]];
const Q_HIST = ["60", "D", "W", "M"];
const qHistCache = {};   // "查詢字串|週期" -> {t, bars, last_date, note, error, loading}
function qHistGet(q, tf){
  const k = q + "|" + tf, h = qHistCache[k];
  if (h && (h.loading || Date.now() - h.t < 300000)) return h;   // 5 分鐘內不重抓
  const nh = qHistCache[k] = {...(h || {bars: []}), loading: true};
  api(`/api/fut/hist?tf=${tf}&${q}`).then(j => Object.assign(nh, j, {t: Date.now(), loading: false}))
    .catch(() => Object.assign(nh, {t: Date.now() - 240000, loading: false}));
  return nh;
}
// 歷史 K 棒接上今天：today = 今天的 1 分K [秒,開,高,低,收,量]（台北時間當作 UTC）
function qMergeToday(hist, today, tf, lastDate){
  const out = hist.map(b => b.slice());
  if (!today.length) return out;
  const agg = bs => [bs[0][0], bs[0][1], Math.max(...bs.map(b => b[2])), Math.min(...bs.map(b => b[3])), bs[bs.length - 1][4], bs.reduce((a, b) => a + b[5], 0)];
  let day = today[0][0] - today[0][0] % 86400;
  if (today[0][0] % 86400 >= 14 * 3600) {   // 夜盤（15:00 開始）算下一個交易日
    day += 86400; const wd = new Date(day * 1000).getUTCDay(); if (wd === 6) day += 2 * 86400; else if (wd === 0) day += 86400;
  }
  if (tf === "60") {
    const off = out.length ? out[out.length - 1][0] % 3600 : 0, by = {};
    for (const b of today) { const k = b[0] - ((b[0] - off) % 3600 + 3600) % 3600; (by[k] = by[k] || []).push(b); }
    const first = Math.min(...Object.keys(by).map(Number));
    return [...out.filter(b => b[0] < first), ...Object.keys(by).map(Number).sort((a, b) => a - b).map(k => { const x = agg(by[k]); x[0] = k; return x; })];
  }
  const ds = new Date(day * 1000).toISOString().slice(0, 10);
  if (lastDate && lastDate >= ds) return out;   // 資料庫已經有今天（盤後更新過）
  const t = agg(today); t[0] = day;
  if (tf === "D") return [...out.filter(b => b[0] < day), t];
  const per = sec => { const d = new Date(sec * 1000);
    if (tf === "M") return d.getUTCFullYear() * 100 + d.getUTCMonth();
    return Math.floor((sec / 86400 + 3) / 7); };   // 週一開始的週編號
  const l = out[out.length - 1];
  if (l && per(l[0]) === per(day)) { l[0] = day; l[2] = Math.max(l[2], t[2]); l[3] = Math.min(l[3], t[3]); l[4] = t[4]; l[5] += t[5]; }
  else out.push(t);
  return out;
}
function qKBtnHTML(){
  return `<span class="qp-kbtn">${Q_KMODES.map(([k, n]) => `<button data-km="${k}" class="${k === qKMode ? "on" : ""}">${n}</button>`).join("")}</span>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest(".qp-kbtn [data-km]");
  if (!b) return;
  qKMode = b.dataset.km; try { localStorage.setItem("qKMode", qKMode); } catch(err) {}
  document.querySelectorAll(".qp-kbtn [data-km]").forEach(x => x.classList.toggle("on", x.dataset.km === qKMode));
  qCharts.forEach((c, k) => { if (c) { c.chart.remove(); qCharts[k] = null; } });   // 下一次更新（1 秒內）用新模式重畫
  if (qRep && !qRep.playing && qSub === "replay" && window.CUR_PAGE === "quote") qRepRender();
});
// 1 分K 併成 N 分K：[秒,開,高,低,收,量]
function qBarsN(bars, n){
  if (n <= 1) return bars;
  const out = [];
  for (const b of bars) {
    const t = b[0] - b[0] % (n * 60), l = out[out.length - 1];
    if (l && l[0] === t) { l[2] = Math.max(l[2], b[2]); l[3] = Math.min(l[3], b[3]); l[4] = b[4]; l[5] += b[5]; }
    else out.push([t, b[1], b[2], b[3], b[4], b[5]]);
  }
  return out;
}

function qChartDraw(i, code, ref, bars, histq){
  const el = $("qpChart" + i);
  let c = qCharts[i];
  if (c && (c.code !== code || c.mode !== qKMode)) { c.chart.remove(); c = qCharts[i] = null; }
  const kline = qKMode !== "line", hist = Q_HIST.includes(qKMode), daily = hist && qKMode !== "60";
  let h = null;
  if (hist) {
    h = qHistGet(histq || "code=" + encodeURIComponent(code), qKMode);
    bars = qMergeToday(h.bars || [], bars, qKMode, h.last_date);
  } else bars = qBarsN(bars, kline ? +qKMode : 1);
  if (!c) {
    const chart = LW.createChart(el, {width: el.clientWidth, height: el.clientHeight,
      layout: {background: {color: "#000"}, textColor: "#d1d4dc", fontSize: 10, attributionLogo: false, panes: {separatorColor: "#2a2e39"}},
      grid: {vertLines: {color: "#1e222d"}, horzLines: {color: "#1e222d"}},
      rightPriceScale: {borderColor: "#2a2e39"}, timeScale: {borderColor: "#2a2e39", timeVisible: !daily, secondsVisible: false},
      crosshair: {mode: 0}, localization: typeof TW_LOCALE !== "undefined" ? TW_LOCALE : undefined});
    // 價格軸只放當天最高到最低（上下留一點邊），走勢的起伏才看得清楚；昨收虛線不在範圍內就不顯示
    const price = kline   // K 棒：紅漲綠跌（台股習慣）
      ? chart.addSeries(LW.CandlestickSeries, {upColor: "#f23645", downColor: "#00c853", borderUpColor: "#f23645", borderDownColor: "#00c853",
                                               wickUpColor: "#f23645", wickDownColor: "#00c853", priceLineVisible: false})
      : chart.addSeries(LW.LineSeries, {color: "#ffeb3b", lineWidth: 1.5, priceLineVisible: false});
    const avg = chart.addSeries(LW.LineSeries, {color: "#00c853", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false});
    chart.priceScale("right").applyOptions({scaleMargins: {top: 0.06, bottom: 0.04}});
    const vol = chart.addSeries(LW.HistogramSeries, {color: "#e040fb", priceFormat: {type: "volume"}, priceLineVisible: false, lastValueVisible: false}, 1);
    try { chart.panes()[0].setStretchFactor(82); chart.panes()[1].setStretchFactor(18); } catch(e) {}
    const markers = LW.createSeriesMarkers(price, []);
    // 滑鼠移到走勢上：右上角顯示那一分鐘的時間、價格、漲跌%、均價、量
    const tip = document.createElement("div");
    tip.className = "qp-tip"; el.appendChild(tip);
    const note = document.createElement("div");   // 歷史週期：資料來源說明／錯誤
    note.className = "qp-note"; el.appendChild(note);
    c = qCharts[i] = {chart, price, avg, vol, markers, note, code, mode: qKMode, ref: null, n: 0, bars: [], avgs: {}};
    chart.subscribeCrosshairMove(pr => {
      const b = pr.time != null && c.bars.find(x => x[0] === pr.time);
      if (!b) { tip.style.display = "none"; return; }
      const r = c.ref, cl = qCls(b[4], r);
      const when = daily ? new Date(b[0] * 1000).toISOString().slice(0, 10) : qHM(b[0]);
      tip.innerHTML = `<span class="k">${when}</span> <b class="${cl}">${qNum(b[4])}</b> <span class="${cl}">${qPct(b[4], r)}</span>` +
        ` <span style="color:#00c853">均 ${c.avgs[b[0]] ? c.avgs[b[0]].toFixed(2) : "–"}</span> <span class="k">量</span> ${b[5]}`;
      tip.style.display = "block";
    });
    new ResizeObserver(() => chart.applyOptions({width: el.clientWidth, height: el.clientHeight})).observe(el);
  }
  c.note.textContent = !hist ? "" : h.loading && !(h.bars || []).length ? "載入歷史資料…" : h.error || h.note || "";
  if (ref && c.ref !== ref && !hist) {
    if (c.refLine) c.price.removePriceLine(c.refLine);
    c.refLine = c.price.createPriceLine({price: ref, color: "#9e9e9e", lineStyle: 2, lineWidth: 1, title: "昨收", axisLabelVisible: true});
    c.ref = ref;
  }
  let cv = 0, cpv = 0;
  c.price.setData(kline ? bars.map(b => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]}))
                        : bars.map(b => ({time: b[0], value: b[4]})));
  const avgs = bars.map(b => { cv += b[5]; cpv += b[5] * (b[2] + b[3] + b[4]) / 3; return {time: b[0], value: cv ? cpv / cv : b[4]}; });
  c.avg.setData(hist ? [] : avgs);   // 均價線只在當天的走勢、分K 有意義
  c.bars = bars; c.avgs = Object.fromEntries(avgs.map(a => [a.time, a.value]));
  c.vol.setData(bars.map(b => kline ? {time: b[0], value: b[5], color: b[4] >= b[1] ? "#f2364599" : "#00c85399"} : {time: b[0], value: b[5]}));
  if (bars.length && !hist) {   // 最高、最低標記
    const hi = bars.reduce((a, b) => b[2] > a[2] ? b : a), lo = bars.reduce((a, b) => b[3] < a[3] ? b : a);
    c.markers.setMarkers([{time: hi[0], position: "aboveBar", color: "#f23645", shape: "arrowDown", size: 0.5, text: String(hi[2])},
                          {time: lo[0], position: "belowBar", color: "#29b6f6", shape: "arrowUp", size: 0.5, text: String(lo[3])}]
                          .sort((a, b) => a.time - b.time));
  }
  if (bars.length !== c.n) {
    if (hist && bars.length > 120) c.chart.timeScale().setVisibleLogicalRange({from: bars.length - 120, to: bars.length + 2});   // 歷史先看最近 120 根，可以往左拖
    else if (!hist || !c.n) c.chart.timeScale().fitContent();
    c.n = bars.length;
  }
}

// ===== 錄影 =====
function qRecShow(r){
  const b = $("qRecBtn");
  if (!r) return;
  b.classList.toggle("rec-on", !!r.on);
  // r.start 是「台北時間當作 UTC」的秒數，所以現在時間也要換成同一種
  const el = Math.max(0, Math.floor(Date.now() / 1000 - new Date().getTimezoneOffset() * 60) - r.start);
  b.innerHTML = r.on ? `<span class="rec-dot"></span>錄影中 ${qHM(el, true)}　${r.n} 筆　■ 停止`
                     : `<span class="rec-dot"></span>錄影`;
  b.dataset.on = r.on ? "1" : "";
}
async function qRecToggle(){
  const on = !$("qRecBtn").dataset.on;
  const j = await post("/api/rt/record", {on, codes: qBoardCodes()});
  if (j && j.error) alert(j.error);
  if (on && !(j && j.error)) alert("開始錄影：A、B 兩組共 " + qBoardCodes().filter(Boolean).length + " 檔一起錄");
  if (!on) alert("錄好了，可以到「⏯ 錄影重播」播放");
  qBoardTick();
}

// ===== 錄影重播 =====
async function qReplayList(){
  const list = await api("/api/rt/recordings");
  const nm = r => r.codes.map(c => `${r.names[c] || ""}(${c})`).join("、");
  const when = n => `${n.slice(4, 6)}/${n.slice(6, 8)} ${n.slice(9, 11)}:${n.slice(11, 13)}:${n.slice(13, 15)}`;
  $("qBody").innerHTML = `<div class="qw-bar"><select id="qrSel">${list.map(r => `<option value="${r.name}">${when(r.name)}　${nm(r)}　${(r.size / 1024).toFixed(0)}KB</option>`).join("")}</select>
    <button class="btn" id="qrLoad">載入</button><span class="k">${list.length ? "" : "還沒有錄影：到「🔲 四格看盤」按 ● 錄影"}</span></div>
    <div class="qr-ctl" id="qrCtl" style="display:none">
      <button class="btn" id="qrPlay">▶ 播放</button>
      <select id="qrSpeed"><option value="1">1 倍速</option><option value="5">5 倍速</option><option value="20" selected>20 倍速</option><option value="60">60 倍速</option></select>
      <input type="range" id="qrSlider" min="0" max="1" value="0"><b id="qrTime"></b><span id="qrGrp"></span></div>
    <div class="qb" id="qb"></div>`;
  if (!list.length) return;
  $("qrLoad").onclick = () => qRepLoad($("qrSel").value);
  qRepLoad(list[0].name);
}
async function qRepLoad(name){
  const ev = await api("/api/rt/recording/" + name);
  const meta = ev.find(e => e.k === "meta"), live = ev.filter(e => e.k === "t" || e.k === "b");
  const t0 = meta.t, t1 = live.reduce((m, e) => Math.max(m, e.t), t0 + 1);   // 不用 Math.max(...)：筆數太多會爆
  const slots = [...(meta.slots || meta.codes), ...Array(8).fill("")].slice(0, 8);   // 舊錄影沒有 slots，只有 A 組
  qRep = {name, meta, ev, slots, t0, t1, t: t0, playing: false, speed: 20, grp: 0};
  qRepPanes();
  $("qrCtl").style.display = "";
  const sl = $("qrSlider"); sl.min = t0; sl.max = t1; sl.value = t0;
  sl.oninput = () => { qRep.t = +sl.value; qRepRender(); };
  $("qrPlay").onclick = () => qRep.playing ? qRepPause() : qRepPlay();
  $("qrSpeed").onchange = e => qRep.speed = +e.target.value;
  qRepRender();
}
// 重播時切換 A／B 組：重建四格，時間軸不動
function qRepPanes(){
  const {slots, grp} = qRep;
  qCharts.forEach(c => c && c.chart.remove()); qCharts = [null, null, null, null];
  $("qb").innerHTML = [0, 1, 2, 3].map(i => qPaneHTML(i, slots[grp * 4 + i], true)).join("");
  $("qrGrp").innerHTML = slots.slice(4).some(Boolean) ? qGrpHTML(slots, grp, "qrGrpBtns") : "";
  $("qrGrp").querySelectorAll("[data-g]").forEach(b => b.onclick = () => { qRep.grp = +b.dataset.g; qRepPanes(); qRepRender(); });
}
function qRepPlay(){
  if (qRep.t >= qRep.t1) qRep.t = qRep.t0;
  qRep.playing = true; $("qrPlay").textContent = "⏸ 暫停";
  const step = () => {
    if (!qRep || !qRep.playing) return;
    qRep.t = Math.min(qRep.t1, qRep.t + qRep.speed * 0.25);
    $("qrSlider").value = qRep.t; qRepRender();
    if (qRep.t >= qRep.t1) return qRepPause();
    qRep.timer = setTimeout(step, 250);
  };
  step();
}
function qRepPause(){ if (!qRep) return; qRep.playing = false; clearTimeout(qRep.timer); const b = $("qrPlay"); if (b) b.textContent = "▶ 播放"; }
function qRepRender(){
  const {meta, ev, t} = qRep;
  $("qrTime").textContent = qHM(Math.floor(t), true);
  qRep.slots.slice(qRep.grp * 4, qRep.grp * 4 + 4).forEach((code, i) => {
    if (!code) return qPaneDraw(i, null);
    let ticks = [], best5 = null;
    for (const e of ev) {
      if (e.c !== code) continue;
      if (e.k === "h") ticks = ticks.concat(e.ticks.filter(x => x[0] <= t));
      else if (e.k === "t" && e.t <= t) ticks.push([e.t, e.p, e.q, e.b, e.a, e.ms]);
      else if (e.k === "b" && e.t <= t) best5 = e;
    }
    const by = {};
    for (const x of ticks) {
      const m = x[0] - x[0] % 60, b = by[m];
      if (!b) by[m] = [m, x[1], x[1], x[1], x[1], x[2]];
      else { b[2] = Math.max(b[2], x[1]); b[3] = Math.min(b[3], x[1]); b[4] = x[1]; b[5] += x[2]; }
    }
    const bars = Object.values(by).sort((a, b) => a[0] - b[0]).map(b => [...b.slice(0, 5), b[5]]);
    const [st, cum] = qTickStats(ticks);
    qPaneDraw(i, {code, name: meta.names[code], ref: meta.ref[code], q: null, best5, st,
                  ticks: ticks.slice(-40).map((x, k) => [...x.slice(0, 6), cum[cum.length - Math.min(40, ticks.length) + k]]), bars});
  });
}

$("qGridBtn").onclick = e => { e.stopPropagation(); $("qGridMenu").classList.toggle("open"); };
document.addEventListener("click", e => { if (!e.target.closest("#qGridMenu")) $("qGridMenu").classList.remove("open"); });
$("qCapBtn").onclick = () => $("btnCapital").click();
$("qRecBtn").onclick = qRecToggle;
