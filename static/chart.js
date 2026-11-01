// ---------- 共用 K 線圖（MACD 頁、處置歷史頁都用這個）----------
const MAS = [["ma5","MA5","#ff9800"],["ma10","MA10","#2196f3"],["ma20","MA20","#e91e63"],["ma60","MA60","#00bcd4"],["ma120","MA120","#ab47bc"]];
const BB_COLOR = "#c3c8d4";
const MARK_COLOR = {"摸底":"#00c853", "跳空":"#e040fb", "金叉":"#00e676"};
// 指標顯示開關（記在這台電腦的瀏覽器裡，兩頁共用）
const VIS_DEFAULT = {ma5:true, ma10:true, ma20:true, ma60:true, ma120:true, bb:true, strat:false, bt:true, kp:false};
const loadVis = key => Object.assign({}, VIS_DEFAULT, (() => { try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch(e) { return {}; } })());
const GLOBAL_VIS = loadVis("vis");   // MACD 頁、處置歷史頁共用

// 十字線在時間軸上的日期：台灣習慣「26 10/15」（分K 加上時間「26 10/15 09:30」）
function twTime(t){
  let y, m, d, hm = "";
  if (typeof t === "number") {            // 分K：台北時間當作 UTC 的秒數
    const x = new Date(t * 1000);
    y = x.getUTCFullYear(); m = x.getUTCMonth() + 1; d = x.getUTCDate();
    hm = ` ${String(x.getUTCHours()).padStart(2, "0")}:${String(x.getUTCMinutes()).padStart(2, "0")}`;
  } else if (typeof t === "string") {     // "2026-10-15"
    [y, m, d] = t.split("-").map(Number);
  } else if (t && t.year) {               // {year, month, day}
    ({year: y, month: m, day: d} = t);
  } else return String(t);
  return `${String(y).slice(-2)} ${m}/${String(d).padStart(2, "0")}${hm}`;
}
const TW_LOCALE = {locale: "zh-TW", timeFormatter: twTime};

