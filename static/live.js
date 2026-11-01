// ---------- ⚡ 盤中即時：族群多空、量能激增、周轉率 ----------
// 資料：/api/live（後端 live.py，證交所 MIS 即時報價；抓不到時用 FinMind）
let LIVE = null, liveTimer = null, livePoll = null;
let liveTab = (() => { try { return localStorage.getItem("liveTab") || "bias"; } catch(e) { return "bias"; } })();
let liveGrp = (() => { try { return localStorage.getItem("liveGrp") || "groups"; } catch(e) { return "groups"; } })();
let liveAuto = (() => { try { return localStorage.getItem("liveAuto") === "1"; } catch(e) { return false; } })();
const liveOpen = {};
const LIVE_TABS = [["bias", "🔥 盤中多空"], ["surge", "📈 量能激增"], ["turn", "🔄 周轉率排行"]];
const liveYi = v => v == null ? "–" : `${fmt(v, Math.abs(v) < 10 ? 2 : 1)} 億`;
const liveFlow = v => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, Math.abs(v) < 10 ? 2 : 1)}</span>`;
const liveVr = v => v == null ? "–" : `<span class="${v >= 3 ? "up" : ""}">${fmt(v, 1)}x</span>`;
const livePos = v => v == null ? "–" : `<span class="live-pos" title="收在當日高低區間的位置"><i style="left:${Math.round(v * 100)}%"></i></span>`;

async function liveShow(){
  const r = await api("/api/live").catch(() => null);
  if (r) { LIVE = r.data; liveJob(r.job); }
  liveRender();
  liveSetAuto(liveAuto);
}

function liveJob(j){
  $("liveStatus").innerHTML = j.running ? `⏳ ${j.msg || "更新中…"}` : j.error ? `<span class="up">⚠ ${j.error}</span>` : "";
  $("liveBtn").disabled = j.running;
  if (j.running && !livePoll) livePoll = setInterval(async () => {
    const r = await api("/api/live").catch(() => null);
    if (!r) return;
    liveJob(r.job);
    if (!r.job.running) { clearInterval(livePoll); livePoll = null; LIVE = r.data; liveRender(); }
  }, 2000);
}

async function liveUpdate(){
  await post("/api/live/update");
  liveJob({running: true, msg: "開始…"});
}

function liveSetAuto(on){
  liveAuto = on; try { localStorage.setItem("liveAuto", on ? "1" : "0"); } catch(e) {}
  $("liveAuto").checked = on;
  clearInterval(liveTimer); liveTimer = null;
  if (on) liveTimer = setInterval(() => {
    const now = new Date(), hm = now.toTimeString().slice(0, 5);
    if (window.CUR_PAGE === "live" && now.getDay() >= 1 && now.getDay() <= 5 && hm >= "09:00" && hm <= "13:35" && !livePoll) liveUpdate();
  }, 3 * 60 * 1000);
}

function liveRender(){
  $("liveTabs").innerHTML = LIVE_TABS.map(([k, n]) => `<button class="btn ${k === liveTab ? "" : "ghost"}" data-lt="${k}">${n}</button>`).join("");
  $("liveTabs").querySelectorAll("[data-lt]").forEach(b => b.onclick = () => {
    liveTab = b.dataset.lt; try { localStorage.setItem("liveTab", liveTab); } catch(e) {} liveRender();
  });
  const d = LIVE;
  if (!d) { $("liveBody").innerHTML = `<div class="k" style="padding:20px">還沒有資料，按「⟳ 更新盤中資料」抓一次（約 30 秒）。盤中按上方「更新資料」也會一起更新。</div>`; return; }
  const m = d.market, ix = (n, x) => x ? `<div><span class="k">${n}</span><b>${fmt(x.price, 2)}</b> ${luPct(x.chg)}</div>` : "";
  $("liveSum").innerHTML = `<div class="live-sum">
      ${ix("加權", m.taiex)}${ix("櫃買", m.otc)}
      <div><span class="k">上漲／下跌</span><b class="up">${m.up}</b>／<b class="down">${m.down}</b></div>
      <div><span class="k">普通股成交</span><b>${liveYi(m.amt)}</b></div>
      <div><span class="k">資金淨流（估）</span><b>${liveFlow(m.flow)} 億</b></div>
      <div class="k">資料時間 ${d.time}｜${d.live ? `盤中（約已成交全天量 ${fmt(d.frac * 100, 0)}%）` : "收盤資料"}｜${d.source}</div></div>`;
  const body = liveTab === "surge" ? liveSurge(d) : liveTab === "turn" ? liveTurn(d) : liveBias(d);
  $("liveBody").innerHTML = body;
  $("liveBody").querySelectorAll("[data-c]").forEach(e => e.onclick = ev => {
    ev.stopPropagation(); showPage("macd"); setTimeout(() => select(e.dataset.c), 300);
  });
  $("liveBody").querySelectorAll("[data-g]").forEach(e => e.onclick = () => {
    liveOpen[e.dataset.g] = !liveOpen[e.dataset.g];
    e.nextElementSibling.style.display = liveOpen[e.dataset.g] ? "" : "none";
    e.querySelector(".idea-arrow").textContent = liveOpen[e.dataset.g] ? "▼" : "▶";
  });
  $("liveBody").querySelectorAll("[data-lg]").forEach(b => b.onclick = () => {
    liveGrp = b.dataset.lg; try { localStorage.setItem("liveGrp", liveGrp); } catch(e) {} liveRender();
  });
}

// 個股表格：cols = 額外欄位 [[標題, 取值函式], ...]
function liveStocks(rows, cols){
  if (!rows.length) return `<div class="k" style="padding:8px">目前沒有符合的個股</div>`;
  return `<div class="lu-scroll"><table class="lu-t live-t"><tr><th>代號</th><th>名稱</th><th>價格</th><th>漲跌</th>${cols.map(c => `<th>${c[0]}</th>`).join("")}</tr>
    ${rows.map(r => `<tr data-c="${r.code}"><td>${r.code}</td><td>${r.name}<span class="k">${r.ind || ""}</span></td><td>${fmt(r.price, 2)}</td><td>${luPct(r.chg)}</td>
      ${cols.map(c => `<td>${c[1](r)}</td>`).join("")}</tr>`).join("")}</table></div>`;
}
const LIVE_BASE_COLS = [["量比", r => liveVr(r.vr)], ["成交額", r => liveYi(r.amt)], ["資金淨流(億)", r => liveFlow(r.flow)], ["位置", r => livePos(r.pos)]];

function liveBias(d){
  const gs = liveGrp === "inds" ? d.inds : d.groups;
  const strongG = gs.filter(g => (g.wchg || 0) > 0).slice(0, 6), weakG = gs.filter(g => (g.wchg || 0) < 0).slice(-6).reverse();
  const chip = g => `<div class="live-chip"><b>${g.name}</b> ${luPct(g.wchg)}<span class="k">漲${g.up}／跌${g.down}｜淨流 ${liveFlow(g.flow)} 億</span>
      <span class="k">${((g.wchg || 0) < 0 ? g.lag : g.lead).map(x => `${x.name} ${luPct(x.chg, 1)}`).join("、")}</span></div>`;
  const row = (g, i) => `<div class="live-g" data-g="${liveGrp}:${g.name}"><span class="idea-arrow">${liveOpen[liveGrp + ":" + g.name] ? "▼" : "▶"}</span>
      <span class="live-rank">${i + 1}</span><b>${g.name}</b><span class="k">${g.n} 檔</span>
      <span>加權 ${luPct(g.wchg)}</span><span class="k">平均 ${luPct(g.chg)}</span>
      <span class="k">漲 <b class="up">${g.up}</b>／跌 <b class="down">${g.down}</b></span>
      <span>成交 ${liveYi(g.amt)}</span><span>淨流 ${liveFlow(g.flow)} 億</span><span class="k">量比 ${liveVr(g.vr)}</span></div>
    <div style="display:${liveOpen[liveGrp + ":" + g.name] ? "" : "none"}">${liveStocks(g.members, LIVE_BASE_COLS)}</div>`;
  return `<div class="lu-box"><div class="lu-title">族群多空
        <span class="live-sw"><button class="btn ${liveGrp === "groups" ? "" : "ghost"}" data-lg="groups">自訂族群</button><button class="btn ${liveGrp === "inds" ? "" : "ghost"}" data-lg="inds">產業別</button></span></div>
      <div class="live-cols"><div><div class="k">🔴 強勢族群</div>${strongG.map(chip).join("") || `<div class="k">沒有</div>`}</div>
        <div><div class="k">🟢 弱勢族群</div>${weakG.map(chip).join("") || `<div class="k">沒有</div>`}</div></div>
      <div class="k" style="margin:8px 0 4px">依成交金額加權漲跌排序；點一列展開個股，點個股看 K 線。資金淨流是估計值（成交額 × 收在當日高低區間的位置）。${liveGrp === "groups" ? "族群名單在 data/live_groups.json，可以跟 Claude 說要加哪些。" : ""}</div>
      ${gs.map(row).join("")}</div>
    <div class="lu-row">
      <div class="lu-box grow"><div class="lu-title">🔴 強勢個股（漲幅前 30）</div>${liveStocks(d.strong, [["比大盤", r => luPct(r.rel)], ...LIVE_BASE_COLS])}</div>
      <div class="lu-box grow"><div class="lu-title">🟢 弱勢個股（跌幅前 30）</div>${liveStocks(d.weak, [["比大盤", r => luPct(r.rel)], ...LIVE_BASE_COLS])}</div></div>
    <div class="k">個股強弱只看股價 ≥ ${d.min_price} 元、估計全天量 ≥ 1000 張的股票。</div>`;
}

function liveSurge(d){
  const tags = r => r.tags.map(t => `<span class="ch-tag g">${t}</span>`).join("");
  const cols = [["量比", r => liveVr(r.vr)], ["估全天量", r => `${Math.round(r.est).toLocaleString()} 張`], ["5日均量", r => `${Math.round(r.avg5).toLocaleString()} 張`],
                ["成交額", r => liveYi(r.amt)], ["位置", r => livePos(r.pos)], ["動能分數", r => fmt(r.score, 1)], ["條件", tags]];
  return `<div class="lu-box"><div class="lu-title">📈 爆量上攻</div>
      <div class="k" style="margin-bottom:6px">條件：股價 ≥ ${d.min_price} 元（排除雞蛋水餃股）、估計全天量 ≥ 1000 張、<b>量比 ≥ 2 倍</b>（估計全天量 ÷ 前 5 日均量）、漲幅 ≥ 2%、收在當日區間上方 4 成。<br>
      動能分數 = 漲幅 × 量比（最多算 5 倍）＋ 每符合一個條件加 2 分：突破昨高、創 20 日高、站上均線（5MA &gt; 20MA）、收在高檔（區間上 2 成）、漲停。盤中的估計全天量依台股平常的盤中量分布推算。</div>
      ${liveStocks(d.surge_up, cols)}</div>
    <div class="lu-box"><div class="lu-title">📉 爆量下殺</div>
      <div class="k" style="margin-bottom:6px">量比 ≥ 2 倍、跌幅 ≥ 2%、收在當日區間下方 4 成。</div>
      ${liveStocks(d.surge_dn, cols)}</div>`;
}

function liveTurn(d){
  return `<div class="lu-box"><div class="lu-title">🔄 盤中周轉率前 20</div>
      <div class="k" style="margin-bottom:6px">周轉率 = 目前成交股數 ÷ 發行股數；「估全天」是用目前已成交比例推算到收盤。只算普通股。</div>
      ${liveStocks(d.turnover, [["周轉率", r => `<b>${fmt(r.turn, 2)}%</b>`], ["估全天", r => `${fmt(r.est_turn, 2)}%`], ["成交張數", r => r.lots.toLocaleString()], ...LIVE_BASE_COLS])}</div>`;
}

$("liveBtn").onclick = liveUpdate;
$("liveAuto").onchange = e => liveSetAuto(e.target.checked);
