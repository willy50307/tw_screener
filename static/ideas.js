// ---------- 💡 研究想法（獨立頁面）----------
// 隨手想到的點子 → 交給 Claude 回測 → 結果存在 data/ideas.json；每個想法有「分類」（結算日、紅黑K、處置股…）
// 處置專區的「🔬 研究想法」也共用這裡的 ideasRender（只顯示 page = disposal 的）
let IDEAS = null, ideaOpen = (() => { try { return JSON.parse(localStorage.getItem("ideaOpen") || "{}"); } catch(e) { return {}; } })();
let ideaCat = (() => { try { return localStorage.getItem("ideaCat") || "all"; } catch(e) { return "all"; } })();
const IDEA_CAT_ORDER = ["結算日", "紅黑K", "處置股", "籌碼", "型態", "未分類"];   // 常用分類排前面，其他依名稱
const ideaCell = v => typeof v === "number" ? (Math.abs(v) < 100 && !Number.isInteger(v) ? fmt(v, Math.abs(v) < 10 ? 2 : 1) : v.toLocaleString()) : (v ?? "–");
const ideaCatOf = x => x.category || (x.page === "disposal" ? "處置股" : "未分類");
// 處置專區等子頁：用下拉選單選一個想法才展開（記住每頁上次選的）
let ideaPick = (() => { try { return JSON.parse(localStorage.getItem("ideaPick") || "{}"); } catch(e) { return {}; } })();
const ideaEsc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

function ideaCats(){
  const n = {};
  (IDEAS || []).forEach(x => { const c = ideaCatOf(x); n[c] = (n[c] || 0) + 1; });
  const rank = c => { const i = IDEA_CAT_ORDER.indexOf(c); return i < 0 ? (c === "未分類" ? 999 : 50) : i; };
  return Object.keys(n).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b, "zh-Hant")).map(c => [c, n[c]]);
}
// 給上方分頁的下拉選單用
function ideaSubList(){
  return [["all", `📚 全部（${(IDEAS || []).length}）`], ...ideaCats().map(([c, n]) => [c, `${c}（${n}）`])];
}

