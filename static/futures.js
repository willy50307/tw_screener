// ---------- 看盤（大分頁，仿 RIDGE）：期貨／證券兩種模式 ----------
// 左邊：全部期貨合約的即時行情表（期交所 MIS；近月指數期貨和正在看的那檔有群益報價就用群益的）。
// 證券模式：左邊列個股K 左邊某個清單（明日觀察、自選、處置股、自己新增的清單…）的股票，報價來自群益（沒開群益就用證交所 MIS）。
// 「即時報價 › 自選股」是另外一份（錄影用），跟這裡不連動。
// 右邊：點一下合約，用「即時報價 › 四格看盤」同一套單格畫面（quote.js 的 qPaneHTML / qPaneDraw）顯示走勢、五檔、明細，資料來自群益。
const FU_PANE = 8;   // qCharts / qp 元素的編號，避開四格看盤的 0~3
const FU_COLS = [["name", "商品"], ["z", "成交價"], ["d", "漲跌"], ["pct", "漲跌幅"], ["bid", "買進"], ["ask", "賣出"],
                 ["o", "開"], ["h", "高"], ["l", "低"], ["v", "總量"], ["yv", "昨量"], ["oi", "未平倉"], ["yoi", "昨日未平倉"], ["doi", "未平倉增減"]];
const fuLS = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch(e) { return d; } };
const fuSave = (k, v) => { try { localStorage.setItem(k, v); } catch(e) {} };
const STK_COLS = FU_COLS.slice(0, 11);   // 證券沒有未平倉
let fuMode = fuLS("fuMode", "fut"), fuList = fuLS("fuList", "mine");
let fuGrp = fuLS("fuGrp", "all"), fuSortK = fuLS("fuSortK", "v"), fuSortD = +fuLS("fuSortD", -1);
const fuSelKey = () => fuMode === "stk" ? "fuSelStk" : "fuSel";
let fuSel = (() => { try { return JSON.parse(fuLS(fuSelKey(), "null")); } catch(e) { return null; } })();
let fuRows = [], fuTimer = null, fuPTimer = null;

