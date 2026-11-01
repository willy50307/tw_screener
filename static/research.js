// ---------- 🔬 回測數據（當沖策略研究＋想法回測＋研究想法 合成一頁）----------
// 上面是依分類整理的索引（可篩選、搜尋），點一則才在底下展開完整數據；一次只開一則
// 想法存在 data/ideas.json（ideas.js 畫卡片）；漲停隔天做多／放空是 /api/limitup 的統計（lu.js 畫，#pageLu 整塊搬進來）
let rsCat = (() => { try { return localStorage.getItem("rsCat") || "all"; } catch(e) { return "all"; } })();
let rsOpenId = (() => { try { return localStorage.getItem("rsOpen") || ""; } catch(e) { return ""; } })();
let rsFold = (() => { try { return JSON.parse(localStorage.getItem("rsFold") || "{}"); } catch(e) { return {}; } })();   // 收起來的分類
const RS_CAT_ORDER = ["當沖", "隔日沖", "漲停", "處置股", "籌碼", "結算日", "選擇權", "紅黑K", "型態"];
const RS_LU = [
  {id: "lu_long", key: "long", title: "漲停隔天做多：五天內第一根漲停，隔天怎麼買", tags: ["漲停", "當沖", "日K", "5分K"],
   question: "「五天內第一根漲停」（收盤收漲停、前 4 天沒收漲停）的隔天做多：依開盤幅度、買法 × 賣法比較"},
  {id: "lu_short", key: "short", title: "漲停隔天放空：五天內第一根漲停，隔天怎麼空", tags: ["漲停", "當沖", "放空", "5分K"],
   question: "同一批漲停股隔天現股當沖先賣後買：開高幾 % 放空最好、被軋到漲停的機率"},
];

const rsSave = (k, v) => { try { localStorage.setItem(k, typeof v === "string" ? v : JSON.stringify(v)); } catch(e) {} };

// 全部項目：漲停研究 2 則＋ideas.json 每一則，統一成 {id, kind, title, cat, status, date, tags, text, sum, lift}
function rsItems(){
  const out = [];
  RS_LU.forEach(s => {
    let sum = "", n = null;
    if (LU && !LU.error) {
      if (s.key === "long") {
        const r = (LU.daily.open_tp || []).find(x => x.gap === "開低 >3%");
        n = LU.daily.n;
        if (r) sum = `開低 &gt;3% 開盤買 → 平均 ${luPct(r.close.avg)}・勝率 ${fmt(r.close.win, 0)}%`;
      } else if (LU.short) {
        const r = (LU.short.daily.open_tp || []).find(x => x.gap === "開高 6~9.4%");
        n = LU.daily.n;
        if (r) sum = `開高 6~9.4% 開盤空 → 平均 ${luPct(r.close.avg)}・勝率 ${fmt(r.close.win, 0)}%`;
      }
    }
    out.push({...s, kind: "lu", cat: "當沖", status: "已回測", date: LU && LU.updated ? String(LU.updated).slice(0, 10) : "",
      n: n != null ? `${n.toLocaleString()} 次` : "", sum, lift: null, text: s.title + s.question + s.tags.join(" ")});
  });
  (IDEAS || []).forEach(x => {
    const k = ideaKpi(x, ideaCtx(x)), b = k.base, best = k.best;
    const lift = best && b && b.v > 0 ? best.v / b.v : null;
    const sum = best ? `最高 <b class="${b ? (best.v > b.v ? "up" : "down") : ""}">${ideaPctTxt(best.v)}</b>${b ? `<span class="k">／基準 ${ideaPctTxt(b.v)}</span>` : ""}${lift ? ` <span class="rs-lift">×${fmt(lift, 2)}</span>` : ""}` : "";
    out.push({id: x.id, kind: "idea", x, title: ideaPlain(x.title), cat: ideaCatOf(x), status: x.status || "待回測", date: x.date || "",
      tags: x.tags || [], n: k.n || "", sum, lift, best: best ? ideaPlain(best.label) : "",
      text: [x.title, x.question, x.scope, ...(x.conclusion || []), ...(x.tags || []), ideaCatOf(x)].map(ideaPlain).join(" ")});
  });
  return out;
}
function rsCats(items){
  const n = {};
  items.forEach(x => n[x.cat] = (n[x.cat] || 0) + 1);
  const rank = c => { const i = RS_CAT_ORDER.indexOf(c); return i < 0 ? (c === "未分類" ? 999 : 50) : i; };
  return Object.keys(n).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b, "zh-Hant")).map(c => [c, n[c]]);
}
// 上方分頁的下拉選單
function rsSubList(){
  const it = rsItems();
  return [["all", `📚 全部（${it.length}）`], ...rsCats(it).map(([c, n]) => [c, `${c}（${n}）`])];
}
function rsSetCat(c){ rsCat = c; rsSave("rsCat", c); rsRender(); }

async function rsShow(){
  try { IDEAS = await api("/api/ideas"); } catch(e) { IDEAS = IDEAS || []; }
  rsRender();
  if (!LU) { try { LU = await api("/api/limitup"); } catch(e) {} rsRender(); }
}

// 把當沖研究那塊（#pageLu）先搬回原位，免得重畫索引時被清掉
function rsParkLu(){
  const lu = $("pageLu");
  if (lu && lu.parentElement !== document.body && lu.closest("#rsIndex")) { lu.style.display = "none"; document.body.appendChild(lu); }
}