async function ideasShow(){
  try { IDEAS = await api("/api/ideas"); } catch(e) { IDEAS = IDEAS || []; }
  if (ideaCat !== "all" && !ideaCats().some(([c]) => c === ideaCat)) ideaCat = "all";
  ideasPageRender();
}
function ideaSetCat(c){
  ideaCat = c; try { localStorage.setItem("ideaCat", c); } catch(e) {}
  ideasPageRender();
}
function ideasPageRender(){
  const cats = ideaCats();
  $("ideaTabs").innerHTML = `<select class="sub-sel">${ideaSubList().map(([k, n]) =>
    `<option value="${ideaEsc(k)}" ${k === ideaCat ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  $("ideaTabs").querySelector("select").onchange = e => ideaSetCat(e.target.value);
  $("ideaInfo").innerHTML = "隨手想到的交易想法記在這裡；告訴 Claude「幫我回測想法：…」，回測完的數據、結論會整理進來｜" +
    cats.map(([c, n]) => `<span class="ch-tag idea-cat-chip ${c === ideaCat ? "on" : ""}" data-cat="${ideaEsc(c)}">${c} ${n}</span>`).join(" ");
  $("ideaInfo").querySelectorAll("[data-cat]").forEach(t => t.onclick = () => ideaSetCat(ideaCat === t.dataset.cat ? "all" : t.dataset.cat));
  ideasRender($("ideasBody"), "all");
  if (window.renderPages) renderPages();
}

// ---------- 圖表化：重點數字、結論卡、每張表的橫條圖 ----------
// 全部從 ideas.json 的表格自動推：主要機率欄、基準（表內「基準／全部」列 → lift 反推 → 同想法其他表的基準列 → scope 文字「基準：…%」）
const ideaNum = v => typeof v === "number" && isFinite(v);
const ideaPlain = s => String(s ?? "").replace(/<[^>]+>/g, "").trim();
const ideaNorm = s => ideaPlain(s).replace(/[%％日\s（）()]/g, "");
const ideaSame = (a, b) => { a = ideaNorm(a); b = ideaNorm(b); return !!a && !!b && (a === b || (Math.min(a.length, b.length) >= 3 && (a.includes(b) || b.includes(a)))); };
const IDEA_RATE_RE = /機率|紅K|黑K|上漲|漲停/, IDEA_CNT_RE = /^(次數|樣本數|股票數)$/;
const ideaIsBase = lbl => { const s = ideaPlain(lbl); return /^[（(]?\s*(基準|全部)/.test(s) || /全部(結算日|樣本|股票)/.test(s); };
const ideaCntIdx = t => t.columns.findIndex(c => IDEA_CNT_RE.test(c));
const ideaSigned = (t, col) => t.signed ? t.signed.includes(col) : /%$/.test(col) && /開|收|報酬|平均/.test(col);
let ideaColPick = {};   // 使用者在圖表上換的欄位（ideaId|表序 → 欄序），只在這次開著時有效
// 可畫圖的欄：有數字、不是次數／lift／z
const ideaNumCols = t => t.columns.map((c, i) => i).filter(i => i > 0 && i !== ideaCntIdx(t) && !/^(lift|z)$/i.test(t.columns[i]) && t.rows.some(r => ideaNum(r[i])));
function ideaMainCol(t){
  const cs = ideaNumCols(t);
  return cs.find(i => IDEA_RATE_RE.test(t.columns[i]) && !ideaSigned(t, t.columns[i])) ?? cs.find(i => /%/.test(t.columns[i])) ?? cs[0] ?? -1;
}
function ideaCtx(x){
  const baseMap = {}, scopeBases = [];
  (x.tables || []).forEach(t => {
    const br = t.rows.find(r => ideaIsBase(r[0]));
    if (br) t.columns.forEach((c, i) => { const k = ideaNorm(c); if (i > 0 && ideaNum(br[i]) && !(k in baseMap)) baseMap[k] = br[i]; });
  });
  const s = ideaPlain(x.scope).split(/基準[：:]?/)[1];
  if (s) s.split("。")[0].split(/[、，,；;]/).forEach(p => { const g = p.match(/^\s*(.*?)\s*(-?\d+(?:\.\d+)?)\s*%/); if (g && g[1]) scopeBases.push({label: g[1].trim(), v: +g[2]}); });
  return {baseMap, scopeBases};
}
function ideaBaseFor(t, ci, ctx){
  const col = t.columns[ci], br = t.rows.find(r => ideaIsBase(r[0]));
  if (br && ideaNum(br[ci])) return br[ci];
  const li = t.columns.findIndex(c => /^lift$/i.test(c));
  if (li > 0 && ci === li - 1) {
    const q = t.rows.filter(r => ideaNum(r[ci]) && ideaNum(r[li]) && r[li] > 0).map(r => r[ci] / r[li]).sort((a, b) => a - b);
    if (q.length) return q[Math.floor(q.length / 2)];
  }
  if (ctx.baseMap[ideaNorm(col)] != null) return ctx.baseMap[ideaNorm(col)];
  const sb = ctx.scopeBases.find(b => ideaSame(b.label, col));
  return sb ? sb.v : null;
}
// 重點數字：樣本數／基準／最高條件／提升
function ideaKpi(x, ctx){
  const T = x.tables || [];
  let base = ctx.scopeBases[0] ? {...ctx.scopeBases[0]} : null;
  if (!base) for (const t of T) {
    const ci = ideaMainCol(t); if (ci < 0) continue;
    const b = ideaBaseFor(t, ci, ctx); if (b != null) { base = {label: t.columns[ci].replace(/%$/, ""), v: b}; break; }
  }
  // 候選表：主要欄的基準跟整體基準一樣（同一個母體、同一個目標）
  const cand = T.map(t => [t, ideaMainCol(t)]).filter(([t, ci]) => {
    if (ci < 0) return false;
    if (!base) return t === T.find(u => ideaMainCol(u) >= 0);
    const b = ideaBaseFor(t, ci, ctx);
    return b != null && Math.abs(b - base.v) <= Math.max(0.6, Math.abs(base.v) * 0.03);
  });
  const rows = cand.flatMap(([t, ci]) => { const n = ideaCntIdx(t);
    return t.rows.filter(r => !ideaIsBase(r[0]) && ideaNum(r[ci])).map(r => ({label: ideaPlain(r[0]), v: r[ci], n: n >= 0 ? r[n] : null, col: t.columns[ci]})); });
  const big = rows.filter(r => r.n == null || r.n >= 30);
  const best = (big.length ? big : rows).reduce((a, r) => !a || r.v > a.v ? r : a, null);
  // 樣本數：scope「共 N 筆／次」→ scope 或結論的「N 萬筆」→ 跟整體基準同母體那張表的基準列次數
  const sc = ideaPlain(x.scope), cc = (x.conclusion || []).map(ideaPlain).join("｜");
  const m = sc.match(/共\s*([\d,]+(?:\.\d+)?\s*萬?)\s*(筆|次)/) || sc.match(/([\d,]+(?:\.\d+)?\s*萬)\s*(筆)/) || cc.match(/([\d,]+(?:\.\d+)?\s*萬)\s*(筆)/);
  let n = m ? `${m[1].trim()} ${m[2]}` : null;
  if (!n) for (const [t] of cand) { const br = t.rows.find(r => ideaIsBase(r[0])), c = ideaCntIdx(t); if (br && c >= 0 && ideaNum(br[c])) { n = `${br[c].toLocaleString()} 筆`; break; } }
  return {n, base, best};
}
const ideaPctTxt = (v, signed) => `${signed && v > 0 ? "+" : ""}${fmt(v, Math.abs(v) < 10 ? 2 : 1)}%`;
function ideaKpiHtml(k){
  if (!k || (!k.base && !k.best && !k.n)) return "";
  const c = [];
  if (k.n) c.push(`<div class="ik"><div class="ik-l">樣本數</div><div class="ik-v">${k.n}</div></div>`);
  if (k.base) c.push(`<div class="ik"><div class="ik-l">基準</div><div class="ik-v">${ideaPctTxt(k.base.v)}</div><div class="ik-s">${ideaEsc(k.base.label)}</div></div>`);
  if (k.best) c.push(`<div class="ik hl"><div class="ik-l">最高條件</div><div class="ik-v ${k.base ? (k.best.v > k.base.v ? "up" : "down") : ""}">${ideaPctTxt(k.best.v)}</div>
    <div class="ik-s" title="${ideaEsc(k.best.label)}">${ideaEsc(k.best.label)}${k.best.n != null ? `<span class="ic-n">n=${k.best.n.toLocaleString()}</span>` : ""}</div></div>`);
  if (k.best && k.base && k.base.v > 0) { const d = k.best.v - k.base.v;
    c.push(`<div class="ik"><div class="ik-l">提升</div><div class="ik-v">×${fmt(k.best.v / k.base.v, 2)}</div><div class="ik-s"><span class="${cls(d)}">${d > 0 ? "+" : ""}${fmt(d, 1)}</span> 個百分點</div></div>`); }
  return `<div class="ik-strip">${c.join("")}</div>`;
}
// 結論卡：拆出開頭圖示；✅／🔑／🎯／「最強、最穩…」的前 2 則加亮
function ideaConclHtml(list){
  const items = list.map((c, i) => {
    const g = String(c).match(/^\s*(\p{Extended_Pictographic}|[↩↪→])️?\s*/u), icon = g ? g[1] : "", text = g ? String(c).slice(g[0].length) : String(c);
    let sc = /[✅🔑🎯⭐]/u.test(icon) ? 3 : /[❌⚠↩]/u.test(icon) ? -9 : 0;
    if (/最強|最穩|最明顯|最實用|最關鍵/.test(ideaPlain(text).slice(0, 30))) sc += 2;
    else if (!icon && /^<b>/.test(text) && !/^<b>[^<]*基準/.test(text)) sc += 1;
    return {i, icon, text, sc};
  });
  const hl = new Set(items.filter(o => o.sc > 0).sort((a, b) => b.sc - a.sc || a.i - b.i).slice(0, 2).map(o => o.i));
  const kind = ic => /✅/u.test(ic) ? "ok" : /❌/u.test(ic) ? "no" : /⚠/u.test(ic) ? "warn" : "";
  return `<div class="ic-sec-t">📌 結論</div><div class="ic-concl">${items.map(o =>
    `<div class="ic-c ${kind(o.icon)} ${hl.has(o.i) ? "hl" : ""}"><span class="ic-ic">${o.icon || "▸"}</span><div>${o.text}</div></div>`).join("")}</div>`;
}
// 一張表的橫條圖：條長從 0 起算，虛線＝基準；高於基準紅、低於綠（沒基準就看正負）
function ideaChartHtml(t, ci, ctx){
  const rows = t.rows.filter(r => ideaNum(r[ci]));
  if (rows.length < 2) return "";
  const col = t.columns[ci], b = ideaBaseFor(t, ci, ctx), n = ideaCntIdx(t);
  const vals = rows.map(r => r[ci]).concat(b != null ? [b] : []);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals) || 1, pos = v => (v - lo) / (hi - lo) * 100, z = pos(0);
  const sg = lo < 0, pct = /%$/.test(col);
  const val = v => pct ? ideaPctTxt(v, sg) : ideaCell(v);
  return `${b != null ? `<div class="ic-leg"><i></i>基準 ${val(b)}</div>` : ""}<div class="ic-bars">${rows.map(r => {
    const v = r[ci], isB = ideaIsBase(r[0]), ref = b != null ? b : 0;
    const k = isB ? "ic-base" : v > ref ? "ic-up" : v < ref ? "ic-down" : "ic-eq";
    return `<div class="ic-row ${k}"><div class="ic-lbl" title="${ideaEsc(ideaPlain(r[0]))}">${r[0]}${n >= 0 && ideaNum(r[n]) ? `<span class="ic-n">n=${r[n].toLocaleString()}</span>` : ""}</div>
      <div class="ic-track">${sg ? `<span class="ic-zero" style="left:${z}%"></span>` : ""}<i style="left:${Math.min(z, pos(v))}%;width:${Math.max(0.5, Math.abs(pos(v) - z))}%"></i>${b != null ? `<span class="ic-bl" style="left:${pos(b)}%"></span>` : ""}</div>
      <div class="ic-val">${val(v)}</div></div>`;
  }).join("")}</div>`;
}
function ideaTableHtml(x, t, ti, ctx){
  const td = (col, v) => ideaSigned(t, col) && typeof v === "number" ? `<td>${luPct(v)}</td>` : `<td>${ideaCell(v)}</td>`;
  const key = `${x.id}|${ti}`, cs = ideaNumCols(t), ci = ideaColPick[key] ?? ideaMainCol(t);
  const chart = ci >= 0 ? ideaChartHtml(t, ci, ctx) : "";
  return `<div class="ic-tsec"><div class="ic-thead"><div class="lu-title">${t.title}</div>
      ${chart && cs.length > 1 ? `<select class="sub-sel ic-col" data-ic="${ideaEsc(key)}">${cs.map(i => `<option value="${i}" ${i === ci ? "selected" : ""}>${t.columns[i]}</option>`).join("")}</select>` : ""}</div>
    <div class="ic-chart">${chart}</div>
    ${t.note ? `<div class="k ic-note">${t.note}</div>` : ""}
    <details class="ic-tbl" ${chart ? "" : "open"}><summary>顯示表格（${t.rows.length} 列）</summary>
      <div class="lu-scroll ic-scroll"><table class="lu-t"><thead><tr>${t.columns.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>
      ${t.rows.map(r => `<tr class="${ideaIsBase(r[0]) ? "lu-all" : ""}">${r.map((v, i) => i === 0 ? `<td>${v}</td>` : td(t.columns[i], v)).join("")}</tr>`).join("")}</tbody></table></div></details></div>`;
}
// 頁面上方的總覽：每則一張小卡（標題、分類、日期、最高 vs 基準）
function ideaOverviewHtml(items, curId){
  if (items.length < 2) return "";
  return `<div class="io-grid">${items.map(x => {
    const k = ideaKpi(x, ideaCtx(x)), b = k.base, best = k.best, mx = Math.max(best ? best.v : 0, b ? b.v : 0) || 1;
    const bar = (v, c) => `<div class="io-bar"><i class="${c}" style="width:${Math.max(2, v / mx * 100)}%"></i></div>`;
    return `<div class="io-card ${x.id === curId ? "on" : ""}" data-ov="${x.id}" title="${ideaEsc(x.title)}">
      <div class="io-top"><span class="ch-tag">${ideaEsc(ideaCatOf(x))}</span><span class="k">${x.date || ""}</span></div>
      <div class="io-title">${ideaEsc(x.title)}</div>
      ${best ? `<div class="io-num"><b class="${b ? (best.v > b.v ? "up" : "down") : ""}">${ideaPctTxt(best.v)}</b>${b ? `<span class="k">基準 ${ideaPctTxt(b.v)}${b.v > 0 ? `・×${fmt(best.v / b.v, 2)}` : ""}</span>` : ""}</div>
        ${best.v >= 0 && (!b || b.v >= 0) ? `${bar(best.v, best && b && best.v < b.v ? "down" : "up")}${b ? bar(b.v, "base") : ""}` : ""}`
        : `<div class="k io-num">${x.status || "待回測"}</div>`}
    </div>`; }).join("")}</div>`;
}

// 一則想法的卡片（標題列＋完整數據）；x._pick = 不要收合箭頭、直接展開（處置專區、回測數據頁用）
const ideaSt = s => `<span class="idea-st ${s === "已回測" ? "done" : ""}">${s || "待回測"}</span>`;
function ideaCardHtml(x){
  const ctx = ideaCtx(x);
  return `<div class="lu-box idea" data-idea="${x.id}">
      <div class="idea-head" data-tg="${x.id}">${x._pick ? "" : `<span class="idea-arrow">${ideaOpen[x.id] === true ? "▼" : "▶"}</span>`}
        <b>${x.title}</b> ${ideaSt(x.status)} <span class="k">${x.date}</span>
        ${(x.tags || []).map(t => `<span class="ch-tag">${t}</span>`).join("")}
        <span class="idea-catsel" title="分類（可直接打新的分類名稱）">📂 <input data-cat-of="${x.id}" list="ideaCatList" value="${ideaEsc(ideaCatOf(x))}"></span>
        <button class="btn ghost idea-del" data-del="${x.id}" title="刪除">🗑</button></div>
      <div class="idea-body" style="display:${!x._pick && ideaOpen[x.id] !== true ? "none" : "block"}">
        ${x.question ? `<div class="idea-q"><b>想法：</b>${x.question}</div>` : ""}
        ${ideaKpiHtml(ideaKpi(x, ctx))}
        ${x.scope ? `<div class="k ic-scope">📦 ${x.scope}</div>` : ""}
        ${x.conclusion && x.conclusion.length ? ideaConclHtml(x.conclusion) : ""}
        ${(x.tables || []).map((t, ti) => ideaTableHtml(x, t, ti, ctx)).join("")}
        ${x.caveats && x.caveats.length ? `<div class="idea-cav"><b>⚠ 注意</b><ul>${x.caveats.map(c => `<li>${c}</li>`).join("")}</ul></div>` : ""}
        <div class="idea-note"><span class="k">我的筆記：</span><textarea data-note="${x.id}" placeholder="自己的想法、之後要再驗證的…">${x.my_note || ""}</textarea></div>
      </div></div>`;
}
// 卡片上的按鈕：展開收合、刪除、改分類、筆記、圖表欄位
function ideaBindCards(el, rerender){
  el.querySelectorAll("[data-tg]").forEach(e => e.onclick = ev => {
    if (ev.target.closest("[data-del], .idea-catsel") || !e.querySelector(".idea-arrow")) return;
    const id = e.dataset.tg; ideaOpen[id] = ideaOpen[id] !== true; try { localStorage.setItem("ideaOpen", JSON.stringify(ideaOpen)); } catch(err) {}
    const b = e.nextElementSibling, open = ideaOpen[id] === true;   // 預設收合，點標題才展開；只動這一則，不整頁重畫
    b.style.display = open ? "block" : "none"; e.querySelector(".idea-arrow").textContent = open ? "▼" : "▶";
  });
  el.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    const x = IDEAS.find(i => i.id === b.dataset.del);
    if (!confirm(`刪除「${x.title}」？刪除後回測數據也會一起消失`)) return;
    await post("/api/ideas/delete", {id: x.id}); rerender();
  });
  el.querySelectorAll("[data-cat-of]").forEach(t => t.onchange = async () => {
    const category = t.value.trim() || "未分類";
    await post("/api/ideas", {id: t.dataset.catOf, category}); rerender();
  });
  el.querySelectorAll("[data-note]").forEach(t => t.onchange = () => post("/api/ideas", {id: t.dataset.note, my_note: t.value}));
  ideaBindCharts(el);
}
// 「記下新想法」表單
const ideaNewHtml = defCat => `<div class="lu-box"><div class="lu-title">✏️ 記下新想法</div>
      <div class="idea-new"><input class="ideaTitle" placeholder="一句話：例如「處置股出關當天開盤買，隔天開盤賣」">
      <textarea class="ideaQ" placeholder="細節（條件、進出場方式、想驗證什麼）"></textarea>
      <label class="k idea-newcat">分類 <input class="ideaCatIn" list="ideaCatList" value="${ideaEsc(defCat)}" placeholder="例如：結算日、紅黑K（可打新的）"></label>
      <button class="btn ideaAdd">＋ 新增</button></div>
      <div class="k">新增後狀態是「待回測」，之後跟 Claude 說「回測想法：○○○」，結果就會放進來。</div></div>`;
