// ---------- 頁面（最上方分頁）----------
// 每個頁面一個分頁：點分頁打開、再點一次收回首頁。頁面清單存在設定（settings.json 的 pages）。
let curPage = (() => { const u = new URLSearchParams(location.search).get("page"); if (u) return u;   // 網址 ?page=quote 可以直接開某一頁
  try { return localStorage.getItem("page") || "home"; } catch(e) { return "home"; } })();
let editingPage = null;

const pagesList = () => (S && S.settings.pages) || [];

// 每個大標題底下的小分頁：[清單, 目前選的, 切換方法]
const SUBPAGES = {
  strategy: {list: () => allTabs(), cur: () => tab, go: k => { tab = k; sortKey = null; renderTabs(); renderList(); }},
  chips: {list: () => CH_TABS, cur: () => chTab, go: k => { chTab = k; try { localStorage.setItem("chTab", k); } catch(e) {} chShow(); }},
  disposal: {list: () => [["chart", "📈 個股K線"], ["ideas", "🔬 研究想法"]], cur: () => (typeof dView !== "undefined" ? dView : "chart"), go: k => dShowView(k)},
  research: {list: () => rsSubList(), cur: () => rsCat, go: k => rsSetCat(k)},
  quote: {list: () => Q_SUBS.map(([k, n]) => [k, n]), cur: () => qSub, go: k => qGo(k)},
  options: {list: () => OPT_SUBS.map(([k, n]) => [k, n]), cur: () => optSub, go: k => optGo(k)},
};
function subName(pg){
  const s = SUBPAGES[pg.type]; if (!s || pg.id !== curPage) return "";
  const x = s.list().find(([k]) => k === s.cur());
  return x ? `<span class="pg-sub">› ${x[1]}</span>` : "";
}
function renderPages(){
  $("pages").innerHTML = pagesList().map(pg => {
    const s = SUBPAGES[pg.type];
    const btn = `<button class="pg ${pg.id === curPage ? "on" : ""}" data-id="${pg.id}" title="點一下打開／再點一次收合；按右鍵可改名">${pg.icon || "📄"} ${pg.name}${subName(pg)}${s ? `<span class="pg-caret" data-caret="${pg.id}">▾</span>` : ""}</button>`;
    if (!s) return btn;
    return `<span class="pgw" data-w="${pg.id}">${btn}<div class="pgmenu">${s.list().map(([k, n]) =>
      `<div data-pg="${pg.id}" data-sub="${k}" class="${pg.id === curPage && k === s.cur() ? "on" : ""}">${n}</div>`).join("")}</div></span>`;
  }).join("") + `<button class="pg add" id="pgAdd" title="新增頁面">＋</button>`;
  document.querySelectorAll("#pages .pg[data-id]").forEach(b => {
    b.onclick = e => {
      if (e.target.closest("[data-caret]")) { e.stopPropagation(); b.parentElement.classList.toggle("open"); return; }
      showPage(b.dataset.id === curPage ? "home" : b.dataset.id);
    };
    b.oncontextmenu = e => { e.preventDefault(); openPageDlg(b.dataset.id); };
  });
  document.querySelectorAll("#pages [data-sub]").forEach(m => m.onclick = e => {
    e.stopPropagation();
    const pg = pagesList().find(p => p.id === m.dataset.pg), s = SUBPAGES[pg.type];
    document.querySelectorAll("#pages .pgw.open").forEach(w => w.classList.remove("open"));
    if (curPage !== pg.id) {
      if (pg.type === "disposal") { showPage(pg.id); setTimeout(() => s.go(m.dataset.sub), 50); }
      else if (pg.type === "strategy") { showPage(pg.id); s.go(m.dataset.sub); }
      else if (pg.type === "research") { rsCat = m.dataset.sub; try { localStorage.setItem("rsCat", rsCat); } catch(err) {} showPage(pg.id); }
      else if (pg.type === "quote") { qSub = m.dataset.sub; try { localStorage.setItem("qSub", qSub); } catch(err) {} showPage(pg.id); }
      else if (pg.type === "options") { optSub = m.dataset.sub; optSave("optSub", optSub); showPage(pg.id); }
      else { if (pg.type === "chips") chTab = m.dataset.sub; s.go(m.dataset.sub); showPage(pg.id); }
    } else s.go(m.dataset.sub);
    renderPages();
  });
  $("pgAdd").onclick = () => openPageDlg(null);
}
document.addEventListener("click", e => { if (!e.target.closest(".pgw")) document.querySelectorAll("#pages .pgw.open").forEach(w => w.classList.remove("open")); });

function renderHome(){
  const c = S ? S.counts : {};
  $("home").innerHTML = `<div class="home-title">選擇要打開的頁面</div><div class="cards">` +
    pagesList().map(pg => `<div class="card" data-id="${pg.id}">
      <div class="ic">${pg.icon || "📄"}</div><div class="nm">${pg.name}</div>
      <div class="ds">${pg.type === "strategy"
        ? `今日訊號 ${c.signal ?? 0} 檔｜明日觀察 ${c.watch ?? 0} 檔｜處置預測 ${c.fc ?? 0} 檔`
        : pg.type === "disposal" ? "8/10 新制後被處置過的股票：處置前、處置中、出關後的走勢"
        : pg.type === "sentiment" ? "PTT 盤中／盤後閒聊的市場情緒分數、關鍵字統計"
        : pg.type === "research" ? "所有回測一頁看：當沖、隔日沖、漲停、處置股、籌碼、結算日…依分類整理，可搜尋、篩選，點一則看完整數據"
        : pg.type === "notes" ? "依日期寫自己的盤勢筆記，一天一格"
        : pg.type === "live" ? "盤中族群多空、資金流向、量能激增股、周轉率排行"
        : pg.type === "futures" ? "全部期貨合約即時行情（成交、買賣價、未平倉增減），點一檔看五檔、明細、走勢"
        : pg.type === "options" ? "臺指選擇權：即時 T 字報價＋Greeks、定價模型、歷史資料（結算日逐分還原 Call／Put 價格）"
        : pg.type === "quote" ? "群益即時報價：自選股、四格看盤（五檔、即時明細、走勢圖）、錄影重播"
        : pg.type === "chips" ? "三大法人、隔日沖分點、資金流向、融資券借券、土洋同步（每晚 7 點後自動抓）" : "空白頁面"}</div></div>`).join("") +
    `<div class="card add" id="cardAdd"><div class="ic">＋</div><div class="nm">新增頁面</div><div class="ds">之後可以放別的策略或功能</div></div></div>`;
  document.querySelectorAll("#home .card[data-id]").forEach(d => d.onclick = () => showPage(d.dataset.id));
  $("cardAdd").onclick = () => openPageDlg(null);
}

