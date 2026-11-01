// ---------- 面板拖拉調整大小（共用）----------
// 每條分隔線拖拉後記在這台電腦的瀏覽器（localStorage 的 split_xxx），點兩下分隔線恢復預設；設定 › 系統 可以一次全部重設。
// 畫面很多是 innerHTML 重畫的（四格看盤換組、籌碼換分頁…），所以用 MutationObserver 看到新的面板就自動補上分隔線。
// 個股K 左邊清單（screener.js 的 addAsideResizer）、K 線副圖高度（chart.js 的 paneH_）是原本就有的，這裡只負責重設時一起清掉。
const SP_RULES = [
  // 看盤：左邊行情表 ↔ 右邊走勢／五檔／明細
  {sel: "#pageFut .fu-main > .fu-left", key: () => "fuLeft", edge: "right", min: 260, keep: 380},
  // 單格看盤裡：走勢圖 ↔ 右邊統計／五檔／明細（看盤頁、四格看盤各記一份，四格的四個一起變）
  {sel: ".qp-main > .qp-side", key: el => el.closest("#fuPane") ? "fuSide" : "qbSide", edge: "left", min: 200, keep: 160},
  // 右側面板（回測／問 AI／主力進出）
  {sel: "#content > #side", key: () => "side", edge: "left", min: 280, keep: 500, cssVar: "--sideW"},
  // 市場情緒：當天走勢 ↔ 右邊統計
  {sel: ".mood-row > .mood-box.side", key: () => "moodSide", edge: "left", min: 220, keep: 300},
  // 籌碼整理、當沖研究：左右兩欄裡右邊那欄
  {sel: ".lu-row > .lu-box.side", key: el => "luSide_" + ((el.closest("[id^=page]") || {}).id || ""), edge: "left", min: 220, keep: 300},
  // 籌碼整理 › 選擇權：右邊未平倉
  {sel: ".opt-layout > .opt-side", key: () => "optSide", edge: "left", min: 260, keep: 300},
];
const spGet = k => { try { return JSON.parse(localStorage.getItem("split_" + k) || "null"); } catch(e) { return null; } };
const spSet = (k, v) => { try { v == null ? localStorage.removeItem("split_" + k) : localStorage.setItem("split_" + k, JSON.stringify(v)); } catch(e) {} };

// 圖表跟著重抓大小（K 線圖、情緒圖聽 window resize；群益走勢圖、籌碼圖自己會偵測）
let spRaf = 0;
const spNotify = () => { if (!spRaf) spRaf = requestAnimationFrame(() => { spRaf = 0; window.dispatchEvent(new Event("resize")); }); };

// 拖拉的共用部分：按下 onStart()、移動 onMove(dx, dy)、放開 onEnd()
function spDrag(h, cursor, onStart, onMove, onEnd){
  h.onpointerdown = e => {
    if (e.button !== 0) return;
    e.preventDefault();
    const x0 = e.clientX, y0 = e.clientY;
    onStart();
    h.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing"); document.body.style.cursor = cursor;
    h.onpointermove = ev => { onMove(ev.clientX - x0, ev.clientY - y0); spNotify(); };
    h.onpointerup = h.onpointercancel = () => {
      h.onpointermove = h.onpointerup = h.onpointercancel = null;
      document.body.classList.remove("resizing"); document.body.style.cursor = "";
      onEnd(); spNotify();
    };
  };
}

function spApply(el, rule, px){
  if (rule.cssVar) { px == null ? document.documentElement.style.removeProperty(rule.cssVar) : document.documentElement.style.setProperty(rule.cssVar, px + "px"); return; }
  el.style.width = px == null ? "" : px + "px";
  el.style.maxWidth = px == null ? "" : "none";
  el.style.flex = px == null ? "" : "0 0 auto";
  el.parentElement.classList.toggle("sp-set", px != null);
}
// 同一個 key 的面板一起變（四格看盤的四個右欄）
const spEach = (el, rule, px) => rule.cssVar ? spApply(el, rule, px) : document.querySelectorAll(`[data-sp-key="${el.dataset.spKey}"]`).forEach(x => spApply(x, rule, px));

