// ---------- 📝 筆記（依日期，一天一格）----------
let NOTES = null, notesQ = "", notesShowN = 24;
const notesTimers = {};
const wd = d => "日一二三四五六"[new Date(d + "T00:00:00").getDay()];
const todayStr = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };

async function notesShow(){
  if (!NOTES) {
    try { NOTES = await api("/api/notes"); } catch(e) { setTimeout(notesShow, 3000); return; }
  }
  notesRender();
}

function notesRender(){
  const today = todayStr();
  const dates = [...new Set([today, ...Object.keys(NOTES)])].sort().reverse();
  const q = notesQ.trim();
  const list = dates.filter(d => !q || (NOTES[d] && NOTES[d].text.includes(q)) || d.includes(q));
  $("notesGrid").innerHTML = list.slice(0, notesShowN).map(d => {
    const n = NOTES[d] || {text: "", updated: ""};
    const isToday = d === today;
    return `<div class="note-card ${isToday ? "today" : ""}">
      <div class="note-head"><b>${d.slice(5).replace("-", "/")}</b><span class="note-wd">（${wd(d)}）</span>${isToday ? `<span class="note-tag">今天</span>` : ""}
        <span class="note-st k" id="ns_${d}">${n.updated ? "更新 " + n.updated.slice(5) : ""}</span></div>
      <textarea data-d="${d}" placeholder="${isToday ? "今天的盤勢、操作、要注意的股票…" : ""}">${(n.text || "").replace(/</g, "&lt;")}</textarea></div>`;
  }).join("") + (list.length > notesShowN ? `<div class="note-more"><button class="btn ghost" id="notesMore">再顯示更早的筆記（還有 ${list.length - notesShowN} 天）</button></div>` : "");
  $("notesCount").textContent = `共 ${Object.keys(NOTES).length} 天有筆記`;
  document.querySelectorAll("#notesGrid textarea").forEach(t => t.oninput = () => {
    const d = t.dataset.d;
    $("ns_" + d).textContent = "輸入中…";
    clearTimeout(notesTimers[d]);
    notesTimers[d] = setTimeout(async () => {
      const r = await post("/api/notes", {date: d, text: t.value});
      if (t.value.trim()) NOTES[d] = {text: t.value, updated: r.updated}; else delete NOTES[d];
      const s = $("ns_" + d); if (s) s.textContent = "✅ 已儲存 " + (r.updated || "").slice(11);
      $("notesCount").textContent = `共 ${Object.keys(NOTES).length} 天有筆記`;
    }, 700);
  });
  const m = $("notesMore"); if (m) m.onclick = () => { notesShowN += 24; notesRender(); };
}

$("notesQ").oninput = () => { notesQ = $("notesQ").value; notesRender(); };
$("notesAddDate").onchange = () => {
  const d = $("notesAddDate").value; if (!d) return;
  if (!NOTES[d]) NOTES[d] = {text: "", updated: ""};
  notesQ = ""; $("notesQ").value = ""; notesRender();
  const t = document.querySelector(`#notesGrid textarea[data-d="${d}"]`); if (t) { t.scrollIntoView({block: "center"}); t.focus(); }
};