function fuStop(){ clearTimeout(fuTimer); clearTimeout(fuPTimer); clearTimeout(fuETimer); }
function fuShow(){
  fuHead();
  fuEstTick();
  if (!$("qp" + FU_PANE)) $("fuPane").innerHTML = qPaneHTML(FU_PANE, fuSel ? fuSel.sym : "", true);
  fuTick(); fuPaneTick();
}
// 上面的篩選按鈕、表頭（點表頭排序）；只重畫，不重新抓資料
function fuHead(){
  $("fuMode").querySelectorAll("[data-m]").forEach(b => {
    b.className = "btn" + (b.dataset.m === fuMode ? "" : " ghost");
    b.onclick = () => {
      if (fuMode === b.dataset.m) return;
      fuMode = b.dataset.m; fuSave("fuMode", fuMode);
      try { fuSel = JSON.parse(fuLS(fuSelKey(), "null")); } catch(e) { fuSel = null; }
      fuRows = []; $("fuSearch").value = "";
      $("fuPane").innerHTML = qPaneHTML(FU_PANE, fuSel ? fuSel.sym : "", true);
      if (qCharts[FU_PANE]) { qCharts[FU_PANE].chart.remove(); qCharts[FU_PANE] = null; }
      fuShow();
    };
  });
  document.querySelectorAll("#pageFut .fu-fonly").forEach(e => e.style.display = fuMode === "fut" ? "" : "none");
  document.querySelectorAll("#pageFut .fu-sonly").forEach(e => e.style.display = fuMode === "stk" ? "" : "none");
  const lists = allTabs().filter(([k]) => k !== "scr");
  if (!lists.some(([k]) => k === fuList)) fuList = "mine";
  $("fuList").innerHTML = lists.map(([k, n]) => `<option value="${k}" ${k === fuList ? "selected" : ""}>${n}（${(S && S.counts[k]) ?? 0}）</option>`).join("");
  // 只有「自選」和自己的清單能加股票（明日觀察、處置股是程式算出來的）
  if (fuMode === "stk") $("fuAddCode").style.display = fuList === "mine" || fuList.startsWith("wl_") ? "" : "none";
  $("fuAddCode").onclick = async () => { if (await wlAddCodes(fuList)) { fuHead(); fuTick(); } };
  $("fuList").onchange = () => { fuList = $("fuList").value; fuSave("fuList", fuList); fuRows = []; fuHead(); fuTick(); };
  $("fuSearch").placeholder = fuMode === "fut" ? "搜尋代號／名稱（台積電、2330、TXF）" : "篩選自選股（代號或名稱）";
  $("fuGrp").querySelectorAll("[data-g]").forEach(b => {
    b.className = "btn" + (b.dataset.g === fuGrp ? "" : " ghost");
    b.onclick = () => { fuGrp = b.dataset.g; fuSave("fuGrp", fuGrp); fuHead(); };
  });
  $("fuSearch").oninput = fuRender;
  $("fuNear").onchange = $("fuTraded").onchange = fuRender;
  $("fuTable").querySelector("thead").innerHTML = "<tr><th class=\"no\">#</th>" + (fuMode === "fut" ? FU_COLS : STK_COLS).map(([k, n]) =>
    `<th data-k="${k}" class="${k === fuSortK ? "on" : ""}">${n}${k === fuSortK ? (fuSortD < 0 ? " ▼" : " ▲") : ""}</th>`).join("") + "</tr>";
  $("fuTable").querySelectorAll("th").forEach(th => th.onclick = () => {
    if (fuSortK === th.dataset.k) fuSortD = -fuSortD; else { fuSortK = th.dataset.k; fuSortD = th.dataset.k === "name" ? 1 : -1; }
    fuSave("fuSortK", fuSortK); fuSave("fuSortD", fuSortD); fuHead();
  });
  fuRender();
}
const fuVisible = () => window.CUR_PAGE === "futures";

async function fuTick(){
  clearTimeout(fuTimer);
  if (!fuVisible()) return;
  if (fuMode === "stk") return fuStkTick();
  let j;
  try { j = await api("/api/fut/table?sel=" + (fuSel ? fuSel.sym : "")); } catch(e) { fuTimer = setTimeout(fuTick, 5000); return; }
  if (fuMode !== "fut") return;
  fuRows = j.rows.map(r => ({...r, d: r.z != null && r.y ? r.z - r.y : null, pct: r.z != null && r.y ? (r.z / r.y - 1) * 100 : null,
                             doi: r.oi != null && r.yoi != null ? r.oi - r.yoi : null}));
  $("fuSrc").textContent = j.error ? j.error : `${j.session === "1" ? "夜盤" : "日盤"}｜` +
    (j.src === "fallback" ? `期交所 MIS 暫時抓不到，改用群益報價（只有近月指數期貨＋昨天量最大的個股期貨共 80 檔有即時價）` :
     `期交所 MIS（約 10 秒更新）${j.cap ? "＋群益（藍色 群 = 群益即時）" : "（群益沒連線）"}`) + `｜昨量、昨日未平倉 = ${j.prev_date || "–"} 一般盤`;
  if (!fuSel) {   // 第一次打開：預設看台指期近月
    const tx = fuRows.find(r => r.sym.startsWith("TXF") && r.near);
    if (tx) { fuSel = {sym: tx.sym, name: tx.name}; fuSave(fuSelKey(), JSON.stringify(fuSel)); fuPaneTick(); }
  }
  fuRender();
  fuTimer = setTimeout(fuTick, 2000);
}

