// ---------- 選擇權（大分頁）：九宮格切小分頁 ----------
// 即時：右邊 T 字報價（Greeks、各履約價未平倉），左邊小框定價模型 → 之後做
// 歷史資料：期交所逐筆還原的 1 分K（optpage.py）。上面台指期K，滑鼠移到哪一分鐘，右邊 T 字就顯示那一分鐘各履約價的 Call／Put 價格；
//          點一下K線鎖定「時點 A」，再移滑鼠（時點 B）就能比較兩個時間點的價格、漲幾倍。
const OPT_SUBS = [["live", "📡 即時報價", "T 字報價、Greeks、各履約價未平倉，左邊定價模型（貴／便宜）"],
                  ["hist", "🕰 歷史資料", "結算日（或任一天）1 分K／5 分K，對照每個時間點的 Call、Put 價格"],
                  ["lottery", "🎰 結算日樂透回測", "結算日幾點買、買多少錢的價外單，抱到結算平均賺賠"]];
const optLS = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch(e) { return d; } };
const optSave = (k, v) => { try { localStorage.setItem(k, v); } catch(e) {} };
let optSub = (() => { const u = new URLSearchParams(location.search).get("sub"); if (u && OPT_SUBS.some(s => s[0] === u)) return u; return optLS("optSub", "hist"); })();

function optGo(k){
  optSub = k; optSave("optSub", k);
  $("optGridMenu").classList.remove("open");
  optShow();
  if (typeof renderPages === "function") renderPages();
}
function optShow(){
  const x = OPT_SUBS.find(s => s[0] === optSub) || OPT_SUBS[1];
  $("optSubName").textContent = x[1];
  $("optGridMenu").innerHTML = OPT_SUBS.map(([k, n, d]) => `<div class="q-tile ${k === optSub ? "on" : ""}" data-k="${k}"><b>${n}</b><span>${d}</span></div>`).join("");
  $("optGridMenu").querySelectorAll(".q-tile").forEach(t => t.onclick = () => optGo(t.dataset.k));
  ohDispose();
  olStop();
  if (optSub === "hist") ohInit();
  else if (optSub === "lottery") lotInit();
  else olInit();
}
const optVisible = () => window.CUR_PAGE === "options";