function spAttach(el, rule){
  const key = rule.key(el);
  el.dataset.sp = "1"; el.dataset.spKey = key;
  const saved = spGet(key);
  if (saved != null) spApply(el, rule, saved);
  const h = document.createElement("div");
  h.className = "resizer sp-h"; h.title = "左右拖拉調整寬度（點兩下恢復預設）";
  const g = parseFloat(getComputedStyle(el.parentElement).columnGap) || 0;   // 分隔線放在原本的間隔裡，不要多出一大塊空白
  if (g) h.style.margin = `0 ${-g / 2 + 1}px`;
  rule.edge === "right" ? el.after(h) : el.before(h);
  let w0, max;
  spDrag(h, "col-resize", () => {
    w0 = el.getBoundingClientRect().width;
    max = Math.max(rule.min, (rule.cssVar ? window.innerWidth : el.parentElement.getBoundingClientRect().width) - rule.keep);
  }, dx => {
    spEach(el, rule, Math.round(Math.max(rule.min, Math.min(max, w0 + (rule.edge === "right" ? dx : -dx)))));
  }, () => spSet(key, Math.round(el.getBoundingClientRect().width)));
  h.ondblclick = () => { spSet(key, null); spEach(el, rule, null); spNotify(); };
}

// 四格看盤：中間的十字分隔線（左右欄寬、上下列高，以 % 記）
function spGrid(qb){
  const set = (v, dim) => {
    qb.style[dim === "c" ? "gridTemplateColumns" : "gridTemplateRows"] = v == null ? "" : `${v}% 1fr`;
    const h = qb.querySelector(`:scope > .sp-g${dim}`);
    if (h) h.style[dim === "c" ? "left" : "top"] = v == null ? "calc(50% - 4px)" : `calc(${v}% - 2px)`;
  };
  ["c", "r"].forEach(dim => {
    const h = document.createElement("div");
    h.className = "sp-g sp-g" + dim; h.title = (dim === "c" ? "左右" : "上下") + "拖拉調整四格大小（點兩下恢復平均）";
    qb.appendChild(h);
    set(spGet("qb_" + dim), dim);
    const first = () => qb.querySelector(":scope > .qp"), len = x => dim === "c" ? x.offsetWidth : x.offsetHeight;
    let p0, tot;
    spDrag(h, dim === "c" ? "col-resize" : "row-resize", () => {
      tot = len(qb) || 1; p0 = first() ? len(first()) / tot * 100 : 50;
    }, (dx, dy) => set(Math.round(Math.max(15, Math.min(85, p0 + (dim === "c" ? dx : dy) / tot * 100)) * 10) / 10, dim),
    () => { if (first()) spSet("qb_" + dim, Math.round(len(first()) / tot * 1000) / 10); });
    h.ondblclick = () => { spSet("qb_" + dim, null); set(null, dim); spNotify(); };
  });
}

function spScan(){
  for (const rule of SP_RULES) document.querySelectorAll(rule.sel).forEach(el => { if (!el.dataset.sp) spAttach(el, rule); });
  document.querySelectorAll(".qb").forEach(qb => { if (!qb.querySelector(":scope > .sp-g")) spGrid(qb); });
}
let spPending = false;
new MutationObserver(() => {
  if (spPending) return;
  spPending = true;
  setTimeout(() => { spPending = false; spScan(); }, 30);
}).observe(document.body, {childList: true, subtree: true});
spScan();

// 設定 › 系統：一次把所有拖拉過的大小恢復預設
(() => {
  const fs = [...document.querySelectorAll("#form fieldset")].find(f => f.querySelector("legend").textContent === "系統");
  if (!fs) return;
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn ghost"; b.style.gridColumn = "1/-1";
  b.textContent = "↺ 所有面板大小恢復預設（拖拉過的分隔線、K 線副圖高度）";
  b.onclick = () => {
    if (!confirm("把所有拖拉調整過的面板大小恢復預設？（畫面會重新整理）")) return;
    try { Object.keys(localStorage).filter(k => /^(split_|asideW_|paneH_)/.test(k)).forEach(k => localStorage.removeItem(k)); } catch(e) {}
    location.reload();
  };
  fs.appendChild(b);
})();