function ideaBindNew(el, page, rerender){
  el.querySelector(".ideaAdd").onclick = async () => {
    const title = el.querySelector(".ideaTitle").value.trim(); if (!title) return;
    const category = el.querySelector(".ideaCatIn").value.trim() || "未分類";
    await post("/api/ideas", {title, question: el.querySelector(".ideaQ").value, page: page === "all" ? (category === "處置股" ? "disposal" : "limitup") : page, category});
    rerender();
  };
}

// el：放卡片的地方；page：all（研究想法頁，依分類）／disposal（處置專區）
async function ideasRender(el, page){
  if (page !== "all" || !IDEAS) { try { IDEAS = await api("/api/ideas"); } catch(e) { IDEAS = IDEAS || []; } }
  const all = IDEAS;
  const catNames = ideaCats().map(([c]) => c);
  const card = ideaCardHtml;

  let body, ov = "";
  if (page === "all") {
    const shown = ideaCat === "all" ? catNames : [ideaCat];
    ov = ideaOverviewHtml(all.filter(x => shown.includes(ideaCatOf(x))), null);
    body = shown.map(c => {
      const items = all.filter(x => ideaCatOf(x) === c);
      if (!items.length) return "";
      return `<div class="idea-group"><div class="idea-group-title">📂 ${c} <span class="k">${items.length} 則</span></div>${items.map(card).join("")}</div>`;
    }).join("");
  } else {
    const items = all.filter(x => (x.page || "limitup") === page);
    if (ideaPick[page] && !items.some(x => x.id === ideaPick[page])) delete ideaPick[page];
    const cur = items.find(x => x.id === ideaPick[page]);
    if (page === "btideas") ov = ideaOverviewHtml(items, cur && cur.id);
    const sel = `<div class="lu-box idea-pick"><span class="k">選擇想法（${items.length} 則）</span>
      <select class="sub-sel idea-pick-sel"><option value="">— 請選擇要看的想法 —</option>${items.map(x =>
        `<option value="${x.id}" ${cur && cur.id === x.id ? "selected" : ""}>${x.date}｜${x.status || "待回測"}｜${ideaEsc(x.title)}</option>`).join("")}</select></div>`;
    body = items.length ? sel + (cur ? card({...cur, _pick: true})
      : `<div class="k" style="padding:12px 4px">從上面的選單選一個想法，就會顯示它的數據跟分析</div>`) : "";
  }
  const defCat = page === "disposal" ? "處置股" : (ideaCat === "all" ? "" : ideaCat);

  const empty = `<div class="k" style="padding:20px">還沒有想法</div>`;
  el.innerHTML = `<datalist id="ideaCatList">${catNames.map(c => `<option value="${ideaEsc(c)}">`).join("")}</datalist>
    ${ov}
    ${page === "all" ? "" : body || empty}
    ${ideaNewHtml(defCat)}
    ${page === "all" ? body || empty : ""}`;

  const rerender = () => page === "all" ? ideasShow() : ideasRender(el, page);
  ideaBindNew(el, page, rerender);
  const ps = el.querySelector(".idea-pick-sel");
  if (ps) ps.onchange = () => {
    if (ps.value) ideaPick[page] = ps.value; else delete ideaPick[page];
    try { localStorage.setItem("ideaPick", JSON.stringify(ideaPick)); } catch(err) {}
    ideasRender(el, page);
  };
  ideaBindCards(el, rerender);
  // 總覽小卡：研究想法頁 → 展開那則並捲過去；其他頁 → 等於在下拉選單選它
  el.querySelectorAll("[data-ov]").forEach(c => c.onclick = async () => {
    const id = c.dataset.ov;
    if (page === "all") { ideaOpen[id] = true; try { localStorage.setItem("ideaOpen", JSON.stringify(ideaOpen)); } catch(err) {} }
    else { ideaPick[page] = id; try { localStorage.setItem("ideaPick", JSON.stringify(ideaPick)); } catch(err) {} }
    await ideasRender(el, page);
    const box = el.querySelector(`.idea[data-idea="${id}"]`); if (box) box.scrollIntoView({behavior: "smooth", block: "start"});
  });
}
// 圖表上方的欄位選單：只重畫那一張表
function ideaBindCharts(root){
  root.querySelectorAll(".ic-col").forEach(s => s.onchange = () => {
    const [id, ti] = s.dataset.ic.split("|"), x = (IDEAS || []).find(i => i.id === id); if (!x) return;
    ideaColPick[s.dataset.ic] = +s.value;
    const sec = s.closest(".ic-tsec"), open = sec.querySelector(".ic-tbl").open, tmp = document.createElement("div");
    tmp.innerHTML = ideaTableHtml(x, x.tables[+ti], +ti, ideaCtx(x));
    const nw = tmp.firstElementChild; nw.querySelector(".ic-tbl").open = open;
    sec.replaceWith(nw); ideaBindCharts(nw);
  });
}