// ===== 即時：左邊小框（摘要＋定價模型），右邊 T 字報價 =====
let ol = {key: optLS("olKey", ""), timer: null, j: null, center: null, scrolled: false};
function olStop(){ if (ol.timer) { clearTimeout(ol.timer); ol.timer = null; api("/api/opt/live?stop=1").catch(() => {}); } }
function olInit(){
  $("optBody").innerHTML = `<div class="opt-live">
    <div class="opt-model" id="olModel"></div>
    <div class="opt-chain"><div class="oh-bar"><span class="fu-grp" id="olExps"></span><span class="k" id="olSrc"></span></div>
      <div class="oh-wrap"><table class="fu oh-t ol-t" id="olT"></table></div></div></div>`;
  ol.scrolled = false;
  olTick();
}
async function olTick(){
  clearTimeout(ol.timer);
  if (!optVisible() || optSub !== "live") return;
  let j;
  try { j = await api(`/api/opt/live?key=${encodeURIComponent(ol.key)}${ol.center ? "&center=" + ol.center : ""}`); }
  catch(e) { ol.timer = setTimeout(olTick, 5000); return; }
  if (optSub !== "live" || !$("olT")) return;
  ol.j = j;
  if (j.error) { $("olSrc").textContent = j.error; ol.timer = setTimeout(olTick, 10000); return; }
  if (j.sel && j.sel.key !== ol.key) { ol.key = j.sel.key; optSave("olKey", ol.key); }
  olRender();
  ol.timer = setTimeout(olTick, j.live ? 2000 : 5000);   // 群益剛開還沒連上時先顯示盤後資料，連上後幾秒內就換成即時
}
function olRender(){
  const j = ol.j, md = e => e.slice(4, 6) + "/" + e.slice(6);
  $("olExps").innerHTML = j.exps.slice(0, 8).map(x => `<button class="btn ${x.key === j.sel.key ? "" : "ghost"}" data-k="${x.key}">${x.kind} ${md(x.expire)}</button>`).join("");
  $("olExps").querySelectorAll("[data-k]").forEach(b => b.onclick = () => { ol.key = b.dataset.k; optSave("olKey", ol.key); ol.center = null; ol.scrolled = false; olTick(); });
  const quoted = j.rows.some(r => r.C.z != null || r.C.bid || r.P.z != null || r.P.bid);
  $("olSrc").innerHTML = j.live && !quoted ? `<span class="flat">剛切換到期，群益報價載入中（約 10～15 秒），價平先用台指期估</span>` :
    j.live ? `群益即時（${j.now}，2 秒更新）｜價平 ${qNum(j.atm)}，上下各 15 檔` :
    `<span class="flat">群益沒連線，顯示 ${j.db_date || "–"} 盤後收盤／結算價</span>（${j.cap || ""}）`;
  const n = v => v == null ? "" : qNum(v), f1 = v => v == null ? "" : v.toFixed(1);
  const maxOi = Math.max(1, ...j.rows.flatMap(r => [r.C.oi || 0, r.P.oi || 0]));
  const bar = (v, side) => v ? `<span class="ol-bar ${side}" style="width:${Math.round(v / maxOi * 60)}px"></span>` : "";
  const doi = q => q.oi == null || q.yoi == null || !j.live || q.stale || q.syn ? "" : (d => `<span class="${d > 0 ? "up" : d < 0 ? "down" : "k"}">${d > 0 ? "+" : ""}${n(d)}</span>`)(q.oi - q.yoi);
  const px = q => { if (q.syn) return `<span class="ol-st" title="這一邊太價內，群益 100 檔額度沒訂；用另一邊的即時價＋買賣權平價推算">${n(q.z)}</span>`;
    if (q.stale) return `<span class="ol-st" title="這一邊太價內，群益 100 檔額度沒訂即時，顯示 ${q.stale} 盤後收盤價">${n(q.z)}</span>`;
    const cl = qCls(q.z, q.y); return `<b class="${cl}">${n(q.z)}</b>${q.flag === "under" ? `<span class="ol-flag under" title="買價低於內含價值">撿</span>` : q.flag === "rich" ? `<span class="ol-flag rich" title="剩沒多久，價外卻還這麼貴">貴</span>` : ""}`; };
  const gg = v => v == null ? "" : (v / 100).toFixed(2), tt = v => v == null ? "" : n(Math.abs(v));
  $("olT").innerHTML = `<thead><tr><th>未平倉</th><th>未平倉<br>增減</th><th title="市場預期的年化波動">隱含<br>波動率%</th><th title="Delta：台指漲 1 點，這檔漲幾點（Put 是負的＝會跌）">指數漲1點<br>這檔漲幾點</th><th title="Gamma：台指漲 100 點後，上一欄會再增加多少">漲100點後<br>上一欄加多少</th><th title="Theta：什麼都沒變，一天時間價值少掉幾點">每天時間<br>價值減少</th><th>成交量</th><th>買</th><th>賣</th><th>成交</th>
      <th class="oh-kh">履約價</th><th>成交</th><th>買</th><th>賣</th><th>成交量</th><th>每天時間<br>價值減少</th><th>漲100點後<br>上一欄加多少</th><th>指數漲1點<br>這檔漲幾點</th><th>隱含<br>波動率%</th><th>未平倉<br>增減</th><th>未平倉</th></tr></thead><tbody>` +
    j.rows.map(r => { const c = r.C, p = r.P, itmC = j.F && r.k < j.F, itmP = j.F && r.k > j.F;
      return `<tr class="${r.k === j.atm ? "oh-atm" : ""}" data-k="${r.k}">
        <td class="ol-oi">${bar(c.oi, "c")}<span>${n(c.oi)}</span></td><td>${doi(c)}</td><td>${f1(c.iv)}</td><td>${c.d == null ? "" : c.d.toFixed(2)}</td><td>${gg(c.g)}</td><td>${tt(c.th)}</td>
        <td class="k">${n(c.v)}</td><td class="${itmC ? "oh-itm" : ""}">${n(c.bid)}</td><td class="${itmC ? "oh-itm" : ""}">${n(c.ask)}</td><td class="${itmC ? "oh-itm" : ""}">${px(c)}</td>
        <td class="oh-k">${r.k}</td>
        <td class="${itmP ? "oh-itm" : ""}">${px(p)}</td><td class="${itmP ? "oh-itm" : ""}">${n(p.bid)}</td><td class="${itmP ? "oh-itm" : ""}">${n(p.ask)}</td><td class="k">${n(p.v)}</td>
        <td>${tt(p.th)}</td><td>${gg(p.g)}</td><td>${p.d == null ? "" : p.d.toFixed(2)}</td><td>${f1(p.iv)}</td><td>${doi(p)}</td><td class="ol-oi">${bar(p.oi, "p")}<span>${n(p.oi)}</span></td></tr>`; }).join("") + "</tbody>";
  $("olSrc").innerHTML += olVolBar(j);
  if (ol.center) { $("olSrc").innerHTML += `　<button class="btn ghost" id="olReset">回到價平（現在以 ${ol.center} 為中心）</button>`;
    $("olReset").onclick = () => { ol.center = null; ol.scrolled = false; olTick(); }; }
  if (j.model && j.model.settle) $("olSrc").innerHTML = `<b class="ol-settle-tag">⚠ 結算日模式：今天日盤 13:30 結算</b>　` + $("olSrc").innerHTML;
  $("olT").querySelectorAll("tr[data-k]").forEach(tr => tr.ondblclick = () => { ol.center = +tr.dataset.k; ol.scrolled = false; olTick(); });
  if (!ol.scrolled) { const r = $("olT").querySelector("tr.oh-atm"); if (r) { r.scrollIntoView({block: "center"}); ol.scrolled = true; } }
  // 左邊摘要
  const top = side => j.rows.filter(r => r[side].oi).sort((a, b) => b[side].oi - a[side].oi).slice(0, 3);
  const sum = side => j.rows.reduce((s, r) => s + (r[side].oi || 0), 0);
  const pcr = sum("C") ? sum("P") / sum("C") : null;
  $("olModel").innerHTML = `<h3>${j.sel.kind} ${md(j.sel.expire)} 到期</h3>
    <div class="ol-kv"><span>剩餘時間</span><b>${j.T_days} 天</b></div>
    <div class="ol-kv"><span>價平履約價</span><b class="flat">${n(j.atm)}</b></div>
    <div class="ol-kv"><span>選擇權反推的指數價位</span><b>${n(j.F)}</b></div>
    <div class="ol-kv"><span>台指期近月</span><b>${n(j.tx)}</b></div>
    <div class="ol-kv"><span title="${j.iv_basis === "交易時間" ? "結算日盤中改用交易時間（只算還剩幾分鐘的日盤）反推，才能跟實際波動直接比" : "用日曆時間（到期日 13:30）反推"}">價平隱含波動率${j.iv_basis === "交易時間" ? "（交易時間）" : ""}</span><b>${j.atm_iv == null ? "–" : j.atm_iv + "%"}</b></div>
${olRV(j)}
    <div class="ol-kv"><span>到結算前的正常波動幅度</span><b>${j.move == null ? "–" : "上下 " + n(j.move) + " 點"}</b></div>
    <div class="ol-kv k"><span>約 68% 機率落在</span><span>${j.move == null ? "–" : n(Math.round(j.F - j.move)) + " ～ " + n(Math.round(j.F + j.move))}</span></div>
    <div class="ol-kv"><span>Call 未平倉最多</span><span class="up">${top("C").map(r => r.k).join("、") || "–"}</span></div>
    <div class="ol-kv"><span>Put 未平倉最多</span><span class="down">${top("P").map(r => r.k).join("、") || "–"}</span></div>
    <div class="ol-kv"><span>賣權 ÷ 買權 未平倉（表內）</span><b>${pcr == null ? "–" : pcr.toFixed(2)}</b></div>
    <div class="ol-note k">右邊表格的欄位：「指數漲1點這檔漲幾點」就是 Delta（Put 是負的，代表指數漲它會跌）；「漲100點後上一欄加多少」是 Gamma；「每天時間價值減少」是 Theta，指數不動的話一天會少掉這麼多點；「隱含波動率」是從市價反推出來、市場預期的波動，越高代表越貴。滑鼠停在欄位標題上也有說明。雙擊表格某一列可以改成以那個履約價為中心。</div>
` + olModel(j);
  const sb = $("olModel").querySelector(".ol-settle"); if (sb) $("olModel").prepend(sb);   // 結算日提醒放最上面
}
// 報價表上方：價平隱波 vs 今天盤中實際波動，一眼看出選擇權貴還便宜
function olVolBar(j){
  const rv = (j.model || {}).rv || {}, t = rv.today, settle = j.iv_basis === "交易時間";
  const iv = j.atm_iv_tt ?? j.atm_iv;
  // 結算日盤中：跟今天盤中比；平常：跟近 20 天（日K，含過夜跳空）比，今天盤中只當參考
  const real = settle ? (t && t.rv ? t.rv : null) : rv.rv20, realName = settle ? "今天盤中實際波動" : "近 20 天實際波動";
  const r = iv && real ? iv / real : null;
  const view = r == null ? "" : r > 1.2 ? "偏貴" : r < 0.85 ? "偏便宜" : "正常";
  const cl = r == null ? "flat" : r > 1.2 ? "up" : r < 0.85 ? "down" : "flat";
  const tip = "實際波動：台指期近月的 K 棒漲跌幅標準差，換算成一年。盤中用今天 5 分K（× √(252×60)），近 20 天用日K（× √252）。" +
    "隱波（交易時間）：把價平隱波從日曆時間換成剩幾個交易日 ÷ 252，晚上、週末不算，才能跟實際波動比。" +
    "隱波 ÷ 實際 < 0.85 偏便宜、> 1.2 偏貴。";
  return `<span class="ol-volbar" title="${tip}">　｜　價平隱波 <b>${iv == null ? "–" : iv + "%"}</b>${!settle && j.atm_iv != null ? `<span class="k">（日曆時間 ${j.atm_iv}%）</span>` : ""}
    　${realName} <b>${real == null ? "–" : real + "%"}</b>
    　隱波÷實際 <b class="${cl}">${r == null ? "–" : r.toFixed(2) + " " + view}</b>
    　<span class="k">今天盤中實際 ${t && t.rv ? t.rv + "%（" + t.sess + " " + t.n + " 根 5 分K，高低差 " + qNum(Math.round(t.hi - t.lo)) + " 點）" : "–（要連群益）"}</span></span>`;
}
// 實際波動（RV）：台指期真的動了多少，年化 %，跟隱含波動率同一把尺
function olRV(j){
  const rv = (j.model || {}).rv; if (!rv) return "";
  const t = rv.today, n = v => v == null ? "–" : v + "%";
  const useT = j.iv_basis === "交易時間" && t && t.rv;     // 結算日盤中：跟今天比；平常：跟近 20 天比（都含過夜）
  const ivx = j.atm_iv_tt ?? j.atm_iv, ref = useT ? t.rv : rv.rv20, r = ivx && ref ? ivx / ref : null;
  const cl = r == null ? "" : r > 1.2 ? "up" : r < 0.85 ? "down" : "flat";
  return `<div class="ol-kv"><span title="台指期近月今天的 5 分K 收盤，每根漲跌幅的標準差 × √(一年 252 天 × 每天 60 根)。只看今天真的動了多少">今天盤中實際波動${t ? "（" + t.sess + " " + t.n + " 根 5 分K）" : ""}</span><b>${t ? n(t.rv) : "–（要連群益）"}</b></div>
    <div class="ol-kv"><span title="台指期近月每天收盤漲跌幅的標準差 × √252">近 5 天 ／ 近 20 天實際波動</span><b>${n(rv.rv5)} ／ ${n(rv.rv20)}</b></div>
    ${rv.min_hist ? `<div class="ol-kv k"><span title="本機存的過去日盤 1 分K（data/opt_min），結算日模式的合理價就是用這個模擬">過去日盤平均實際波動（1 分K）</span><span>${n(rv.min_hist)}</span></div>` : ""}
    <div class="ol-kv"><span title="大於 1.2 代表選擇權比台指期真實的波動貴（偏貴）；小於 0.85 代表便宜">隱含波動率 ÷ ${useT ? "今天" : "近 20 天"}實際波動</span><b class="${cl}">${r == null ? "–" : r.toFixed(2)}</b></div>`;
}
// 定價模型小框：價平 IV 貴不貴 ＋ 價外各履約價 市價 vs 合理價
function olModel(j){
  const m = j.model;
  if (!m || m.error) return `<h3 style="margin-top:12px">定價模型</h3><p class="k">${m ? m.error : "算不出來（沒有報價）"}</p>`;
  const g = m.judge || {}, n = v => v == null ? "–" : qNum(v);
  const vc = g.view === "偏貴" ? "up" : g.view === "偏便宜" ? "down" : "flat";
  // 市價 vs 合理價：Call、Put 分開兩張表，列出表格裡全部履約價（價內、價外都有）
  const side = cp => { const rs = j.rows.filter(r => r[cp].mkt && r[cp].fair != null);
    return `<div class="ol-fair-s"><div class="ol-fair-h ${cp === "C" ? "up" : "down"}">${cp === "C" ? "買權 Call" : "賣權 Put"}（${rs.length} 檔）</div>
    <table class="ol-fair"><thead><tr><th>履約價</th><th>價內／價外</th><th>市價</th><th>合理(近況)</th><th>合理(長期)</th><th>市價÷合理</th></tr></thead><tbody>${rs.map(r => {
      const q = r[cp], d = cp === "C" ? j.F - r.k : r.k - j.F, itm = d > 0, ratio = q.fair > 0.05 ? q.mkt / q.fair : null;
      const cl = ratio == null ? "" : ratio >= 1.3 ? "up" : ratio <= 0.8 ? "down" : "";
      return `<tr class="${r.k === j.atm ? "ol-atm" : ""} ${itm ? "ol-itm" : ""}"><td>${r.k}</td><td class="k">${Math.abs(d) < 25 ? "價平" : (itm ? "價內 " : "價外 ") + Math.round(Math.abs(d))}</td>
        <td class="${q.stale || q.syn ? "ol-st" : ""}" title="${q.syn ? "用買賣權平價推算" : q.stale ? q.stale + " 盤後價（非即時）" : ""}">${n(q.mkt)}</td><td>${n(q.fair)}</td><td class="k">${n(q.fair_l)}</td><td class="${cl}">${ratio == null ? "–" : ratio.toFixed(2) + " 倍"}</td></tr>`; }).join("")}</tbody></table></div>`; };
  const st = m.settle, nn = v => v == null ? "–" : qNum(v);
  const settle = !st ? "" : `<div class="ol-settle"><b>⚠ 結算日模式（今天日盤 13:30 結算）</b>
      <div>結算價 = 13:00～13:30 加權指數平均。離 13:00 還有 ${st.to_13} 分鐘，平均區間剩 ${st.win_left} 分鐘；合理價改用過去日盤每分鐘的漲跌，模擬到結算還剩的波動（約上下 ${nn(st.sd)} 點）。</div>
      <div style="margin-top:6px"><b>低於內含價值（買進等結算幾乎穩賺）</b>：${st.under.length ? st.under.map(x => `${x.cp === "C" ? "買權" : "賣權"} ${x.k}：賣價 ${x.buy}、內含 ${x.intr}，多 ${x.gain} 點`).join("；") : "目前沒有"}</div>
      <div style="margin-top:4px"><b>價外卻還很貴（通常是有人在賣）</b>：${st.rich.length ? st.rich.map(x => `${x.cp === "C" ? "買權" : "賣權"} ${x.k}（價外 ${x.otm} 點）市價 ${x.mkt}、合理 ${x.fair}`).join("；") : "目前沒有"}</div>
      <div class="k" style="margin-top:4px">表格裡「撿」= 低於內含價值、「貴」= 價外偏貴。注意：成交量少的履約價買賣價差大，成交價可能是好幾分鐘前的，下單前看買賣價。</div></div>`;
  const gs = g.settle;
  const head = gs ? `<div class="ol-kv"><span>價平隱含波動率（交易時間） ／ ${gs.ref_src}實際波動</span><b>${j.atm_iv ?? "–"}% ／ ${n(gs.ref)}%</b></div>
    <div class="ol-kv"><span>隱含波動率 ÷ 實際波動</span><b>${gs.ratio ?? "–"}</b><span class="k">（大於 1.2 偏貴、小於 0.85 偏便宜）</span></div>
    <div class="ol-kv k"><span>參考：近 20 天實際波動</span><span>${n(g.rv20)}%</span></div>` : `<div class="ol-kv"><span>價平隱含波動率 ／ 近 20 天實際波動</span><b>${j.atm_iv ?? "–"}% ／ ${n(g.rv20)}%</b></div>`;
  return settle + `<h3 style="margin-top:12px">定價模型${st ? "（結算日：剩幾分鐘算）" : ""}　<span class="${vc}">${g.view || ""}</span></h3>
    ${head}
    ${gs ? "" : `<div class="ol-kv"><span>隱含波動率 ÷ 實際波動</span><b>${g.ratio ?? "–"}</b><span class="k">（過去同樣天數平均 ${g.ratio_avg ?? "–"}）</span></div>
    <div class="ol-kv"><span>剩 ${g.bucket || ""}到期的歷史隱含波動率</span><span>平均 ${g.avg ?? "–"}%，現在高過 ${g.pct ?? "–"}% 的日子</span></div>`}
    <div class="ol-kv k"><span>剩餘交易日（收盤到收盤）</span><span>${m.h} 天</span></div>
    <div class="ol-fair2">${side("C")}${side("P")}</div>
    <div class="ol-note k">合理價 = 用加權指數 2015 年以來每天的漲跌（保留暴漲暴跌的肥尾）模擬到結算的指數，算出每個履約價平均能拿回多少。
      「近況」把波動放大縮小到最近 20 天的實際波動（${n(g.rv20)}%），「長期」用 2015 年以來的平均波動（${m.long_vol}%）。
      市價÷合理 大於 1.3 算偏貴（紅）、小於 0.8 算便宜（綠）。這是統計上的平均值，買方大多數時候會歸零，只有少數幾次大賺撐起平均。</div>`;
}

