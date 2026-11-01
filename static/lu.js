// ---------- 當沖策略研究頁（每個研究一個資料庫／分頁）----------
let LU = null;
const STUDIES = [["long", "📈 漲停隔天做多"], ["short", "📉 漲停隔天放空"]];
let luStudy = (() => { try { const v = localStorage.getItem("luStudy"); return v === "short" ? v : "long"; } catch(e) { return "long"; } })();
const luPct = (v, d = 2) => v == null ? "–" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, d)}%</span>`;
const luBar = (v, max, color) => `<div class="lu-bar"><i style="width:${Math.min(100, v / max * 100)}%;background:${color}"></i><span>${fmt(v, 1)}%</span></div>`;

async function luShow(){
  if (!LU) {
    try { LU = await api("/api/limitup"); } catch(e) { setTimeout(luShow, 3000); return; }
  }
  luRender();
  luStatus();
}

function luRender(){
  $("luStudies").innerHTML = `<select class="sub-sel">${STUDIES.map(([k, n]) => `<option value="${k}" ${k === luStudy ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  $("luStudies").querySelector("select").onchange = e => { luStudy = e.target.value; try { localStorage.setItem("luStudy", luStudy); } catch(err) {} luRender(); };
  if (window.renderPages) renderPages();
  if (!LU || LU.error) { $("luBody").innerHTML = `<div class="k" style="padding:20px">${LU ? LU.error : ""}</div>`; return; }
  if (luStudy === "short") return luRenderShort();
  const d = LU.daily, i = LU.intraday, c = LU.candidates;
  const h = [];
  $("luInfo").innerHTML = `「五天內第一根漲停」（收盤收漲停、前 4 天沒收漲停）的隔天做多｜日K樣本 <b>${d.n.toLocaleString()}</b> 次（${d.stocks.toLocaleString()} 檔，${d.period[0]} ~ ${d.period[1]}）` +
    (i ? `｜5分K樣本 <b>${i.n.toLocaleString()}</b> 次（${i.period[0]} ~ ${i.period[1]}）` : "") + `｜統計時間 ${LU.updated}`;

  // ① 明天要注意的股票
  h.push(`<div class="lu-box"><div class="lu-title">🎯 明天的漲停隔日股（${c.date} 收盤「五天內第一根漲停」，共 ${c.rows.length} 檔）
      <span class="k">點代號可看 K 線</span></div>
    <div class="lu-cands">${c.rows.map(r => `<span class="lu-cand" data-c="${r.code}"><b>${r.code}</b> ${r.name}
      <span class="k">${fmt(r.close)}｜${r.lots.toLocaleString()}張｜${r.lu_type}</span></span>`).join("") || `<span class="k">沒有</span>`}</div>
    <div class="lu-guide">${luGuide(d)}</div></div>`);

  // ② 隔天走勢分布
  const maxp = Math.max(...d.patterns.map(p => p.pct));
  h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">① 漲停隔天的走勢分布（日K，${d.n.toLocaleString()} 次）</div>
    <table class="lu-t"><tr><th>隔天走勢</th><th>機率</th><th>次數</th><th>平均開盤</th><th>平均最高</th><th>平均收盤</th><th>開盤買→收盤</th></tr>
    ${d.patterns.map(p => `<tr><td>${p.pattern}</td><td>${luBar(p.pct, maxp, p.close >= 0 ? "#f23645" : "#089981")}</td><td>${p.n.toLocaleString()}</td>
      <td>${luPct(p.gap)}</td><td>${luPct(p.high)}</td><td>${luPct(p.close)}</td><td>${luPct(p.o2c)}</td></tr>`).join("")}</table>
    <div class="lu-kpis">${Object.entries(d.overall).map(([k, v]) => `<div><span class="k">${k}</span><b>${luPct(v.avg)}</b><span class="k">中位 ${luPct(v.med)}｜>0 機率 ${fmt(v.up, 0)}%</span></div>`).join("")}
      <div><span class="k">隔天續漲停</span><b>${fmt(d.lu_next, 1)}%</b></div></div></div>
    <div class="lu-box side"><div class="lu-title">② 依漲停當天的型態</div>
    <table class="lu-t"><tr><th>型態</th><th>次數</th><th>隔天開盤</th><th>收盤</th><th>開盤買→收盤</th><th>收紅率</th><th>續漲停</th></tr>
    ${d.by_type.map(r => `<tr><td>${r.lu_type}</td><td>${r.n.toLocaleString()}</td><td>${luPct(r.gap)}</td><td>${luPct(r.close)}</td><td>${luPct(r.o2c)}</td><td>${fmt(r.red, 0)}%</td><td>${fmt(r.lu, 0)}%</td></tr>`).join("")}</table>
    <div class="lu-title" style="margin-top:10px">③ 各年度</div>
    <table class="lu-t"><tr><th>年</th><th>次數</th><th>隔天開盤</th><th>收盤</th><th>開盤買→收盤</th><th>續漲停</th></tr>
    ${d.by_year.map(r => `<tr><td>${r.year}</td><td>${r.n.toLocaleString()}</td><td>${luPct(r.gap)}</td><td>${luPct(r.close)}</td><td>${luPct(r.o2c)}</td><td>${fmt(r.lu, 0)}%</td></tr>`).join("")}</table></div></div>`);

  // ③ 開盤買（長期日K）
  h.push(`<div class="lu-box"><div class="lu-title">④ 隔天「開盤價買」當沖：依開盤幅度（日K 長期統計，已扣當沖成本 0.435%；開盤就鎖漲停買不到，已排除）</div>
    <table class="lu-t"><tr><th>隔天開盤</th><th>次數</th><th>收盤賣</th><th>停利+2%</th><th>停利+3%</th><th>停利+5%</th><th>盤中碰到 +2%</th><th>+3%</th><th>+4%</th><th>+5%</th></tr>
    ${d.open_tp.map(r => `<tr class="${r.gap === "全部" ? "lu-all" : ""}"><td>${r.gap}</td><td>${r.n.toLocaleString()}</td>
      ${["close", "tp2", "tp3", "tp5"].map(k => `<td>${luPct(r[k].avg)}<span class="k">／勝率 ${fmt(r[k].win, 0)}%</span></td>`).join("")}
      ${[2, 3, 4, 5].map(t => `<td>${fmt(r["reach" + t], 0)}%</td>`).join("")}</tr>`).join("")}</table>
    <div class="k">「停利 +x%」＝開盤買進後盤中只要漲到買價 +x% 就賣，沒漲到就收盤賣（用日K最高價判斷）。「盤中碰到 +x%」＝當天最高價有沒有到開盤價 +x%。</div></div>`);

  // ④ 5分K 買法比較
  if (i) {
    const g = i.grid.slice().sort((a, b) => b.avg - a.avg);
    const top = (k, n = 1) => i.grid.slice().sort((a, b) => b[k] - a[k]).slice(0, n);
    const bw = top("win")[0], ba = top("avg")[0];
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">⑤ 用 5 分K 比較各種買法 × 賣法（近 3 個月 ${i.n.toLocaleString()} 次，已扣當沖成本）</div>
      <div class="lu-hl"><div>🏆 勝率最高：<b>${bw.entry_name} → ${bw.exit_name}</b>　勝率 <b>${fmt(bw.win, 1)}%</b>、平均 ${luPct(bw.avg)}</div>
        <div>💰 平均最賺：<b>${ba.entry_name} → ${ba.exit_name}</b>　平均 ${luPct(ba.avg)}、勝率 ${fmt(ba.win, 1)}%</div></div>
      <div class="lu-scroll"><table class="lu-t"><tr><th>買法</th><th>賣法</th><th>成交率</th><th>平均</th><th>中位</th><th>勝率</th><th>獲利因子</th><th>最差一筆</th></tr>
      ${g.map(r => `<tr><td>${r.entry_name}</td><td>${r.exit_name}</td><td>${fmt(r.fill, 0)}%</td><td>${luPct(r.avg)}</td><td>${luPct(r.med)}</td>
        <td>${fmt(r.win, 1)}%</td><td>${r.pf ?? "–"}</td><td>${luPct(r.worst)}</td></tr>`).join("")}</table></div></div>
      <div class="lu-box side"><div class="lu-title">⑥ 開盤價買進後</div>
      <table class="lu-t"><tr><th>漲到買價</th><th>30分鐘內</th><th>全天</th></tr>
      ${Object.entries(i.reach).map(([t, v]) => `<tr><td>+${t}%</td><td>${luBar(v.m30, 100, "#f23645")}</td><td>${luBar(v.day, 100, "#ff8a80")}</td></tr>`).join("")}</table>
      <div class="k">開盤買→收盤：平均 ${luPct(i.open_close)}、中位 ${luPct(i.open_med)}、勝率 ${fmt(i.open_win, 1)}%<br>開盤後 30 分鐘內平均最低 ${luPct(i.l30_avg)}（買進後通常會先被洗）</div>
      <div class="lu-title" style="margin-top:10px">⑦ 依隔天開盤幅度：最好的買法（5分K）</div>
      ${i.by_gap.map(r => `<div class="lu-gap"><b>${r.gap}</b> <span class="k">${r.n} 次｜開盤買→收盤 ${luPct(r.open_close)}｜30分內 +3% 機率 ${r.h30_3 ?? "–"}%</span><br>
        ${r.best_win ? `勝率最高：${r.best_win.name}（${fmt(r.best_win.win, 0)}%、平均 ${luPct(r.best_win.avg)}）<br>` : ""}
        ${r.best_avg ? `平均最賺：${r.best_avg.name}（平均 ${luPct(r.best_avg.avg)}、勝率 ${fmt(r.best_avg.win, 0)}%）` : ""}</div>`).join("")}</div></div>`);
  }
  $("luBody").innerHTML = h.join("");
  document.querySelectorAll(".lu-cand").forEach(e => e.onclick = () => { showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
}

// 給明天的操作建議（依長期日K統計自動產生）
function luGuide(d){
  const row = name => d.open_tp.find(r => r.gap === name);
  const dn3 = row("開低 >3%"), dn0 = row("開低 0~3%"), up = ["開高 0~2%", "開高 2~4%", "開高 4~6%"].map(row).filter(Boolean), up6 = row("開高 6~9.4%");
  const best = r => ["close", "tp2", "tp3", "tp5"].reduce((a, k) => r[k].avg > r[a].avg ? k : a, "close");
  const nm = {close: "抱到收盤", tp2: "停利 +2%", tp3: "停利 +3%", tp5: "停利 +5%"};
  return `<b>📋 依明天開盤幅度怎麼做（長期統計）</b><ul>
    ${dn3 ? `<li><b class="up">開低超過 3%</b>：開盤價買，${nm[best(dn3)]} → 平均 ${luPct(dn3[best(dn3)].avg)}、勝率 ${fmt(dn3[best(dn3)].win, 0)}%（${dn3.n.toLocaleString()} 次，每一年都是正的）</li>` : ""}
    ${dn0 ? `<li><b>開低 0~3%</b>：開盤買→收盤平均 ${luPct(dn0.close.avg)}，優勢不大</li>` : ""}
    ${up.length ? `<li><b class="down">開高 0~6%</b>：開盤追買平均都是負的（${up.map(r => luPct(r.close.avg)).join("、")}）；要做的話用「停利 +2~3%」勝率約 ${fmt(Math.min(...up.map(r => r.tp2.win)), 0)}~${fmt(Math.max(...up.map(r => r.tp2.win)), 0)}%，但期望值仍略負</li>` : ""}
    ${up6 ? `<li><b class="down">開高 6% 以上</b>：不要追，開盤買平均 ${luPct(up6.close.avg)}</li>` : ""}
    <li>開盤就鎖漲停：買不到，不考慮</li></ul>`;
}

async function luStatus(){
  const s = await api("/api/limitup/status").catch(() => null);
  if (!s) return;
  $("luCompute").disabled = $("luFetch").disabled = s.running;
  if (s.running) { $("luStatus").textContent = s.msg; luStatus.was = true; setTimeout(luStatus, 1500); return; }
  if (luStatus.was) { luStatus.was = false; LU = null; await luShow(); }
  $("luStatus").textContent = s.error ? "⚠ " + s.error : "";
}
$("luCompute").onclick = async () => { await post("/api/limitup/compute", {fetch5m: false}); luStatus.was = true; setTimeout(luStatus, 500); };
$("luFetch").onclick = async () => {
  if (!confirm("會從 Yahoo Finance 下載近 60 天所有漲停股的 5 分K（約 800 檔，需要幾分鐘），再重新統計。確定？")) return;
  await post("/api/limitup/compute", {fetch5m: true}); luStatus.was = true; setTimeout(luStatus, 500);
};


// ===== 漲停隔天放空 =====
function luRenderShort(){
  const s = LU.short, d = s.daily, i = s.intraday, c = LU.candidates;
  $("luInfo").innerHTML = `「五天內第一根漲停」的隔天放空（現股當沖先賣後買，成本 0.435%；被軋到漲停最多虧到漲停價）｜日K樣本 <b>${LU.daily.n.toLocaleString()}</b> 次` +
    (i ? `｜5分K樣本 <b>${i.n.toLocaleString()}</b> 次（${i.period[0]} ~ ${i.period[1]}）` : "") + `｜統計時間 ${LU.updated}`;
  const row = name => d.open_tp.find(r => r.gap === name);
  const g69 = row("開高 6~9.4%"), glu = row("開盤漲停"), g46 = row("開高 4~6%"), g24 = row("開高 2~4%"), gdn = row("開低 >3%");
  const cr = (gap, val) => d.cross.find(x => x.gap === gap && x.val === val);
  const lock69 = cr("開高 6~9.4%", "一字鎖死");
  const h = [];
  h.push(`<div class="lu-box"><div class="lu-title">🎯 明天的漲停隔日股（${c.date} 收盤，共 ${c.rows.length} 檔）<span class="k">點代號可看 K 線</span></div>
    <div class="lu-cands">${c.rows.map(r => `<span class="lu-cand" data-c="${r.code}"><b>${r.code}</b> ${r.name}
      <span class="k">${fmt(r.close)}｜${r.lots.toLocaleString()}張｜${r.lu_type}</span></span>`).join("") || `<span class="k">沒有</span>`}</div>
    <div class="lu-guide"><b>📋 放空怎麼做（長期日K驗證過的規則優先）</b><ul>
      ${g69 ? `<li><b class="down">開高 6~9.4%</b>：開盤價放空、收盤回補 → 平均 ${luPct(g69.close.avg)}、勝率 ${fmt(g69.close.win, 0)}%；改成「跌 3% 回補」勝率 ${fmt(g69.tp3.win, 0)}%、平均 ${luPct(g69.tp3.avg)}（${g69.n.toLocaleString()} 次）。但有 ${fmt(g69.squeeze, 0)}% 機率盤中被軋到漲停，要設停損</li>` : ""}
      ${lock69 ? `<li><b class="down">前一天一字鎖死＋隔天開高 6~9.4%</b>：開盤放空收盤回補平均 ${luPct(lock69.close)}、勝率 ${fmt(lock69.win, 0)}%（${lock69.n} 次）← 最強的放空組合</li>` : ""}
      ${glu ? `<li><b>開盤就漲停</b>：用漲停價放空，平均 ${luPct(glu.close.avg)}，但勝率只有 ${fmt(glu.close.win, 0)}%（大多數會一路鎖住小賠，少數打開大跌），適合小部位</li>` : ""}
      ${g46 && g24 ? `<li><b>開高 2~6%</b>：開盤放空大約打平（${luPct(g24.close.avg)}、${luPct(g46.close.avg)}），沒有優勢</li>` : ""}
      ${gdn ? `<li><b class="up">開低超過 3%：不要空</b>，開盤放空平均 ${luPct(gdn.close.avg)}、勝率只有 ${fmt(gdn.close.win, 0)}%（這時反而是做多的機會）</li>` : ""}
      ${i && i.grid.length ? `<li><b>盤中訊號（5分K）</b>：${i.grid[0].entry_name} → ${i.grid[0].exit_name} 平均 ${luPct(i.grid[0].avg)}、勝率 ${fmt(i.grid[0].win, 0)}%（${i.grid[0].n} 次，近 3 個月，樣本少僅供參考）</li>` : ""}
    </ul></div></div>`);

  // ① 長期：開盤放空 依開盤幅度
  h.push(`<div class="lu-box"><div class="lu-title">① 隔天「開盤價放空」當沖：依開盤幅度（日K 長期統計，已扣成本）</div>
    <table class="lu-t"><tr><th>隔天開盤</th><th>次數</th><th>收盤回補</th><th>跌2%回補</th><th>跌3%回補</th><th>跌5%回補</th><th>盤中跌到 -2%</th><th>-3%</th><th>-4%</th><th>-5%</th><th>被軋到漲停</th></tr>
    ${d.open_tp.map(r => `<tr class="${r.gap === "全部" ? "lu-all" : ""}"><td>${r.gap}</td><td>${r.n.toLocaleString()}</td>
      ${["close", "tp2", "tp3", "tp5"].map(k => `<td>${luPct(r[k].avg)}<span class="k">／勝率 ${fmt(r[k].win, 0)}%</span></td>`).join("")}
      ${[2, 3, 4, 5].map(t => `<td>${fmt(r["drop" + t], 0)}%</td>`).join("")}<td class="${r.squeeze > 30 ? "up" : ""}">${fmt(r.squeeze, 0)}%</td></tr>`).join("")}</table>
    <div class="k">「跌 x% 回補」＝開盤放空後盤中只要跌到放空價 -x% 就回補，沒跌到就收盤補（用日K最低價判斷）。「被軋到漲停」＝當天最高價有碰到漲停價。</div></div>`);

  // ② 長期：條件細分
  const crossT = nm => `<table class="lu-t"><tr><th>隔天開盤</th><th>${nm}</th><th>次數</th><th>收盤回補</th><th>勝率</th><th>跌3%回補</th><th>勝率</th></tr>
    ${d.cross.filter(x => x.cond === nm).map(x => `<tr><td>${x.gap}</td><td>${x.val}</td><td>${x.n.toLocaleString()}</td><td>${luPct(x.close)}</td>
      <td>${fmt(x.win, 0)}%</td><td>${luPct(x.tp3)}</td><td>${fmt(x.win3, 0)}%</td></tr>`).join("")}</table>`;
  h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">② 開高 2% 以上：依「漲停當天量能」（長期驗證）</div>${crossT("漲停當天量能")}</div>
    <div class="lu-box grow"><div class="lu-title">③ 開高 2% 以上：依「漲停型態」（長期驗證）</div>${crossT("漲停型態")}</div></div>`);

  if (i) {
    // ④ 5分K：放空方法比較
    h.push(`<div class="lu-row"><div class="lu-box grow"><div class="lu-title">④ 用 5 分K 比較放空方法 × 回補方法（近 3 個月 ${i.n.toLocaleString()} 次，已扣成本）</div>
      <div class="k" style="margin-bottom:6px">「平盤下比例」＝放空價低於前一天收盤的比例（平盤以下放空可能受限）；「只算平盤上」＝排除平盤下進場後的結果</div>
      <div class="lu-scroll"><table class="lu-t"><tr><th>放空方法</th><th>回補方法</th><th>出現率</th><th>平均</th><th>勝率</th><th>獲利因子</th><th>最差</th><th>平盤下比例</th><th>只算平盤上</th></tr>
      ${i.grid.map(r => `<tr><td>${r.entry_name}</td><td>${r.exit_name}</td><td>${fmt(r.fill, 0)}%</td><td>${luPct(r.avg)}</td><td>${fmt(r.win, 1)}%</td>
        <td>${r.pf ?? "–"}</td><td>${luPct(r.worst)}</td><td>${fmt(r.below_pct, 0)}%</td>
        <td>${r.above ? `${luPct(r.above.avg)}<span class="k">／${fmt(r.above.win, 0)}%（${r.above.n}）</span>` : "–"}</td></tr>`).join("")}</table></div></div>
      <div class="lu-box side"><div class="lu-title">⑤ 開盤價放空後</div>
      <table class="lu-t"><tr><th>跌到放空價</th><th>30分鐘內</th><th>全天</th></tr>
      ${Object.entries(i.drop).map(([t, v]) => `<tr><td>-${t}%</td><td>${luBar(v.m30, 100, "#089981")}</td><td>${luBar(v.day, 100, "#4db6ac")}</td></tr>`).join("")}</table>
      <div class="k">開盤放空→收盤回補：平均 ${luPct(i.open_close)}、勝率 ${fmt(i.open_win, 1)}%</div>
      <div class="lu-title" style="margin-top:10px">⑥ 前三名放空方法：各種條件下的表現</div>
      ${i.conds.map(cd => `<div class="lu-gap"><b>${cd.name}</b><table class="lu-t">
        ${cd.rows.map(r => `<tr><td>${r.cond}</td><td>${r.val}</td><td>${r.n}</td><td>${luPct(r.avg)}</td><td>${fmt(r.win, 0)}%</td></tr>`).join("")}</table></div>`).join("")}
      <div class="k">只列「進場當下已經知道」的條件，不會用到未來資訊</div></div></div>`);
    // ⑦ 自動找出的組合
    const combo = (title, arr) => `<div class="lu-box grow"><div class="lu-title">${title}</div>
      <table class="lu-t"><tr><th>放空方法</th><th>條件</th><th>次數</th><th>平均</th><th>勝率</th><th>前半段</th><th>後半段</th></tr>
      ${arr.map(x => `<tr><td>${x.name}</td><td>${x.cond}</td><td>${x.n}</td><td>${luPct(x.avg)}</td><td>${fmt(x.win, 0)}%</td><td>${luPct(x.avg1)}</td><td>${luPct(x.avg2)}</td></tr>`).join("")}</table></div>`;
    h.push(`<div class="lu-row">${combo("⑦ 自動找出：平均最賺的條件組合", i.best_avg)}${combo("⑧ 自動找出：勝率最高的條件組合（≥40 次）", i.best_win)}</div>
      <div class="k" style="margin:-4px 0 12px">前半段 ${i.split[0]} ~ ${i.split[1]}、後半段 ~ ${i.split[2]}，兩段都賺錢才列出。⚠ 近 3 個月、每組只有幾十筆，又是從大量組合中挑出來的，容易「看起來很準」，請以 ①~③ 長期驗證的規則為主</div>`);
  }
  $("luBody").innerHTML = h.join("");
  document.querySelectorAll(".lu-cand").forEach(e => e.onclick = () => { showPage("macd"); setTimeout(() => select(e.dataset.c), 300); });
}


// 💡 想法 已移到獨立頁面「研究想法」（ideas.js）