// 證券模式：選的那個清單的即時報價
async function fuStkTick(){
  let j;
  const key = fuList;
  try { j = await api("/api/rt/list?key=" + encodeURIComponent(key)); } catch(e) { fuTimer = setTimeout(fuTick, 5000); return; }
  if (fuMode !== "stk" || key !== fuList) return;
  fuRows = j.rows.map(r => ({...r, sym: r.code, name: r.name || r.code, grp: "stock", near: true, v: r.v ?? 0,
                             d: r.z != null && r.y ? r.z - r.y : null, pct: r.z != null && r.y ? (r.z / r.y - 1) * 100 : null}));
  $("fuSrc").textContent = "報價來源：" + j.src;
  if (!fuSel && fuRows.length) { fuSel = {sym: fuRows[0].sym, name: fuRows[0].name}; fuSave(fuSelKey(), JSON.stringify(fuSel)); fuPaneTick(); }
  fuRender();
  fuTimer = setTimeout(fuTick, 3000);
}

function fuRender(){
  const s = $("fuSearch").value.trim().toUpperCase(), near = $("fuNear").checked, traded = $("fuTraded").checked;
  const stk = fuMode === "stk", cols = stk ? STK_COLS.length + 1 : FU_COLS.length + 1;
  let rows = fuRows.filter(r => (stk || fuGrp === "all" || r.grp === fuGrp) &&
    (stk || !near || r.near) && (stk || !traded || r.v > 0) && (!s || r.sym.toUpperCase().includes(s) || r.name.toUpperCase().includes(s) || (r.spot && r.spot.startsWith(s))));
  const k = fuSortK, dir = fuSortD;
  rows.sort((a, b) => {
    const x = a[k], y = b[k];
    if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y, "zh-Hant") : x - y) * dir;
  });
  const c = (v, ref) => v == null || ref == null ? "" : v > ref ? "up" : v < ref ? "down" : "flat";
  const n = v => v == null ? "" : qNum(v), sg = v => v == null ? "" : (v > 0 ? "▲" : v < 0 ? "▼" : "") + qNum(Math.abs(v));
  const shown = rows.slice(0, 600);   // 全部合約一千多個，一次最多畫 600 列，用搜尋或篩選找其他的
  // 漲跌停（個股期貨 ±10%）：成交價、最高／最低那格整格塗紅／綠底
  const lim = (v, r) => v == null || !r.y || r.grp === "index" ? "" : v >= r.y * 1.095 ? " lim-up" : v <= r.y * 0.905 ? " lim-dn" : "";
  $("fuTable").querySelector("tbody").innerHTML = shown.map((r, k) => {
    const cl = c(r.z, r.y);
    return `<tr data-s="${r.sym}" class="${fuSel && fuSel.sym === r.sym ? "sel" : ""} ${r.day_only ? "dayonly" : ""}" title="${r.sym}${r.day_only ? "（沒有夜盤，顯示日盤）" : ""}">
      <td class="no">${k + 1}</td><td><span class="nm">${r.name}</span>${r.src === "cap" ? `<span class="cap">群</span>` : ""}</td>
      <td class="${cl}${lim(r.z, r)}"><b>${n(r.z)}</b></td><td class="${cl}">${sg(r.d)}</td><td class="${cl}">${r.pct == null ? "" : r.pct.toFixed(2) + "%"}</td>
      <td class="${c(r.bid, r.y)}">${n(r.bid)}</td><td class="${c(r.ask, r.y)}">${n(r.ask)}</td>
      <td class="${c(r.o, r.y)}">${n(r.o)}</td><td class="${c(r.h, r.y)}${lim(r.h, r)}">${n(r.h)}</td><td class="${c(r.l, r.y)}${lim(r.l, r)}">${n(r.l)}</td>
      <td class="v">${n(r.v)}</td><td>${n(r.yv)}</td>` + (stk ? "</tr>" : `<td>${n(r.oi)}</td><td>${n(r.yoi)}</td>
      <td class="${r.doi > 0 ? "up" : r.doi < 0 ? "down" : ""}">${r.doi == null ? "" : (r.doi > 0 ? "+" : "") + qNum(r.doi)}</td></tr>`);
  }).join("") + (rows.length > shown.length ? `<tr><td colspan="${cols}" class="k" style="text-align:center">還有 ${rows.length - shown.length} 個合約沒列出，請用搜尋或篩選</td></tr>` : "") +
    (!rows.length ? `<tr><td colspan="${cols}" class="k" style="text-align:center;padding:20px">${fuRows.length ? "沒有符合的項目" : stk ? "這個清單目前沒有股票（自選清單在「個股K」左邊按 ＋ 新增、加股票）" : "載入中…"}</td></tr>` : "");
  $("fuTable").querySelectorAll("tr[data-s]").forEach(tr => tr.onclick = () => {
    const r = fuRows.find(x => x.sym === tr.dataset.s);
    fuSel = {sym: r.sym, name: r.name, spot: r.spot || ""}; fuSave(fuSelKey(), JSON.stringify(fuSel));
    $("fuTable").querySelectorAll("tr.sel").forEach(x => x.classList.remove("sel")); tr.classList.add("sel");
    $("qbIn" + FU_PANE).value = r.sym;
    fuPaneTick();
  });
}