// ===== 🎰 結算日樂透回測 =====
async function lotInit(){
  $("optBody").innerHTML = `<div class="lot-wrap" id="lotBody"><span class="k">回測中…（第一次要整理逐筆，約 10 秒）</span></div>`;
  let j;
  try { j = await api("/api/opt/lottery"); } catch(e) { $("lotBody").textContent = "讀取失敗"; return; }
  if (optSub !== "lottery") return;
  if (j.error) { $("lotBody").textContent = j.error; return; }
  const pc = v => v == null ? "–" : v.toFixed(1) + "%", rt = v => v == null ? "–" : `<b class="${v >= 1 ? "up" : "down"}">${v.toFixed(2)}</b>`;
  const times = [...new Set(j.by_time_tier.map(r => r.time))], tiers = [...new Set(j.by_time_tier.map(r => r.tier))];
  const cell = (t, tr) => { const r = j.by_time_tier.find(x => x.time === t && x.tier === tr);
    return r ? `<td title="${r.n} 筆、${r.days} 次結算｜平均成本 ${r.cost}、平均拿回 ${r.pay}｜賺錢 ${pc(r.win)}、翻 10 倍以上 ${pc(r.x10)}｜最好 ${r.best} 倍">${rt(r.ret)}<span class="k"> ${pc(r.win)}</span></td>` : `<td class="k">–</td>`; };
  const pv = j.prev_close;
  $("lotBody").innerHTML = `
    <div class="lu-box"><div class="lu-title">結算日當天各時間買價外單、抱到結算：每投入 1 點平均拿回幾點（後面是賺錢機率）</div>
      <div class="k" style="margin-bottom:6px">樣本：${j.days.length} 次結算（${j.days[0] || ""} ～ ${j.days[j.days.length - 1] || ""}，週三、週五、月選），${j.n_trades.toLocaleString()} 筆（每個時間點、每個履約價算一筆）。價格 = 那個時間點前 10 分鐘內最後一筆成交；價平用買賣權平價反推。滑鼠停在格子上看細節。</div>
      <table class="lu-t lot-t"><thead><tr><th>買進時間 ＼ 權利金</th>${tiers.map(t => `<th>${t}</th>`).join("")}<th>全部</th></tr></thead><tbody>
      ${times.map(t => { const a = j.by_time.find(x => x.time === t); return `<tr><td>${t}</td>${tiers.map(tr => cell(t, tr)).join("")}<td>${a ? rt(a.ret) : "–"}</td></tr>`; }).join("")}</tbody></table>
      <div class="k" style="margin-top:6px">1.00 = 打平；大於 1 代表這幾次結算平均是賺的。樣本只有 ${j.days.length} 次，一兩次大行情就會左右結果，要等資料累積多一點才準。</div></div>
    ${pv ? `<div class="lu-box"><div class="lu-title">結算前一天收盤買、抱到結算（資料庫每日收盤，${pv.from} ～ ${pv.to}，${pv.n_exp} 次結算）</div>
      <table class="lu-t"><thead><tr><th>權利金</th><th>Call／Put</th><th>筆數</th><th>平均成本</th><th>平均拿回</th><th>每 1 點拿回</th><th>賺錢機率</th><th>翻 10 倍以上</th></tr></thead><tbody>
      ${pv.rows.map(r => `<tr><td>${r.tier}</td><td class="${r.cp === "C" ? "up" : "down"}">${r.cp === "C" ? "Call" : "Put"}</td><td>${r.n}</td><td>${r.cost}</td><td>${r.pay}</td><td>${rt(r.ret)}</td><td>${pc(r.win)}</td><td>${pc(r.x10)}</td></tr>`).join("")}</tbody></table>
      <div class="k" style="margin-top:6px">這段期間台股大多頭，Call 本來就比較容易賺，Put 比較吃虧；不代表之後也一樣。</div></div>` : ""}
    <div class="lu-box"><div class="lu-title">每一次結算：最後結算價、開盤時的價平、當天最賺的一筆價外單</div>
      <table class="lu-t"><thead><tr><th>結算日</th><th>合約</th><th>08:50 價平</th><th>最後結算價</th><th>最賺的一筆</th></tr></thead><tbody>
      ${j.detail.map(r => `<tr><td>${r.date}</td><td>${r.contract}</td><td>${r.open_F == null ? "–" : r.open_F.toLocaleString()}</td><td>${r.fsp.toLocaleString()}</td><td>${r.best}</td></tr>`).join("")}</tbody></table></div>`;
}
$("optGridBtn").onclick = e => { e.stopPropagation(); $("optGridMenu").classList.toggle("open"); };
document.addEventListener("click", e => { if (!e.target.closest("#optGridMenu")) $("optGridMenu").classList.remove("open"); });