function rsRender(){
  const all = rsItems(), cats = rsCats(all);
  if (rsCat !== "all" && !cats.some(([c]) => c === rsCat)) rsCat = "all";
  const q = ($("rsQ").value || "").trim().toLowerCase(), st = $("rsSt").value, sort = $("rsSort").value;
  $("rsCats").innerHTML = [["all", "全部", all.length], ...cats.map(([c, n]) => [c, c, n])].map(([k, nm, n]) =>
    `<span class="ch-tag rs-chip ${k === rsCat ? "on" : ""}" data-c="${ideaEsc(k)}">${nm} <b>${n}</b></span>`).join("");
  $("rsCats").querySelectorAll("[data-c]").forEach(t => t.onclick = () => rsSetCat(t.dataset.c));

  const hit = all.filter(x => (rsCat === "all" || x.cat === rsCat) && (!st || x.status === st) &&
    (!q || q.split(/\s+/).every(w => x.text.toLowerCase().includes(w))));
  const order = sort === "lift" ? (a, b) => (b.lift ?? -1) - (a.lift ?? -1) : (a, b) => (b.date || "").localeCompare(a.date || "");
  if (rsOpenId && !all.some(x => x.id === rsOpenId)) rsOpenId = "";
  $("rsCount").textContent = `${hit.length} / ${all.length} 則`;

  rsParkLu();
  const row = x => `<div class="rs-item ${x.id === rsOpenId ? "open" : ""}" data-rs="${x.id}">
      <div class="rs-row" data-rsrow="${x.id}">
        <span class="rs-arrow">${x.id === rsOpenId ? "▼" : "▶"}</span>
        <div class="rs-main"><div class="rs-title">${ideaEsc(x.title)}</div>
          <div class="rs-meta">${sort === "lift" ? `<span class="ch-tag">📂 ${ideaEsc(x.cat)}</span>` : ""}${ideaSt(x.status)}<span class="k">${x.date}</span>${x.n ? `<span class="k">樣本 ${x.n}</span>` : ""}
            ${x.tags.slice(0, 4).map(t => `<span class="ch-tag">${ideaEsc(t)}</span>`).join("")}</div></div>
        <div class="rs-sum">${x.sum || `<span class="k">${x.status === "已回測" ? "" : "還沒回測"}</span>`}${x.best ? `<div class="k rs-best" title="${ideaEsc(x.best)}">${ideaEsc(x.best)}</div>` : ""}</div>
      </div>
      ${x.id === rsOpenId ? `<div class="rs-detail" id="rsDetail"></div>` : ""}</div>`;
  // 依提升倍數排 → 不分類，整份排名；依日期 → 分類分組
  const groups = sort === "lift" ? (hit.length ? `<div class="rs-group"><div class="rs-gt">🏆 依提升倍數排名 <span class="k">${hit.length} 則（沒有基準可比的排最後）</span></div>
      <div class="rs-list">${hit.slice().sort(order).map(row).join("")}</div></div>` : "")
    : (rsCat === "all" ? cats.map(([c]) => c) : [rsCat]).map(c => {
    const items = hit.filter(x => x.cat === c).sort(order);
    if (!items.length) return "";
    const fold = rsFold[c] && !q && !items.some(x => x.id === rsOpenId);   // 搜尋中、或裡面有展開的那則 → 不收
    return `<div class="rs-group ${fold ? "fold" : ""}"><div class="rs-gt" data-g="${ideaEsc(c)}"><span class="rs-arrow">${fold ? "▶" : "▼"}</span>📂 ${c} <span class="k">${items.length} 則</span></div>
      <div class="rs-list">${items.map(row).join("")}</div></div>`;
  }).join("");
  $("rsIndex").innerHTML = `<datalist id="ideaCatList">${ideaCats().map(([c]) => `<option value="${ideaEsc(c)}">`).join("")}</datalist>` +
    (groups || `<div class="k" style="padding:20px">沒有符合的回測</div>`);
  $("rsNew").innerHTML = ideaNewHtml(rsCat === "all" || rsCat === "當沖" ? "" : rsCat);
  ideaBindNew($("rsNew"), "all", rsShow);

  $("rsIndex").querySelectorAll("[data-g]").forEach(g => g.onclick = () => {
    const c = g.dataset.g; rsFold[c] = !rsFold[c]; rsSave("rsFold", rsFold); rsRender();
  });
  $("rsIndex").querySelectorAll("[data-rsrow]").forEach(r => r.onclick = () => rsOpen(r.dataset.rsrow === rsOpenId ? "" : r.dataset.rsrow, true));
  rsFillDetail(all);
  if (window.renderPages) renderPages();
}

function rsOpen(id, scroll){
  rsOpenId = id; rsSave("rsOpen", id);
  rsRender();
  const box = id && $("rsIndex").querySelector(`[data-rs="${id}"]`);
  if (box && scroll) box.scrollIntoView({behavior: "smooth", block: "start"});
}

// 展開那一則的完整內容
function rsFillDetail(all){
  const el = $("rsDetail"), x = el && all.find(i => i.id === rsOpenId);
  if (!x) return;
  if (x.kind === "lu") {
    const lu = $("pageLu");
    luStudy = x.key; rsSave("luStudy", x.key);
    el.appendChild(lu); lu.style.display = "block";
    luShow();
  } else {
    el.innerHTML = ideaCardHtml({...x.x, _pick: true});
    ideaBindCards(el, rsShow);
  }
}

$("rsQ").oninput = () => rsRender();
$("rsSt").onchange = () => rsRender();
$("rsSort").onchange = () => rsRender();