function showPage(id){
  if (id !== curPage && typeof sidePanel !== "undefined" && sidePanel === "br") closeSide();   // 換頁就收起主力進出，點了股票才再打開
  const pg = pagesList().find(p => p.id === id);
  if (!pg) id = "home";
  curPage = id;
  try { localStorage.setItem("page", id); } catch(e) {}
  const type = pg ? pg.type : "home";
  $("home").style.display = type === "home" ? "block" : "none";
  $("pageStrategy").style.display = type === "strategy" ? "flex" : "none";
  $("pageBlank").style.display = type === "blank" ? "flex" : "none";
  $("pageDisp").style.display = type === "disposal" ? "flex" : "none";
  $("pageMood").style.display = type === "sentiment" ? "block" : "none";
  $("pageChips").style.display = type === "chips" ? "block" : "none";
  $("pageNotes").style.display = type === "notes" ? "block" : "none";
  $("pageResearch").style.display = type === "research" ? "block" : "none";   // 當沖策略研究（#pageLu）點開時會搬進這頁
  if (type === "research") rsShow();
  $("pageLive").style.display = type === "live" ? "block" : "none";
  if (type === "live") liveShow();
  $("pageQuote").style.display = type === "quote" ? "flex" : "none";
  $("pageFut").style.display = type === "futures" ? "flex" : "none";
  const optWas = $("pageOpt").style.display !== "none" && $("pageOpt").style.display !== "";
  $("pageOpt").style.display = type === "options" ? "flex" : "none";
  window.CUR_PAGE = type;
  if (type === "options" && !optWas) optShow();
  if (type !== "options") olStop();
  if (type === "quote") qShow(); else { clearTimeout(qTimer); if (qRep) qRepPause(); }
  if (type === "futures") fuShow(); else fuStop();
  if (type === "notes") notesShow();
  if (type === "chips") chShow();
  if (type === "sentiment") moodShow();
  document.querySelectorAll(".s-only, #sub").forEach(e => e.style.display = type === "strategy" ? "" : "none");
  document.querySelectorAll(".sd-only").forEach(e => e.style.display = (type === "strategy" || type === "disposal") ? "" : "none");
  if (type !== "strategy" && type !== "disposal") closeSide();
  if (type === "disposal") dispShow();
  if (type === "home") renderHome();
  if (type === "blank") $("pageBlank").innerHTML = `<div class="blank-box"><div class="ic">${pg.icon || "📄"}</div>
    <h2>${pg.name}</h2><p>這是空白頁面。</p>
    <p class="k">告訴 Claude 你想在這一頁放什麼（例如：另一套選股策略、處置股專區、回測報表…），就會幫你做出來。<br>
    按上方分頁的右鍵可以改名或刪除。</p></div>`;
  window.CUR_PAGE = type;
  if (type === "strategy" || type === "disposal") setTimeout(() => ChartView.resizeAll(), 0);  // 讓 K 線圖重新抓大小
  renderPages();
}

function openPageDlg(id){
  editingPage = id;
  const pg = pagesList().find(p => p.id === id);
  $("dlgPageTitle").textContent = pg ? "編輯頁面" : "新增頁面";
  $("formPage").elements.name.value = pg ? pg.name : "";
  $("formPage").elements.icon.value = pg ? (pg.icon || "📄") : "📄";
  $("btnPageDel").style.display = pg && pg.type === "blank" ? "" : "none";   // 內建頁面不可刪
  $("dlgPage").showModal();
}

async function savePages(pages){
  await post("/api/settings", {pages});
  S = await api("/api/state");
}

$("btnPageCancel").onclick = () => $("dlgPage").close();
$("formPage").onsubmit = async e => {
  e.preventDefault();
  const f = $("formPage").elements, name = f.name.value.trim(), icon = f.icon.value.trim() || "📄";
  if (!name) return;
  let pages = pagesList().map(p => ({...p}));
  let target = editingPage;
  if (editingPage) pages.find(p => p.id === editingPage).name = name, pages.find(p => p.id === editingPage).icon = icon;
  else { target = "p" + Date.now(); pages.push({id: target, name, type: "blank", icon}); }
  $("dlgPage").close();
  await savePages(pages);
  showPage(target);
};
$("btnPageDel").onclick = async () => {
  const pg = pagesList().find(p => p.id === editingPage);
  if (!pg || pg.type !== "blank" || !confirm(`確定刪除「${pg.name}」頁面？`)) return;
  $("dlgPage").close();
  await savePages(pagesList().filter(p => p.id !== editingPage));
  showPage("home");
};
$("homeBtn").onclick = () => showPage("home");

// 等設定載入後再顯示
(function waitState(){ if (S) showPage(curPage); else setTimeout(waitState, 100); })();