// ===== 歷史資料 =====
let oh = {days: null, date: optLS("ohDate", ""), contract: "", tf: optLS("ohTf", "1"), night: optLS("ohNight", "0") === "1",
          j: null, A: null, B: null, k: null, charts: null};
const ohHM = t => qHM(t);
const ohN = v => v == null ? "–" : v >= 100 ? Math.round(v).toLocaleString() : (+v.toFixed(1)).toString();

// 期交所已經沒有逐筆的日子台指期只有 5 分K → 全部用 5 分K
const ohTfN = () => Math.max(+oh.tf, oh.j ? +oh.j.fut_tf || 1 : 1);
function ohDispose(){ if (oh.charts) { oh.charts.fut.remove(); oh.charts.opt.remove(); oh.charts = null; } }

async function ohInit(){
  $("optBody").innerHTML = `<div class="oh-bar">
      <label class="k">日期 <select id="ohDate"></select></label>
      <label class="k">到期 <select id="ohCon"></select></label>
      <span class="fu-grp" id="ohTf"><button class="btn" data-t="1">1 分K</button><button class="btn ghost" data-t="5">5 分K</button></span>
      <label class="k"><input type="checkbox" id="ohNight"> 含前一晚夜盤</label>
      <button class="btn ghost" id="ohClrA" title="取消鎖定的時點 A">清除時點 A</button>
      <span class="k" id="ohInfo"></span></div>
    <div class="oh-main">
      <div class="oh-left"><div class="oh-cap k" id="ohCapF"></div><div class="oh-chart" id="ohFut"></div>
        <div class="oh-cap k" id="ohCapO">點右邊 T 字的履約價，這裡畫那個履約價的 Call（紅）、Put（綠）走勢</div><div class="oh-chart oh-chart2" id="ohOpt"></div></div>
      <div class="oh-right"><div class="oh-when" id="ohWhen"></div><div class="oh-wrap"><table class="fu oh-t" id="ohT"></table></div></div>
    </div>`;
  $("ohNight").checked = oh.night;
  $("ohNight").onchange = () => { oh.night = $("ohNight").checked; optSave("ohNight", oh.night ? "1" : "0"); ohLoad(); };
  $("ohClrA").onclick = () => { oh.A = null; ohMark(); ohTable(); };
  ohTfBtns();
  if (!oh.days) {
    $("ohInfo").textContent = "載入日期…";
    try { oh.days = await api("/api/opt/hist/days"); } catch(e) { $("ohInfo").textContent = "讀取失敗"; return; }
  }
  const ds = oh.days.days;
  if (!ds.some(d => d.date === oh.date)) oh.date = (ds.find(d => d.settle.length) || ds[0] || {}).date;
  $("ohDate").innerHTML = ds.map(d => `<option value="${d.date}" ${d.date === oh.date ? "selected" : ""}>${d.date}（${d.wd}）${d.settle.length ? "★ " + d.settle.join("、") + " 結算" : ""}${d.local ? "" : "　期交所下載"}</option>`).join("");
  $("ohDate").onchange = () => { oh.date = $("ohDate").value; oh.contract = ""; oh.A = null; oh.k = null; optSave("ohDate", oh.date); ohLoad(); };
  $("ohInfo").textContent = `資料最早到 ${oh.days.oldest_local || "–"}（期交所只保留最近 30 個交易日的逐筆，之後每天自動存）`;
  ohLoad();
}
function ohTfBtns(){
  $("ohTf").querySelectorAll("[data-t]").forEach(b => {
    b.className = "btn" + (b.dataset.t === oh.tf ? "" : " ghost");
    b.onclick = () => { oh.tf = b.dataset.t; optSave("ohTf", oh.tf); ohTfBtns(); ohDraw(); };
  });
}
async function ohLoad(){
  $("ohWhen").innerHTML = `<span class="k">載入 ${oh.date} 逐筆…（第一次要下載、整理，約 10~20 秒）</span>`;
  $("ohT").innerHTML = "";
  let j;
  try { j = await api(`/api/opt/hist?date=${oh.date}&contract=${encodeURIComponent(oh.contract)}&night=${oh.night ? 1 : 0}`); }
  catch(e) { $("ohWhen").textContent = "讀取失敗"; return; }
  if (j.error) { $("ohWhen").innerHTML = `<span class="down">${j.error}</span>`; return; }
  oh.j = j; oh.contract = j.contract; oh.scrolled = false; oh.B = null;
  if (oh.k != null && !j.strikes.includes(oh.k)) oh.k = null;
  $("ohCon").innerHTML = j.contracts.map(c => `<option value="${c.c}" ${c.c === j.contract ? "selected" : ""}>${c.c}（${c.kind}，${c.expire ? c.expire.slice(4, 6) + "/" + c.expire.slice(6) : "–"} 到期${c.today ? "，今天結算" : ""}）量 ${c.v.toLocaleString()}</option>`).join("");
  $("ohCon").onchange = () => { oh.contract = $("ohCon").value; oh.k = null; ohLoad(); };
  $("ohCapF").textContent = `台指期 ${j.fut_contract || ""} ${j.fut_tf === "5" ? "（這天期交所已經沒有逐筆，只有 5 分K）" : ""}｜滑鼠移動 = 時點 B，點一下 = 鎖定時點 A`;
  ohDraw();
}