class ChartView {
  static all = [];
  // opts.visKey：這張圖自己記開關（例如情緒頁的加權指數）；opts.visDefault：這張圖預設要打開的指標
  constructor(box, opts = {}){
    this.visKey = opts.visKey || "vis";
    this.vis = opts.visKey ? Object.assign(loadVis(opts.visKey), (() => { try { return localStorage.getItem(opts.visKey) ? {} : (opts.visDefault || {}); } catch(e) { return opts.visDefault || {}; } })()) : GLOBAL_VIS;
    box.innerHTML = `<div class="statbar"></div><div class="legend"></div><div class="macdLegend"></div><div class="sentLegend"></div><div class="mfLegend"></div><div class="tfbar"></div><div class="chart"></div>`;
    this.box = box; this.el = box.querySelector(".chart"); this.sb = box.querySelector(".statbar"); this.off = 0;
    this.lg = box.querySelector(".legend"); this.ml = box.querySelector(".macdLegend"); this.bar = box.querySelector(".tfbar");
    this.sl = box.querySelector(".sentLegend"); this.mfl = box.querySelector(".mfLegend");
    this.chart = null; this.last = null;
    const saved = (() => { try { return JSON.parse(localStorage.getItem("tf") || "{}"); } catch(e) { return {}; } })();
    this.tf = saved.tf || "D";
    this.n = "2m";      // 日K範圍：2m＝載入半年但只顯示近兩個月（每次打開 App 都從這裡開始），0＝半年，-1＝全部
    this.renderBar();
    ChartView.all.push(this);
  }
  // 週期按鈕：日 週 月 60分 5分；日K另外可選範圍
  renderBar(){
    const TFS = [["T","走勢"],["D","日"],["W","週"],["M","月"],["60","60分"],["5","5分"]];
    const RNG = [["2m","2個月"],[0,"半年"],[250,"1年"],[750,"3年"],[-1,"全部"]];
    this.bar.innerHTML = TFS.map(([k,l]) => `<button data-tf="${k}" class="${this.tf===k?"on":""}">${l}</button>`).join("") +
      (this.tf === "D" ? `<span class="sep"></span>` + RNG.map(([k,l]) => `<button data-n="${k}" class="${this.n===k?"on":""}">${l}</button>`).join("") : "");
    this.bar.querySelectorAll("button").forEach(b => b.onclick = () => {
      if (b.dataset.tf) this.tf = b.dataset.tf; else this.n = b.dataset.n === "2m" ? "2m" : +b.dataset.n;
      try { localStorage.setItem("tf", JSON.stringify({tf: this.tf})); } catch(e) {}
      this.renderBar(); this.reload();
    });
  }
  url(code){ return `/api/stock/${code}?tf=${this.tf}&n=${this.tf === "D" && this.n !== "2m" ? this.n : 0}`; }
  // 預設顯示範圍：日K「2個月」只顯示最後約 42 根（可以往左拉看更早），其他就整段顯示
  fit(){
    if (this.onFit) return this.onFit();
    const ts = this.chart.timeScale();
    if (this.tf === "D" && this.n === "2m" && this.nbars > 42) ts.setVisibleLogicalRange({from: this.nbars - 42, to: this.nbars + 1});
    else ts.fitContent();
  }
  async reload(){
    if (!this.last) return;
    const code = this.last.r.code;
    this.lg.innerHTML = `<div class="k">載入${{T:"盤中走勢",D:"日K",W:"週K",M:"月K","60":"60分K","5":"5分K"}[this.tf]}中…</div>`;
    const c = await api(this.url(code));
    if (this.last.r.code === code) this.draw(this.last.r, c, this.last.extra);
  }
  static resizeAll(){ ChartView.all.forEach(v => v.resize()); }
  // 主力買賣超（每天）：同一檔 30 分鐘內共用，兩張圖不會重複抓
  static mf = {};
  static mainforce(code){
    const x = ChartView.mf[code];
    if (x && Date.now() - x.t < 1800e3) return x.p;
    const p = api(`/api/mainforce/${code}`).then(d => d.rows || []).catch(() => []);
    ChartView.mf[code] = {t: Date.now(), p};
    p.then(rows => { if (!rows.length) delete ChartView.mf[code]; });
    return p;
  }
  resize(){
    if (!this.chart || !this.el.clientWidth) return;
    if (this.sb.style.display !== "none" && this.sb.offsetHeight !== this.off) {   // 視窗變窄，統計列換行變高
      this.off = this.sb.offsetHeight;
      this.el.style.top = this.off + "px"; this.lg.style.top = (this.off + 8) + "px"; this.bar.style.top = (this.off + 6) + "px";
    }
    this.chart.resize(this.el.clientWidth, this.el.clientHeight);
    this.fit();   // onFit：自訂預設顯示範圍
    if (this._show) [50, 300, 1000].forEach(ms => setTimeout(() => this._show && this._show(null), ms));   // 視窗大小改變後重新定位 MACD / 情緒窗格的說明文字
  }
  // 窗格高度比例：使用者拖拉過就用記住的，沒有就用預設
  applyPanes(chart, def){
    try {
      const pn = chart.panes(), saved = JSON.parse(localStorage.getItem("paneH_" + pn.length) || "null");
      const f = saved && saved.length === pn.length ? saved : def;
      f.forEach((x, i) => pn[i] && pn[i].setStretchFactor(x));
      this._paneSet = f.join(",");
    } catch(e) {}
  }
  savePanes(chart){
    try {
      const pn = chart.panes(), hs = pn.map(p => p.getHeight()), tot = hs.reduce((a, b) => a + b, 0);
      if (!tot) return;
      const f = hs.map(h => Math.round(h / tot * 1000) / 10);
      const cur = (this._paneSet || "").split(",").map(Number), sum = cur.reduce((a, b) => a + b, 0) || 1;
      if (f.every((x, i) => Math.abs(x - (cur[i] || 0) / sum * 100) < 1.5)) return;   // 沒有拖拉（只是點一下）
      localStorage.setItem("paneH_" + pn.length, JSON.stringify(f)); this._paneSet = f.join(",");
    } catch(e) {}
  }
  // 盤中走勢圖（1 分K）：價格線（在昨收上紅、下綠）、黃色均價線、灰色虛線昨收，下面是每分鐘成交量；盤中每分鐘自動更新
  drawTrend(r, c){
    const el = this.el;
    [this.ml, this.sl, this.mfl].forEach(e => e.innerHTML = "");
    this._show = null; this.onFit = null;
    if (!c.bars.length) { this.chart = null; this.lg.innerHTML = `<div class="err">${c.error || "沒有走勢資料"}</div>`; return; }
    const chart = this.chart = LW.createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout: { background: {color:"#131722"}, textColor:"#d1d4dc", panes:{separatorColor:"#2a2e39", separatorHoverColor:"rgba(41,98,255,.55)", enableResize:true} },
      grid: { vertLines:{color:"#1e222d"}, horzLines:{color:"#1e222d"} },
      rightPriceScale: { borderColor:"#2a2e39" },
      timeScale: { borderColor:"#2a2e39", timeVisible:true, secondsVisible:false, rightOffset: 2 },
      crosshair: { mode: 0 }, localization: TW_LOCALE,
    });
    const ref = c.ref, dev = Math.max(...c.bars.map(b => Math.max(Math.abs(b[2] - ref), Math.abs(b[3] - ref))), ref * 0.01) * 1.08;
    const sym = () => ({priceRange: {minValue: ref - dev, maxValue: ref + dev}});   // 以昨收為中心上下對稱
    const pct = v => v == null ? "–" : `${v >= ref ? "+" : ""}${fmt((v / ref - 1) * 100)}%`;
    const price = chart.addSeries(LW.LineSeries, {lineWidth:2, priceLineVisible:false, lastValueVisible:true, autoscaleInfoProvider: sym,
      priceFormat:{type:"price", precision:2, minMove:0.01}});
    price.setData(c.bars.map(b => ({time:b[0], value:b[4], color: b[4] > ref ? "#f23645" : b[4] < ref ? "#089981" : "#d1d4dc"})));
    const avg = chart.addSeries(LW.LineSeries, {color:"#ffd600", lineWidth:1.5, priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false, autoscaleInfoProvider: sym});
    avg.setData(c.vwap.map(([t, v]) => ({time:t, value:v})));
    price.createPriceLine({price: ref, color:"#9e9e9e", lineStyle:2, lineWidth:1, title:"昨收", axisLabelVisible:true});
    const hi = c.bars.reduce((a, b) => b[2] > a[2] ? b : a), lo = c.bars.reduce((a, b) => b[3] < a[3] ? b : a);
    LW.createSeriesMarkers(price, [
      {time: hi[0], position:"aboveBar", color:"#f23645", shape:"arrowDown", size:0.6, text:`高 ${hi[2]}`},
      {time: lo[0], position:"belowBar", color:"#089981", shape:"arrowUp", size:0.6, text:`低 ${lo[3]}`},
    ].sort((a, b) => a.time - b.time));
    const vol = chart.addSeries(LW.HistogramSeries, {priceFormat:{type:"volume"}, priceLineVisible:false}, 1);
    vol.setData(c.bars.map((b, i) => ({time:b[0], value:b[5], color: b[4] >= (i ? c.bars[i - 1][4] : ref) ? "rgba(242,54,69,.7)" : "rgba(8,153,129,.7)"})));
    this.applyPanes(chart, [75, 25]);
    this.el.onmouseup = () => setTimeout(() => { if (this.chart === chart) this.savePanes(chart); }, 30);
    this.nbars = c.bars.length;
    chart.timeScale().fitContent();
    const byT = Object.fromEntries(c.bars.map((b, i) => [b[0], i])), vw = Object.fromEntries(c.vwap);
    const hm = t => { const x = new Date(t * 1000); return `${String(x.getUTCHours()).padStart(2, "0")}:${String(x.getUTCMinutes()).padStart(2, "0")}`; };
    const last = c.bars[c.bars.length - 1];
    const show = t => {
      const i = byT[t] ?? c.bars.length - 1, b = c.bars[i];
      let cum = 0; for (let k = 0; k <= i; k++) cum += c.bars[k][5];
      this.lg.innerHTML =
        `<div><b>${md(c.day)} 盤中走勢</b>　<span class="k">昨收</span> ${fmt(ref)}　<span class="k">高</span> <span class="up">${fmt(c.high)}</span> ${pct(c.high)}` +
        `　<span class="k">低</span> <span class="down">${fmt(c.low)}</span> ${pct(c.low)}　<span class="k">收</span> <span class="${cls(last[4] - ref)}">${fmt(last[4])} ${pct(last[4])}</span>` +
        (c.day_lots ? `　<span class="k">總量</span> ${c.day_lots.toLocaleString()}張` : "") + `</div>` +
        `<div>${hm(b[0])}　<span class="k">價</span> <b class="${cls(b[4] - ref)}">${fmt(b[4])}</b> ${pct(b[4])}　` +
        `<span style="color:#ffd600">均價 ${fmt(vw[b[0]])}</span> <span class="k">(${b[4] >= vw[b[0]] ? "價在均價上" : "價在均價下"} ${fmt((b[4] / vw[b[0]] - 1) * 100)}%)</span>　` +
        `<span class="k">量</span> ${b[5].toLocaleString()}　<span class="k">累計</span> ${cum.toLocaleString()}張</div>` +
        (c.src === "capital" ? `<div class="k"><span class="src-tag cap">群益逐筆</span> 今天的 1 分K 由群益即時逐筆組成（含開盤／收盤集合競價）</div>`
          : `<div class="k"><span class="src-tag">Yahoo</span> 1 分K 來自 Yahoo（約延遲 20 分鐘；開盤／收盤集合競價的量不在裡面）</div>`);
    };
    show(null);
    chart.subscribeCrosshairMove(pr => show(pr.time));
    // 盤中（09:00~13:35）每 60 秒自動重抓
    const now = new Date(), hmNow = now.getHours() * 100 + now.getMinutes();
    if (now.getDay() >= 1 && now.getDay() <= 5 && hmNow >= 900 && hmNow <= 1335)
      this._tt = setTimeout(() => { if (this.tf === "T" && this.last && this.last.r.code === r.code) this.reload(); }, 60e3);
  }
  redraw(extra){ if (this.last) this.draw(this.last.r, this.last.c, {...this.last.extra, ...extra}); }

  // r：股票摘要（收盤、明日關鍵價…）；c：K 線資料；extra.shades：[[起, 迄, 文字]] 要塗色的期間；extra.trades：回測交易
  saveVis(){ try { localStorage.setItem(this.visKey, JSON.stringify(this.vis)); } catch(e) {} }

  draw(r, c, extra = {}){
    const VIS = this.vis;
    this.last = {r, c, extra};
    if (this.chart) this.chart.remove();
    const el = this.el;
    // 最上面一條：仿權證小哥的統計數據（連漲、均量比、月線斜率、外資連買…），滑鼠移到哪天就顯示哪天
    const st = typeof STATS_ON !== "undefined" && STATS_ON && c.stats && c.stats.by_date && Object.keys(c.stats.by_date).length ? c.stats : null;   // 左邊清單按「📊 數據」才顯示
    const renderStats = t => {
      if (!st) return;
      const ks = st.keys, row = st.by_date[t] || st.by_date[c.bars[c.bars.length - 1][0]];
      if (!row) return;
      const SKIP = ["close", "chg", "lots"];
      this.sb.innerHTML = ks.map(([k, label, unit, nd, desc], i) => {
        if (SKIP.includes(k)) return "";
        const v = row[i];
        const color = /streak|chg|slope|pos|bias|^fi$|^it$|m_chg/.test(k) ? cls(v) : "";
        const txt = v == null ? "–" : `${v > 0 && color ? "+" : ""}${fmt(v, nd)}`;
        return `<span class="st" data-k="${k}" title="${desc}（點一下到「數據篩選」用這個條件找股票）"><span class="k">${label}</span> <b class="${color}">${txt}</b><span class="k">${unit}</span></span>`;
      }).join("");
      this.sb.querySelectorAll(".st").forEach(e => e.onclick = () => window.scrOpenWith && scrOpenWith(e.dataset.k, row[ks.findIndex(x => x[0] === e.dataset.k)]));
    };
    this.sb.style.display = st ? "" : "none";
    if (st) renderStats(null);
    this.off = st ? this.sb.offsetHeight : 0;
    el.style.top = this.off + "px";
    this.lg.style.top = (this.off + 8) + "px";
    this.bar.style.top = (this.off + 6) + "px";
    clearTimeout(this._tt);
    if (c.tf === "T") return this.drawTrend(r, c);
    const chart = this.chart = LW.createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout: { background: {color:"#131722"}, textColor:"#d1d4dc", panes:{separatorColor:"#2a2e39", separatorHoverColor:"rgba(41,98,255,.55)", enableResize:true} },
      grid: { vertLines:{color:"#1e222d"}, horzLines:{color:"#1e222d"} },
      rightPriceScale: { borderColor:"#2a2e39" },
      timeScale: { borderColor:"#2a2e39", rightOffset: 4 },
      crosshair: { mode: 0 },
      localization: TW_LOCALE,
    });
    const dates = c.bars.map(b => b[0]);
    const daily = !c.tf || c.tf === "D";
    const intra = c.tf === "60" || c.tf === "5";
    if (intra) chart.applyOptions({timeScale: {timeVisible: true, secondsVisible: false}});
    const fmtT = t => typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") : t;
    if (c.error && !c.bars.length) { this.lg.innerHTML = `<div class="err">${c.error}</div>`; this.ml.innerHTML = ""; return; }
    // 處置期間塗色（放最底層，只有日K）
    const shades = daily ? (extra.shades || []) : [];
    if (shades.length) {
      const sh = chart.addSeries(LW.HistogramSeries, {priceScaleId:"shade", priceLineVisible:false, lastValueVisible:false,
        color:"rgba(242,54,69,.13)"}, 0);
      chart.priceScale("shade").applyOptions({scaleMargins:{top:0, bottom:0}, visible:false});
      sh.setData(dates.map(t => ({time:t, value: shades.some(([a,b]) => t >= a && t <= b) ? 1 : 0})));
    }
    const candle = chart.addSeries(LW.CandlestickSeries, {
      upColor:"#f23645", downColor:"#089981", borderUpColor:"#f23645", borderDownColor:"#089981",
      wickUpColor:"#f23645", wickDownColor:"#089981", priceLineVisible:false });
    candle.setData(c.bars.map(([t,o,h,l,cl]) => ({time:t, open:o, high:h, low:l, close:cl})));
    const ln = (data, color, w=1, style=0, pane=0) => {
      const s = chart.addSeries(LW.LineSeries, {color, lineWidth:w, lineStyle:style, priceLineVisible:false,
        lastValueVisible:false, crosshairMarkerVisible:false}, pane);
      s.setData(data.map(([t,v]) => ({time:t, value:v}))); return s; };
    const toMap = data => Object.fromEntries(data);

    // 主圖指標（左上角可開關）
    const items = [
      ...MAS.map(([k, label, color]) => ({k, label, color, series:[ln(c[k], color)], vals:[toMap(c[k])]})),
      {k:"bb", label:"BB(20,2)", color:BB_COLOR, series:[ln(c.bbu, BB_COLOR, 2), ln(c.bbd, BB_COLOR, 2)],
       vals:[toMap(c.bbu), toMap(c.bbd)]},
    ];
    items.forEach(it => it.series.forEach(s => s.applyOptions({visible: VIS[it.k]})));

    // MACD 關鍵價預測（隔日偏移）：粉點＝當日摸底價、黃點＝當日金叉價；最右邊多一根畫「明日」
    const KP = ["#e040fb", "#ffd600"];
    const kpData = k => {
      const a = (c.keyp || []).filter(x => x[k] != null).map(x => ({time: x[0], value: x[k]}));
      const tmr = k === 1 ? r.shrink : r.cross;
      if (daily && c.next_day && tmr != null) a.push({time: c.next_day, value: tmr});
      return a;
    };
    const kpS = [1, 2].map(k => {
      const s = chart.addSeries(LW.LineSeries, {color: KP[k - 1], lineVisible:false, pointMarkersVisible:true, pointMarkersRadius:2.5,
        priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false, visible: VIS.kp});
      s.setData(kpData(k)); return s; });
    const kpMap = Object.fromEntries((c.keyp || []).map(x => [x[0], x]));

    // 標記：策略訊號、回測進出場、處置起訖
    const p = S.settings;
    const stratName = `MACD(${p.macd_fast},${p.macd_slow},${p.macd_signal}) 單發狙擊版`;
    const markerApi = LW.createSeriesMarkers(candle, []);
    const inChart = t => t >= dates[0] && t <= dates[dates.length - 1];
    const stratMarks = c.marks.map(([t,txt]) => ({time:t, position:"belowBar", color: MARK_COLOR[txt] || "#00e676", shape:"arrowUp", text:`BUY(${txt})`}));
    const trades = daily ? (extra.trades || []) : [];
    const btMarks = trades.flatMap(t => {
      const sh = t.side === "short", res = `${t.ret > 0 ? "+" : ""}${t.ret}%`;
      if (sh && t.entry_date === t.exit_date)   // 當沖放空：同一根 K 棒只標一個
        return [{time:t.entry_date, position:"aboveBar", color: t.pnl > 0 ? "#ff9800" : "#f23645", shape:"arrowDown", text:`空→補 ${res}`}];
      return [
        sh ? {time:t.entry_date, position:"aboveBar", color:"#ab47bc", shape:"arrowDown", text:`空 ${t.label}`}
           : {time:t.entry_date, position:"belowBar", color:"#2962ff", shape:"arrowUp", text:`買 ${t.label}`},
        ...(t.reason === "持有中" ? [] : [sh
          ? {time:t.exit_date, position:"belowBar", color: t.pnl > 0 ? "#ff9800" : "#f23645", shape:"arrowUp", text:`補 ${t.reason} ${res}`}
          : {time:t.exit_date, position:"aboveBar", color: t.pnl > 0 ? "#ff9800" : "#f23645", shape:"arrowDown", text:`賣 ${t.reason} ${res}`}])];
    });
    // 處置起訖：小箭頭放在 K 線上方，不擋住 K 棒
    const shadeMarks = shades.flatMap(([a, b, txt]) => [
      {time: dates.find(t => t >= a), position:"aboveBar", color:"#ff5252", shape:"arrowDown", size:0.6, text: txt || "處置"},
      // 出關日 = 處置迄日的下一個交易日（還沒出關的就不標）
      {time: dates.find(t => t > b), position:"aboveBar", color:"#9e9e9e", shape:"arrowDown", size:0.6, text:"出關"}]);
    let priceLines = [];
    const applyMarks = () => {
      const m = [...(VIS.strat ? stratMarks : []), ...(VIS.bt ? btMarks : []), ...shadeMarks]
        .filter(x => x.time && inChart(x.time)).sort((a,b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
      markerApi.setMarkers(m);
      priceLines.forEach(pl => candle.removePriceLine(pl)); priceLines = [];
      if (!VIS.kp || !daily) return;
      if (r.shrink != null) priceLines.push(candle.createPriceLine({price:r.shrink, color:"#e040fb", lineStyle:2, lineWidth:1, title:"明日摸底"}));
      if (r.cross != null) priceLines.push(candle.createPriceLine({price:r.cross, color:"#ffd600", lineStyle:2, lineWidth:1, title:"明日金叉"}));
    };
    applyMarks();

    // 成交量 / MACD
    const vol = chart.addSeries(LW.HistogramSeries, {priceFormat:{type:"volume"}, priceLineVisible:false}, 1);
    vol.setData(c.bars.map(([t,o,h,l,cl,v]) => ({time:t, value:v, color: cl >= o ? "rgba(242,54,69,.6)" : "rgba(8,153,129,.6)"})));
    const hist = chart.addSeries(LW.HistogramSeries, {priceLineVisible:false, lastValueVisible:false}, 2);
    hist.setData(c.hist.map(([t,v]) => ({time:t, value:v, color: v >= 0 ? "#f23645" : "#089981"})));
    ln(c.dif, "#ffd600", 1, 0, 2); ln(c.dea, "#2962ff", 1, 0, 2);
    const mv = {dif: toMap(c.dif), dea: toMap(c.dea), hist: toMap(c.hist)};

    // 第 4 窗格：PTT 情緒（柱＝盤中閒聊、黃線＝盤後閒聊/夜盤），跟 K 棒同一條時間軸
    const senti = daily ? extra.sentiment : null;
    const sMap = senti ? Object.fromEntries(senti.map(x => [x.time, x])) : {};
    if (senti) {
      const sc = s => s >= 40 ? "#f23645" : s >= 12 ? "#ff8a80" : s > -12 ? "#9e9e9e" : s > -40 ? "#4db6ac" : "#089981";
      const sh = chart.addSeries(LW.HistogramSeries, {priceLineVisible:false, lastValueVisible:false}, 3);
      sh.setData(senti.filter(x => x.intra != null && inChart(x.time)).map(x => ({time:x.time, value:x.intra, color:sc(x.intra)})));
      const sa = chart.addSeries(LW.LineSeries, {color:"#ffd600", lineWidth:2, pointMarkersVisible:true, pointMarkersRadius:2.5,
        priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false}, 3);
      sa.setData(senti.filter(x => x.after != null && inChart(x.time)).map(x => ({time:x.time, value:x.after})));
    }

    // 最下面窗格：主力買賣超（買超前15大券商買超張數 − 賣超前15大券商賣超張數），柱＝當日（週K/月K＝該週/月加總），黃線＝近 N 根累計
    // 只有個股的日／週／月K 有；分K、指數、期貨不顯示
    const code = r && r.code;
    const mfN = +(p.mf_days || 20);
    const mfPane = senti ? 4 : 3;
    let mfMap = {}, mfState = "off", mfH = null, mfL = null;
    if (!intra && /^\d/.test(code || "") && c.bars.length) {
      mfState = "loading";
      mfH = chart.addSeries(LW.HistogramSeries, {priceLineVisible:false, lastValueVisible:false, priceFormat:{type:"volume"}}, mfPane);
      mfL = chart.addSeries(LW.LineSeries, {color:"#ffd600", lineWidth:1.5, priceScaleId:"mfcum", priceLineVisible:false,
        lastValueVisible:false, crosshairMarkerVisible:false}, mfPane);
      const per = t => {                          // 這天屬於哪一根 K 棒（週K：週六～週五；月K：同月）
        if (daily) return t;
        if (c.tf === "M") return t.slice(0, 7);
        return Math.floor((Date.parse(t + "T00:00:00Z") / 864e5 - 2) / 7);
      };
      const fill = rows => {
        if (this.chart !== chart) return;
        if (!rows.length) {
          mfState = "none"; chart.removeSeries(mfH); chart.removeSeries(mfL);
          this.applyPanes(chart, senti ? [44, 9, 20, 27] : [58, 14, 28]);
          return show(null);
        }
        const agg = new Map();
        rows.forEach(([t, v]) => { const k = per(t); agg.set(k, (agg.get(k) || 0) + v); });
        const ks = [...agg.keys()], vs = ks.map(k => agg.get(k)), cum = {};
        let s = 0;
        vs.forEach((v, i) => { s += v - (i >= mfN ? vs[i - mfN] : 0); cum[ks[i]] = s; });
        mfMap = {};
        c.bars.forEach(([t, o, h, l, cl, vol]) => {
          const k = per(t);
          if (!agg.has(k)) return;
          const v = agg.get(k);
          mfMap[t] = [v, cum[k], vol ? v / vol * 100 : null];
        });
        const ts = dates.filter(t => mfMap[t]);
        mfH.setData(ts.map(t => ({time:t, value:mfMap[t][0], color: mfMap[t][0] >= 0 ? "rgba(242,54,69,.8)" : "rgba(8,153,129,.8)"})));
        mfL.setData(ts.map(t => ({time:t, value:mfMap[t][1]})));
        mfState = "ok"; show(null);
      };
      ChartView.mainforce(code).then(fill);
    }

    this.applyPanes(chart, mfState !== "off" ? (senti ? [40, 8, 17, 20, 15] : [52, 12, 22, 14]) : senti ? [44, 9, 20, 27] : [58, 14, 28]);
    // 窗格之間的分隔線可以上下拖拉調整高度：放開滑鼠後記住比例（同樣窗格數的圖共用），說明文字跟著移位
    this.el.onmouseup = () => setTimeout(() => { if (this.chart === chart) { this.savePanes(chart); this._show && this._show(null); } }, 30);
    this.nbars = c.bars.length;
    chart.timeScale().fitContent();
    setTimeout(() => this.fit(), 0);

    // 左上角圖例：滑鼠移到哪天顯示那天的數值，點名稱可開關
    const byT = Object.fromEntries(c.bars.map((b, i) => [b[0], i]));
    const eye = on => `<span class="eye">${on ? "👁" : "◌"}</span>`;
    const show = t => {
      const future = !!(t && c.next_day && t === c.next_day);   // 滑到最右邊「明日」那一格
      const i = byT[t] ?? c.bars.length - 1, b = c.bars[i]; if (!b) return;
      const kp = kpMap[b[0]], isLast = i === c.bars.length - 1;
      const ok = (v, strict) => v != null && kp && kp[3] != null && (strict ? kp[3] > v : kp[3] >= v) ? `<b class="up"> ✓</b>` : "";
      const kpTxt = (!VIS.kp || !daily) ? "" : (future
        ? ` <b>明日（${md(c.next_day)}）</b> <span style="color:${KP[0]}">摸底 ${fmt(r.shrink)}</span> <span style="color:${KP[1]}">金叉 ${fmt(r.cross)}</span>`
        : ` <span class="k">${md(b[0])}</span> <span style="color:${KP[0]}">摸底 ${fmt(kp && kp[1])}${ok(kp && kp[1])}</span>` +
          ` <span style="color:${KP[1]}">金叉 ${fmt(kp && kp[2])}${ok(kp && kp[2], true)}</span>` +
          (isLast && c.next_day ? `　<span class="k">明日</span> <span style="color:${KP[0]}">${fmt(r.shrink)}</span> <span style="color:${KP[1]}">${fmt(r.cross)}</span>` : ""));
      renderStats(b[0]);
      const cc = b[4] >= b[1] ? "up" : "down";
      const prev = i > 0 ? c.bars[i - 1][4] : null;   // 漲跌、漲跌幅：跟前一天收盤比
      const chg = prev ? b[4] - prev : null, pct = prev ? chg / prev * 100 : null;
      const chgTxt = prev == null ? "" : ` 漲跌<span class="${cls(chg)}">${chg > 0 ? "+" : ""}${fmt(chg)} (${pct > 0 ? "+" : ""}${fmt(pct)}%)</span>`;
      this.lg.innerHTML =
        `<div>${fmtT(b[0])}　<span class="k">${{D:"日K",W:"週K",M:"月K","60":"60分K","5":"5分K"}[c.tf || "D"]}</span>　開<span class="${cc}">${b[1]}</span> 高<span class="${cc}">${b[2]}</span> 低<span class="${cc}">${b[3]}</span> 收<span class="${cc}">${b[4]}</span>${chgTxt} 量${b[5].toLocaleString()}${c.vol_unit || "張"}</div>` +
        (!daily ? "" : `<div class="lg ${VIS.strat?"":"off"}" data-k="strat">${eye(VIS.strat)}<b style="color:#00e676">${stratName}</b></div>`) +
        (!daily ? "" : `<div class="lg ${VIS.kp?"":"off"}" data-k="kp">${eye(VIS.kp)}<b style="color:${KP[0]}">MACD(${p.macd_fast},${p.macd_slow},${p.macd_signal}) 關鍵價預測</b>${kpTxt}</div>`) +
        (trades.length ? `<div class="lg ${VIS.bt?"":"off"}" data-k="bt">${eye(VIS.bt)}<b style="color:#2962ff">回測交易</b> ${trades.length} 筆</div>` : "") +
        `<div class="lgrow">` + items.map(it => `<span class="lg ${VIS[it.k]?"":"off"}" data-k="${it.k}">${eye(VIS[it.k])}<span style="color:${it.color}">${it.label}</span> ` +
          it.vals.map(m => fmt(m[b[0]])).join(" / ") + `</span>`).join("") + `</div>`;
      this.lg.querySelectorAll(".lg").forEach(e => e.onclick = () => {
        const k = e.dataset.k; VIS[k] = !VIS[k]; this.saveVis();
        if (k === "kp") { kpS.forEach(s => s.applyOptions({visible: VIS.kp})); applyMarks(); }
        else if (k === "strat" || k === "bt") applyMarks();
        else items.find(it => it.k === k).series.forEach(s => s.applyOptions({visible: VIS[k]}));
        show(t);
      });
      const m = k => mv[k][b[0]];
      this.ml.innerHTML = `MACD(${p.macd_fast},${p.macd_slow},${p.macd_signal})　<span style="color:#ffd600">DIF ${fmt(m("dif"))}</span>　` +
        `<span style="color:#2962ff">MACD ${fmt(m("dea"))}</span>　<span class="${cls(m("hist"))}">OSC ${fmt(m("hist"))}</span>`;
      try { const pn = chart.panes(); this.ml.style.top = (this.off + pn[0].getHeight() + pn[1].getHeight() + 6) + "px";
            if (senti) this.sl.style.top = (this.off + pn[0].getHeight() + pn[1].getHeight() + pn[2].getHeight() + 8) + "px"; } catch(e) {}
      if (senti) {
        const x = sMap[b[0]], f = v => v == null ? "–" : `${v > 0 ? "+" : ""}${fmt(v, 1)}`;
        const lb = v => v == null ? "" : v <= -40 ? "極度恐慌" : v <= -12 ? "偏空" : v < 12 ? "中性" : v < 40 ? "偏多" : "極度貪婪";
        this.sl.innerHTML = `PTT 情緒 ${md(b[0])}　<span class="${cls(x && x.intra)}">▮ 盤中 ${f(x && x.intra)} ${lb(x && x.intra)}</span>　` +
          `<span style="color:#ffd600">● 盤後（夜盤，看隔天）${f(x && x.after)} ${lb(x && x.after)}</span>`;
      } else this.sl.innerHTML = "";
      if (mfState === "off" || mfState === "none") this.mfl.innerHTML = "";
      else {
        try { const pn = chart.panes(); this.mfl.style.top = (this.off + pn.slice(0, mfPane).reduce((a, x) => a + x.getHeight(), 0) + 6 + mfPane * 1) + "px"; } catch(e) {}
        const unit = daily ? "日" : c.tf === "W" ? "週" : "月";
        const sel = `<select class="mfN" title="累計天數">${[1, 5, 10, 20, 60].map(k => `<option value="${k}" ${k === mfN ? "selected" : ""}>${k}${unit}</option>`).join("")}</select>`;
        const x = mfMap[b[0]], sg = v => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${Math.round(v).toLocaleString()}</span>`;
        this.mfl.innerHTML = `主力買賣超 ${sel}　` + (mfState === "loading" ? `<span class="k">主力資料載入中…</span>` :
          `${md(b[0])}　▮ ${daily ? "當日" : "當" + unit} ${sg(x && x[0])} 張　<span style="color:#ffd600">— ${mfN}${unit}累計 ${sg(x && x[1])} 張</span>　` +
          `佔成交量 ${x && x[2] != null ? `<span class="${cls(x[2])}">${x[2] > 0 ? "+" : ""}${fmt(x[2], 1)}%</span>` : "–"}`);
        this.mfl.querySelector(".mfN").onchange = async e => {
          const n = +e.target.value; S.settings.mf_days = n;
          ChartView.all.forEach(v => v.redraw());
          post("/api/settings", {mf_days: n}).catch(() => {});
        };
      }
    };
    show(null);
    this._show = show;
    chart.subscribeCrosshairMove(pr => show(pr.time));
    // 等窗格真的畫好（每一個畫面更新時）再定位窗格說明文字，前 40 個畫面都檢查一次
    let frames = 0;
    const tick = () => { if (this._show !== show) return; show(null); if (++frames < 40) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }
}
window.addEventListener("resize", () => ChartView.resizeAll());