async function fuPaneTick(){
  clearTimeout(fuPTimer);
  if (!fuVisible() || !fuSel) return;
  const sel = fuSel.sym, stk = fuMode === "stk";
  let j;
  try { j = await api(`/api/fut/pane?${stk ? "code" : "sym"}=${encodeURIComponent(sel)}&name=${encodeURIComponent(fuSel.name)}`); } catch(e) { fuPTimer = setTimeout(fuPaneTick, 3000); return; }
  if (!fuSel || fuSel.sym !== sel) return;   // 等回應的時候已經點了別檔
  if (!$("qp" + FU_PANE)) $("fuPane").innerHTML = qPaneHTML(FU_PANE, sel, true);
  $("qbIn" + FU_PANE).value = sel;
  if (!j.ready) {
    $("fuMsg").textContent = `右邊的五檔、明細、走勢需要群益 API：${j.msg}`;
    qPaneDraw(FU_PANE, null);
    $("qpTk" + FU_PANE).innerHTML = "";
    fuPTimer = setTimeout(fuPaneTick, 3000);
    return;
  }
  $("fuMsg").textContent = "";
  const p = j.pane;
  if (p.st && !stk) p.st.amount = null;   // 期貨沒有「成交值」（四格看盤是用 價×張×1000 算的）
  p.name = fuSel.name;
  // 60分K／日K／週K／月K 的歷史：股票用代號；期貨用期交所代碼＋標的股票（個股期貨沒有自己的歷史，用標的的）
  p.histq = stk ? "code=" + encodeURIComponent(sel)
    : `fut=${encodeURIComponent(sel)}&spot=${encodeURIComponent(fuSel.spot || "")}&name=${encodeURIComponent(p.q && p.q.name || fuSel.name)}`;
  qPaneDraw(FU_PANE, p);
  if (!stk) {
    $("qpName" + FU_PANE).textContent = `${fuSel.name}（群益 ${p.code}）`;
    $("qpPx" + FU_PANE).innerHTML = $("qpPx" + FU_PANE).innerHTML.replace("張<", "口<");
  }
  fuTickColor(p.ticks);
  fuPTimer = setTimeout(fuPaneTick, 1000);
}

