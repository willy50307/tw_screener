// ---------- 統計數據（仿權證小哥：連漲、均量比、月線斜率、外資連買…）：個股K 左邊清單的「📊 數據」欄、「🔎 篩選」分頁 ----------
var SCR = null;
let SCR_T = 0, SCR_MAP = {}, scrLoading = null;
const SCR_OPS = [[">=", "≥"], [">", ">"], ["<=", "≤"], ["<", "<"], ["=", "="]];
// 清單顯示的統計欄（權證小哥前半段的順序）；篩選用到的其他欄位會自動加在後面
const SCR_COLS = ["up_streak", "vol_streak", "prev_chg", "pos", "vr", "slope20", "turnover", "bw", "fi_streak", "it_streak"];
const SCR_PRESETS = [
  ["外資連買 ≥3天", [["fi_streak", ">=", 3]]],
  ["投信連買 ≥3天", [["it_streak", ">=", 3]]],
  ["土洋都連買", [["fi_streak", ">=", 2], ["it_streak", ">=", 2]]],
  ["月線上彎", [["slope20", ">", 0]]],
  ["爆量 均量比≥3", [["vr", ">=", 3], ["lots", ">=", 1000]]],
  ["連漲 ≥3天", [["up_streak", ">=", 3]]],
  ["帶寬收斂 ≤8%", [["bw", "<=", 8], ["lots", ">=", 500]]],
  ["高週轉 ≥10%", [["turnover", ">=", 10]]],
];
let scrFilters = (() => { try { return JSON.parse(localStorage.getItem("scrFilters") || "null") || [["fi_streak", ">=", 3]]; } catch(e) { return [["fi_streak", ">=", 3]]; } })();
const scrSave = () => { try { localStorage.setItem("scrFilters", JSON.stringify(scrFilters)); } catch(e) {} };
const scrKey = k => SCR && SCR.keys.find(x => x[0] === k);
const statColored = k => /streak|chg|slope|pos|bias|^fi$|^it$|m_chg/.test(k);

// 全市場最新一天的統計（5 分鐘內共用）
function scrLoad(force){
  if (SCR && !force && Date.now() - SCR_T < 300e3) return Promise.resolve(SCR);
  if (scrLoading) return scrLoading;
  scrLoading = api("/api/stats").then(d => {
    if (d.error) throw new Error(d.error);
    SCR = d; SCR_T = Date.now(); SCR_MAP = Object.fromEntries(d.rows.map(r => [r.code, r]));
    scrRenderFilters(); return d;
  }).catch(e => { $("scrMeta").textContent = "⚠ " + e.message; }).finally(() => { scrLoading = null; });
  return scrLoading;
}
function statVal(r, k){ const s = SCR_MAP[r.code]; return s ? s[k] : null; }

// 給 app.js 的 columns() 用：[key, 標題, 顯示內容, 排序值]
function statColumns(){
  if (!SCR) return [];
  const extra = tab === "scr" ? scrFilters.map(f => f[0]).filter(k => !SCR_COLS.includes(k) && !["close", "chg", "lots"].includes(k)) : [];
  return [...SCR_COLS, ...new Set(extra)].map(k => {
    const x = scrKey(k); if (!x) return null;
    return [k, `<span title="${x[4]}">${x[1]}</span>`, r => {
      const v = statVal(r, k);
      return v == null ? "–" : statColored(k) ? `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, x[3])}</span>` : fmt(v, x[3]);
    }, r => statVal(r, k)];
  }).filter(Boolean).concat([["ind", "產業", r => `<span class="k sm">${(SCR_MAP[r.code] || {}).ind || ""}</span>`, r => (SCR_MAP[r.code] || {}).ind]]);
}

function scrRows(){
  if (!SCR) return [];
  const q = $("scrQ").value.trim(), mk = $("scrMarket").value;
  const test = (v, op, x) => v != null && (op === ">=" ? v >= x : op === ">" ? v > x : op === "<=" ? v <= x : op === "<" ? v < x : v === x);
  const fs = scrFilters.filter(f => f[2] != null);
  return SCR.rows.filter(r => (!mk || r.market === mk) && (!q || r.code.startsWith(q) || r.name.includes(q) || (r.ind || "").includes(q))
    && fs.every(([k, op, x]) => test(r[k], op, x)));
}