// 1 分K → n 分K（時間標在每根開始；日盤 08:45、夜盤 15:00 都是 5 的倍數，直接取整即可）
function ohAgg(bars, n){
  if (n === 1) return bars;
  const out = [];
  for (const b of bars) {
    const t = b[0] - b[0] % (n * 60), o = out[out.length - 1];
    if (o && o[0] === t) { o[2] = Math.max(o[2], b[2]); o[3] = Math.min(o[3], b[3]); o[4] = b[4]; o[5] += b[5]; }
    else out.push([t, b[1], b[2], b[3], b[4], b[5]]);
  }
  return out;
}
// 時間 t 的價平：10 分鐘內 Call、Put 都有成交的履約價，用買賣權平價（K + C − P）反推指數，取最接近的 3 檔中位數
function ohAtm(t){
  const j = oh.j, n = ohTfN(); if (!j) return null;
  const xs = [];
  for (const s of j.strikes) {
    const c = ohAt(j.C[s], t, n), p = ohAt(j.P[s], t, n);
    if (c && p && t - c.t <= 600 && t - p.t <= 600) xs.push([Math.abs(c.p - p.p), s + c.p - p.p]);
  }
  if (!xs.length) return null;
  xs.sort((a, b) => a[0] - b[0]);
  const v = xs.slice(0, 3).map(x => x[1]).sort((a, b) => a - b), F = v[Math.floor(v.length / 2)];
  const k = j.strikes.reduce((a, s) => Math.abs(s - F) < Math.abs(a - F) ? s : a, j.strikes[0]);
  const c = ohAt(j.C[k], t, n), p = ohAt(j.P[k], t, n);
  return {F, k, c: c && c.p, p: p && p.p};
}
// 某個履約價在時間 t（含那一分鐘）之前的最後成交、累計量
function ohAt(bars, t, n){
  if (!bars) return null;
  let last = null, vol = 0;
  for (const b of bars) { if (b[0] >= t + n * 60) break; last = b; vol += b[5]; }
  return last ? {p: last[4], t: last[0], v: vol} : null;
}