// ===== 最上面的預估量：加權、台指期、櫃買三格＋上市櫃合計（est.py：今天累計 ÷ 過去 20 天同時間平均已成交比例）=====
let fuETimer = null;
async function fuEstTick(){
  clearTimeout(fuETimer);
  if (!fuVisible()) return;
  let j;
  try { j = await api("/api/est"); } catch(e) { fuETimer = setTimeout(fuEstTick, 5000); return; }
  const yi = v => v == null ? "–" : Math.round(v / 1e8).toLocaleString() + " 億";
  const lots = v => v == null ? "–" : Math.round(v).toLocaleString() + " 口";
  const px = x => {
    if (x.z == null) return `<span class="k">–</span>`;
    const d = x.y ? x.z - x.y : null, cl = qCls(x.z, x.y);
    return `<b class="${cl}">${qNum(x.z)}</b> <span class="${cl}">${d == null ? "" : (d > 0 ? "▲" : d < 0 ? "▼" : "") + qNum(Math.abs(+d.toFixed(2)))} ${qPct(x.z, x.y)}</span>`;
  };
  const est = (x, f) => x.frac >= 1 ? `<span class="k">已收盤，全天</span> <b>${f(x.cum)}</b>`
    : x.est == null ? `<span class="k">${j.pre ? "還沒開盤" : "資料不足"}</span>` : `<b class="yel">${f(x.est)}</b> <span class="k">（已過 ${(x.frac * 100).toFixed(0)}%）</span>`;
  // 較昨日同時間：今天累計 ÷ 前一個交易日同一個時間的累計（開盤頭幾分鐘預估量跳很大，這個比較穩）
  const vsPrev = x => x.prev && x.cum && !(x.frac >= 1) ? (r => `<span class="${r >= 1 ? "up" : "down"}">較昨日同時間 ${r >= 1 ? "+" : ""}${((r - 1) * 100).toFixed(0)}%</span>`)(x.cum / x.prev) : "";
  const card = (title, x, f, lbl) => `<div class="fe-card"><div class="fe-t">${title}　${px(x)}</div>
    <div class="fe-row"><span class="k">${lbl}</span><b>${f(x.cum)}</b>${j.pre && f === yi ? `<span class="k">（前一日）</span>` : vsPrev(x)}</div>
    <div class="fe-row"><span class="k">預估量</span>${est(x, f)}</div>
    <div class="fe-row"><span class="k">昨量</span><b>${f(x.yv)}</b>${x === j.otc && x.yv != null ? `<span class="k">（約）</span>` : ""}</div></div>`;
  const s = j.tse.cum != null && j.otc.cum != null ? j.tse.cum + j.otc.cum : null;
  const se = j.tse.est != null && j.otc.est != null ? j.tse.est + j.otc.est : null;
  const fin = j.tse.frac >= 1 && j.otc.frac >= 1;
  $("fuEst").innerHTML = card("加權指數", j.tse, yi, "成交金額") + card(`台指期近月（${j.tx_session === "1" ? "夜盤" : "日盤"}）`, j.tx, lots, "成交口數") +
    card("櫃買指數", j.otc, yi, "成交金額") +
    `<div class="fe-card fe-sum"><div class="fe-t">上市＋上櫃</div><div class="fe-row"><span class="k">成交金額</span><b>${yi(s)}</b></div>
      <div class="fe-row"><span class="k">預估量</span>${fin ? `<span class="k">已收盤，全天</span> <b>${yi(s)}</b>` : se == null ? `<span class="k">–</span>` : `<b class="yel">${yi(se)}</b>`}</div>
      <div class="fe-row"><span class="k">昨量</span><b>${yi(j.tse.yv != null && j.otc.yv != null ? j.tse.yv + j.otc.yv : null)}</b></div></div>` +
    `<div class="fe-note k" title="預估量 = 今天到現在的累計量 ÷ 過去 ${j.days || 20} 個交易日「到同一個時間點平均已成交全天的比例」。開盤和尾盤集合競價量特別大，所以比單純用時間比例準。台指期用資料庫裡的台指期 5 分K，日盤、夜盤分開算。">ⓘ 預估量怎麼算</div>`;
  fuETimer = setTimeout(fuEstTick, 3000);
}

// 明細依單量上色：比最近成交的 90%／98% 還大的單，整列底色變黃（越大越深）
function fuTickColor(ticks){
  const qs = ticks.map(t => t[2]).sort((a, b) => a - b);
  if (qs.length < 10) return;
  const big = Math.max(2, qs[Math.floor(qs.length * 0.9)]), huge = Math.max(big + 1, qs[Math.floor(qs.length * 0.98)]);
  const shown = ticks.slice(-40), trs = $("qpTk" + FU_PANE).querySelectorAll("tr");
  shown.forEach((t, k) => { const tr = trs[k + 1]; if (tr) tr.className = t[2] >= huge ? "huge" : t[2] >= big ? "big" : ""; });
}
