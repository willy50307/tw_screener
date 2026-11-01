// ---------- 處置歷史頁 ----------
let DISP = null, dSel = null, dSort = {k: "start", dir: -1}, DISP_CV = null;

async function dispShow(){
  if (!DISP) {
    try { DISP = await api("/api/disposals"); } catch(e) { setTimeout(dispShow, 3000); return; }
  }
  dispRender();
}

function dispRows(){
  const m = $("dfMarket").value, n = $("dfNth").value, st = $("dfState").value, q = $("dfQ").value.trim();
  return DISP.filter(r => (!m || r.market === m) && (!n || String(r.nth) === n)
      && (!st || (st === "ongoing") === r.ongoing) && (!q || r.code.includes(q) || r.name.includes(q)))
    .sort((a, b) => ((a[dSort.k] ?? -1e9) > (b[dSort.k] ?? -1e9) ? 1 : -1) * dSort.dir);
}

const pctCell = v => v == null ? `<span class="k">–</span>` : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, 1)}</span>`;

function dispRender(){
  const rs = dispRows();
  // 摘要：平均漲跌與上漲比例
  const stat = k => { const v = rs.map(r => r[k]).filter(x => x != null);
    return v.length ? {avg: v.reduce((a, b) => a + b, 0) / v.length, up: v.filter(x => x > 0).length / v.length * 100, n: v.length} : null; };
  $("dsum").innerHTML = `<div><b>${rs.length}</b> 筆處置（${new Set(rs.map(r => r.code)).size} 檔）<span class="k">　115/8/10 新制後</span></div>` +
    `<div class="dsum-grid">` + [["pre5","處置前5日"],["during","處置中"],["post5","出關後5日"],["post10","出關後10日"]].map(([k, l]) => {
      const s = stat(k);
      return `<div><span class="k">${l}</span><br>${s ? `平均 ${pctCell(s.avg)}%<br><span class="k">上漲 ${fmt(s.up, 0)}%｜${s.n}筆</span>` : "–"}</div>`;
    }).join("") + `</div>`;
  const cols = [["code","代號"],["name","名稱"],["start","處置期間／條件"],["pre5","前5日%"],["during","處置中%"],["post5","出關5日%"]];
  $("dthead").innerHTML = "<tr>" + cols.map(([k, l]) => `<th data-k="${k}">${l}${dSort.k === k ? (dSort.dir > 0 ? "▲" : "▼") : ""}</th>`).join("") + "</tr>";
  document.querySelectorAll("#dthead th").forEach(th => th.onclick = () => {
    dSort = {k: th.dataset.k, dir: dSort.k === th.dataset.k ? -dSort.dir : -1}; dispRender(); });
  $("dtbody").innerHTML = rs.map((r, i) => `<tr class="r ${dSel && dSel.code === r.code && dSel.start === r.start ? "sel" : ""}" data-i="${i}">
    <td>${r.code}</td><td>${r.name}${r.ongoing ? `<span class="tag t-disp">處置中</span>` : ""}</td>
    <td>${md(r.start)}~${md(r.end)}<br><span class="cond sm">${r.cond}${r.nth === 2 ? " 第2次" : ""}</span></td>
    <td>${pctCell(r.pre5)}</td><td>${pctCell(r.during)}</td><td>${pctCell(r.post5)}</td></tr>`).join("")
    || `<tr><td colspan="6" class="empty">沒有符合的處置紀錄</td></tr>`;
  document.querySelectorAll("#dtbody tr.r").forEach(tr => tr.onclick = () => dispSelect(rs[+tr.dataset.i]));
  if (rs.length && !dSel) dispSelect(rs[0], true);     // 自動選第一筆時不要切走「研究想法」
}

async function dispSelect(rec, auto){
  if (!auto && typeof dView !== "undefined" && dView !== "chart") dShowView("chart");
  dSel = rec;
  document.querySelectorAll("#dtbody tr.r").forEach((tr, i) => tr.classList.toggle("sel", dispRows()[i] === rec));
  if (!DISP_CV) DISP_CV = new ChartView($("dchartbox"));
  const c = await api(DISP_CV.url(rec.code));
  if (!c.row || dSel !== rec) return;
  const mine = DISP.filter(x => x.code === rec.code).sort((a, b) => a.start < b.start ? -1 : 1);
  $("dinfo").innerHTML = `<div><span class="big">${rec.code} ${rec.name}</span> <span class="k">${rec.market}</span>
      <span class="k">收盤</span> <span class="big ${cls(c.row.chg)}">${fmt(c.row.close)}</span> <span class="${cls(c.row.chg)}">${fmt(c.row.chg)}%</span></div>
    <div class="dhist">${mine.map(x => `<span class="${x === rec ? "on" : ""}">${md(x.start)}~${md(x.end)} ${x.cond}${x.nth === 2 ? "（第2次）" : ""}：
      前5日 ${pctCell(x.pre5)}%｜處置中 ${pctCell(x.during)}%｜出關5日 ${pctCell(x.post5)}%｜出關10日 ${pctCell(x.post10)}%</span>`).join("")}</div>`;
  if (!DISP_CV) DISP_CV = new ChartView($("dchartbox"));
  DISP_CV.draw(c.row, c, {shades: mine.map(x => [x.start, x.end, `處置${x.nth === 2 ? "②" : ""}`]),
                          trades: (window.BT_TRADES || {})[rec.code]});
  window.CUR_STOCK = {code: rec.code, r: c.row, c, page: "disposal", disposals: mine};
  if (window.brOnStock) brOnStock();
}

["dfMarket", "dfNth", "dfState"].forEach(id => $(id).onchange = dispRender);
$("dfQ").oninput = dispRender;


// 處置歷史：右邊切換「個股K線」／「研究想法」
let dView = "chart";
function dShowView(v){
  dView = v;
  $("dSel").value = v;
  if (window.renderPages) renderPages();
  $("dinfo").style.display = $("dchartbox").style.display = v === "chart" ? "" : "none";
  $("dIdeas").style.display = v === "ideas" ? "block" : "none";
  if (v === "ideas") ideasRender($("dIdeas"), "disposal");
  else setTimeout(() => ChartView.resizeAll(), 0);
}
$("dSel").onchange = e => dShowView(e.target.value);