function ohDraw(){
  const j = oh.j; if (!j) return;
  const n = ohTfN(), fut = ohAgg(j.fut, n);
  ohDispose();
  const mk = (el, h2) => LW.createChart(el, {width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: "#000"}, textColor: "#d1d4dc", fontSize: 10, attributionLogo: false, panes: {separatorColor: "#2a2e39"}},
    grid: {vertLines: {color: "#1e222d"}, horzLines: {color: "#1e222d"}}, rightPriceScale: {borderColor: "#2a2e39", minimumWidth: 70},
    timeScale: {borderColor: "#2a2e39", timeVisible: true, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true}, crosshair: {mode: 0},
    localization: typeof TW_LOCALE !== "undefined" ? TW_LOCALE : undefined});
  const cf = mk($("ohFut")), co = mk($("ohOpt"));
  const k = cf.addSeries(LW.CandlestickSeries, {upColor: "#f23645", downColor: "#00c853", borderUpColor: "#f23645", borderDownColor: "#00c853",
    wickUpColor: "#f23645", wickDownColor: "#00c853", priceLineVisible: false});
  k.setData(fut.map(b => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]})));
  const v = cf.addSeries(LW.HistogramSeries, {priceFormat: {type: "volume"}, priceLineVisible: false, lastValueVisible: false}, 1);
  v.setData(fut.map(b => ({time: b[0], value: b[5], color: b[4] >= b[1] ? "#f2364599" : "#00c85399"})));
  try { cf.panes()[0].setStretchFactor(80); cf.panes()[1].setStretchFactor(20); } catch(e) {}
  const lc = co.addSeries(LW.LineSeries, {color: "#f23645", lineWidth: 2, priceLineVisible: false, title: "Call"});
  const lp = co.addSeries(LW.LineSeries, {color: "#00c853", lineWidth: 2, priceLineVisible: false, title: "Put"});
  const markers = LW.createSeriesMarkers(k, []);
  oh.charts = {fut: cf, opt: co, k, lc, lp, markers, bars: fut};
  requestAnimationFrame(() => { if (oh.charts && oh.charts.fut === cf) cf.timeScale().fitContent(); });
  // 兩張圖時間軸同步（期權線用台指期的時間點補齊，邏輯位置就會一樣）
  let sync = false;
  const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange(r => { if (sync || !r) return; sync = true; b.timeScale().setVisibleLogicalRange(r); sync = false; });
  link(cf, co); link(co, cf);
  // 游標旁邊顯示那一根的點數（上圖：開高低收、量；下圖：Call、Put）
  const tips = [cf, co].map((ch, i) => { const el = $(i ? "ohOpt" : "ohFut"), d = document.createElement("div"); el.querySelectorAll(".oh-tip").forEach(x => x.remove()); d.className = "oh-tip"; el.style.position = "relative"; el.appendChild(d); return d; });
  const showTip = (i, pr) => {
    tips[i].style.display = "none";
    if (pr.time == null || !pr.point) return;
    const t = tips[i], el = $(i ? "ohOpt" : "ohFut");
    if (i === 0) { const b = pr.seriesData.get(k); if (!b) return;
      const bb = fut.find(x => x[0] === pr.time), cl = b.close >= b.open ? "up" : "down";
      t.innerHTML = `<b>${ohHM(pr.time)}</b><br>開 ${ohN(b.open)}<br>高 ${ohN(b.high)}<br>低 ${ohN(b.low)}<br>收 <b style="color:${cl === "up" ? "#ff5252" : "#00e676"}">${ohN(b.close)}</b>${bb ? "<br>量 " + bb[5].toLocaleString() : ""}`;
    } else { const c = pr.seriesData.get(lc), p = pr.seriesData.get(lp);
      t.innerHTML = `<b>${ohHM(pr.time)}　${oh.k}</b><br><span style="color:#ff5252">買權 Call ${c && c.value != null ? ohN(c.value) : "–"}</span><br><span style="color:#00e676">賣權 Put ${p && p.value != null ? ohN(p.value) : "–"}</span>`; }
    const a = ohAtm(pr.time);
    if (a) t.innerHTML += `<div class="oh-tip-atm">價平 <b>${a.k}</b>（反推指數 ${ohN(a.F)}）<br><span style="color:#ff5252">Call ${a.c == null ? "–" : ohN(a.c)}</span>　<span style="color:#00e676">Put ${a.p == null ? "–" : ohN(a.p)}</span></div>`;
    t.style.display = "block";
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.left = (pr.point.x + 16 + w > el.clientWidth - 70 ? pr.point.x - w - 16 : pr.point.x + 16) + "px";
    t.style.top = Math.max(4, Math.min(pr.point.y - h / 2, el.clientHeight - h - 30)) + "px";
  };
  // 兩張圖十字線連動：滑鼠在哪一張，另一張就把游標放到同一分鐘（K 棒放收盤價、曲線放 Call 或 Put 的價）
  let mirroring = false;
  const mirror = (i, pr) => {
    if (mirroring || !pr.sourceEvent) return;
    const other = i ? cf : co;
    mirroring = true;
    try {
      if (pr.time == null) { other.clearCrosshairPosition(); tips[1 - i].style.display = "none"; }
      else if (i === 1) { const b = oh.charts.bars.find(x => x[0] === pr.time);
        if (b) { other.setCrosshairPosition(b[4], pr.time, k);
          showTip(0, {time: pr.time, point: {x: cf.timeScale().timeToCoordinate(pr.time), y: k.priceToCoordinate(b[4])},
                      seriesData: new Map([[k, {open: b[1], high: b[2], low: b[3], close: b[4]}]])}); } }
      else { const c = oh.charts.lineC.get(pr.time), p = oh.charts.lineP.get(pr.time);
        if (c != null || p != null) {
          const ser = c != null ? lc : lp, val = c != null ? c : p;
          other.setCrosshairPosition(val, pr.time, ser);
          showTip(1, {time: pr.time, point: {x: co.timeScale().timeToCoordinate(pr.time), y: ser.priceToCoordinate(val)},
                      seriesData: new Map([[lc, {value: c}], [lp, {value: p}]])});
        } else { other.clearCrosshairPosition(); tips[1].style.display = "none"; } }
    } finally { mirroring = false; }
  };
  const onMove = (i => pr => { showTip(i, pr); mirror(i, pr); if (pr.time == null) return; oh.B = pr.time; ohTable(); });
  cf.subscribeCrosshairMove(onMove(0)); co.subscribeCrosshairMove(onMove(1));
  const onClick = pr => { if (pr.time == null) return; oh.A = pr.time; ohMark(); ohTable(); };
  cf.subscribeClick(onClick); co.subscribeClick(onClick);
  ["ohFut", "ohOpt"].forEach((id, i) => new ResizeObserver(() => { const c = [cf, co][i], el = $(id); if (oh.charts) c.applyOptions({width: el.clientWidth, height: el.clientHeight}); }).observe($(id)));
  if (!oh.B && fut.length) oh.B = fut[fut.length - 1][0];
  if (oh.k == null) {   // 預設：當天收盤價附近的履約價
    const px = fut.length ? fut[fut.length - 1][4] : 0;
    oh.k = j.strikes.reduce((a, s) => Math.abs(s - px) < Math.abs(a - px) ? s : a, j.strikes[0]);
  }
  ohMark(); ohLine(); ohTable();
}
function ohMark(){
  const c = oh.charts; if (!c) return;
  c.markers.setMarkers(oh.A ? [{time: oh.A - oh.A % (ohTfN() * 60), position: "aboveBar", color: "#ffeb3b", shape: "arrowDown", text: "A " + ohHM(oh.A)}] : []);
}
// 選的履約價：Call、Put 每根K的最後成交（沒成交就沿用上一筆）
function ohLine(){
  const c = oh.charts, j = oh.j; if (!c || !j) return;
  const n = ohTfN();
  const fill = bars => { let i = 0, last = null; bars = bars || [];
    return c.bars.map(b => { while (i < bars.length && bars[i][0] < b[0] + n * 60) last = bars[i++][4]; return last == null ? {time: b[0]} : {time: b[0], value: last}; }); };
  const fc = fill(j.C[oh.k]), fp = fill(j.P[oh.k]);
  c.lc.setData(fc); c.lp.setData(fp);
  c.lineC = new Map(fc.filter(x => x.value != null).map(x => [x.time, x.value]));
  c.lineP = new Map(fp.filter(x => x.value != null).map(x => [x.time, x.value]));
  $("ohCapO").innerHTML = `<b>${oh.k}</b> 履約價：<span class="up">Call</span>／<span class="down">Put</span> 每根K的最後成交價（沒有成交就沿用上一筆）`;
}
function ohTable(){
  const j = oh.j, c = oh.charts; if (!j || !c) return;
  const n = ohTfN(), B = oh.B, A = oh.A;
  const fb = t => { const b = t == null ? null : c.bars.filter(x => x[0] <= t).pop(); return b ? b[4] : null; };
  const pxB = fb(B), pxA = fb(A);
  const atm = pxB == null ? null : j.strikes.reduce((a, s) => Math.abs(s - pxB) < Math.abs(a - pxB) ? s : a, j.strikes[0]);
  $("ohWhen").innerHTML = (A ? `<span class="oh-a">A ${ohHM(A)}</span> 台指期 <b>${ohN(pxA)}</b>　` : `<span class="k">點K線鎖定時點 A　</span>`) +
    `<span class="oh-b">B ${B ? ohHM(B) : "–"}</span> 台指期 <b>${ohN(pxB)}</b>` + (A && pxA ? ` <span class="${pxB >= pxA ? "up" : "down"}">${pxB >= pxA ? "+" : ""}${ohN(pxB - pxA)}</span>` : "") +
    `<div class="k" style="margin-top:2px">${j.contract}（${j.kind}${j.expire ? "，" + j.expire.slice(4, 6) + "/" + j.expire.slice(6) + " 到期" : ""}）　價格 = 到那一${n === 1 ? "分鐘" : "根 5 分K"}為止最後一筆成交；灰色 = 超過 5 分鐘沒成交</div>`;
  const cell = (bars, t) => { const x = t == null ? null : ohAt(bars, t, n); return x; };
  const fmt = (x, t) => !x ? `<span class="k">–</span>` : `<span class="${t - x.t > 300 ? "k" : ""}">${ohN(x.p)}</span>`;
  const ratio = (a, b) => !a || !b || !a.p ? "" : (r => `<span class="${r >= 1 ? "up" : "down"}">${r >= 10 ? r.toFixed(0) : r.toFixed(2)}×</span>`)(b.p / a.p);
  const head = A ? `<tr><th>A Call</th><th>B Call</th><th>B÷A</th><th>履約價</th><th>A Put</th><th>B Put</th><th>B÷A</th></tr>`
                 : `<tr><th>Call 量</th><th>Call</th><th>履約價</th><th>Put</th><th>Put 量</th></tr>`;
  const rows = j.strikes.map(s => {
    const cA = cell(j.C[s], A), cB = cell(j.C[s], B), pA = cell(j.P[s], A), pB = cell(j.P[s], B);
    const itmC = pxB != null && s < pxB, itmP = pxB != null && s > pxB;
    const cls = `${s === atm ? "oh-atm" : ""} ${s === oh.k ? "sel" : ""}`;
    return A ? `<tr data-k="${s}" class="${cls}"><td class="${itmC ? "oh-itm" : ""}">${fmt(cA, A)}</td><td class="${itmC ? "oh-itm" : ""}"><b>${fmt(cB, B)}</b></td><td>${ratio(cA, cB)}</td>
        <td class="oh-k">${s}</td><td class="${itmP ? "oh-itm" : ""}">${fmt(pA, A)}</td><td class="${itmP ? "oh-itm" : ""}"><b>${fmt(pB, B)}</b></td><td>${ratio(pA, pB)}</td></tr>`
      : `<tr data-k="${s}" class="${cls}"><td class="k">${cB ? cB.v.toLocaleString() : ""}</td><td class="${itmC ? "oh-itm" : ""}"><b>${fmt(cB, B)}</b></td>
        <td class="oh-k">${s}</td><td class="${itmP ? "oh-itm" : ""}"><b>${fmt(pB, B)}</b></td><td class="k">${pB ? pB.v.toLocaleString() : ""}</td></tr>`;
  }).join("");
  $("ohT").innerHTML = `<thead>${head}</thead><tbody>${rows}</tbody>`;
  $("ohT").querySelectorAll("tr[data-k]").forEach(tr => tr.onclick = () => { oh.k = +tr.dataset.k; ohLine(); ohTable(); });
  if (!oh.scrolled && atm != null) { const r = $("ohT").querySelector("tr.oh-atm"); if (r) { r.scrollIntoView({block: "center"}); oh.scrolled = true; } }
}