function scrRenderFilters(){
  if (!SCR) return;
  const m = SCR.meta;
  $("scrMeta").textContent = `${m.date} 收盤｜法人 ${md(m.inst_date)}｜融資券 ${md(m.margin_date)}`;
  const opts = sel => SCR.keys.map(([k, l, u]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${l}${u ? `（${u}）` : ""}</option>`).join("");
  $("scrRows").innerHTML = scrFilters.map(([k, op, v], i) => `<div class="scr-f" data-i="${i}">
    <select class="fk">${opts(k)}</select>
    <select class="fo">${SCR_OPS.map(([o, l]) => `<option value="${o}" ${o === op ? "selected" : ""}>${l}</option>`).join("")}</select>
    <input class="fv" type="number" step="any" value="${v ?? ""}"><span class="k">${scrKey(k)?.[2] || ""}</span>
    <span class="k" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${scrKey(k)?.[4] || ""}</span>
    <button class="x" title="刪除這個條件">✕</button></div>`).join("") || `<div class="k">沒有條件（顯示全部，依成交值排序）</div>`;
  document.querySelectorAll("#scrRows .scr-f").forEach(row => {
    const i = +row.dataset.i, upd = () => {
      scrFilters[i] = [row.querySelector(".fk").value, row.querySelector(".fo").value, row.querySelector(".fv").value === "" ? null : +row.querySelector(".fv").value];
      scrSave(); scrRefresh();
    };
    row.querySelector(".fk").onchange = () => { upd(); scrRenderFilters(); };
    row.querySelector(".fo").onchange = upd;
    row.querySelector(".fv").oninput = upd;
    row.querySelector(".x").onclick = () => { scrFilters.splice(i, 1); scrSave(); scrRenderFilters(); scrRefresh(); };
  });
}
function scrRefresh(){ if (tab === "scr") { renderTabs(); renderList(); } }

// K 線上方統計列點一下 → 個股K 的「🔎 篩選」分頁加上「這個欄位 ≥ 目前值」（負值用 ≤）
window.scrOpenWith = (k, v) => {
  if (k == null) return;
  const val = v == null ? 0 : v, op = val < 0 ? "<=" : ">=";
  const i = scrFilters.findIndex(f => f[0] === k);
  if (i >= 0) scrFilters[i] = [k, op, val]; else scrFilters.push([k, op, val]);
  scrSave();
  const pg = pagesList().find(p => p.type === "strategy");
  if (pg && window.CUR_PAGE !== "strategy") showPage(pg.id);
  tab = "scr"; sortKey = null;
  scrLoad().then(() => { scrRenderFilters(); renderTabs(); renderList(); if (window.renderPages) renderPages(); });
};

$("scrAdd").onclick = () => { scrFilters.push(["slope20", ">", 0]); scrSave(); scrRenderFilters(); scrRefresh(); };
$("scrClear").onclick = () => { scrFilters = []; scrSave(); scrRenderFilters(); scrRefresh(); };
$("scrQ").oninput = scrRefresh;
$("scrMarket").onchange = scrRefresh;
$("scrPresets").innerHTML = SCR_PRESETS.map(([l], i) => `<button data-i="${i}">${l}</button>`).join("");
document.querySelectorAll("#scrPresets button").forEach(b => b.onclick = () => {
  scrFilters = SCR_PRESETS[+b.dataset.i][1].map(f => [...f]); scrSave(); scrRenderFilters(); scrRefresh();
});

// ---------- 左邊清單可以左右拖拉調整寬度（每一頁各自記住）----------
function addAsideResizer(wrap){
  const aside = wrap.querySelector(":scope > aside");
  if (!aside || wrap.querySelector(":scope > .resizer")) return;
  const key = "asideW_" + wrap.id;
  try { const w = +localStorage.getItem(key); if (w) aside.style.width = w + "px"; } catch(e) {}
  const h = document.createElement("div");
  h.className = "resizer"; h.title = "左右拖拉調整寬度（點兩下恢復預設）";
  aside.after(h);
  h.onmousedown = e => {
    e.preventDefault();
    const x0 = e.clientX, w0 = aside.getBoundingClientRect().width;
    document.body.classList.add("resizing");
    const move = ev => { aside.style.width = Math.max(220, Math.min(window.innerWidth - 300, w0 + ev.clientX - x0)) + "px"; ChartView.resizeAll(); };
    const up = () => {
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
      document.body.classList.remove("resizing");
      try { localStorage.setItem(key, Math.round(aside.getBoundingClientRect().width)); } catch(e) {}
      ChartView.resizeAll();
    };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  };
  h.ondblclick = () => { aside.style.width = ""; try { localStorage.removeItem(key); } catch(e) {} ChartView.resizeAll(); };
}
document.querySelectorAll(".wrap").forEach(addAsideResizer);
