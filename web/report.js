// NAS100 Trade Trainer – session report and all-time progress (uses helpers from app.js).
"use strict";

const SPLIT_TABS = [["detector", "split_detector"], ["side", "split_side"], ["confidence", "split_confidence"]];
const R = { tab: "session", session: null, progress: null, exportMsg: "" };

function fill(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) => (k in values ? values[k] : m));
}
function groupName(split, key) {
  if (split === "detector") return S.L.setups[key] || key;
  if (split === "side") return t(key);
  return `${t("confidence")} ${key}`;
}
function signCls(x) { return x === null || x === undefined ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "flat"; }

// ---------- building blocks ----------
function statGrid(s) {
  const items = [
    [t("trades"), `${s.trades} / ${s.rounds}`, ""],
    [t("win_rate"), pct(s.win_rate), ""],
    [t("expectancy"), fmtR(s.expectancy), signCls(s.expectancy)],
    [t("avg_r"), fmtR(s.avg_r), signCls(s.avg_r)],
    [t("total_r"), fmtR(s.total_r), signCls(s.total_r)],
    [t("max_streak"), String(s.max_losing_streak), ""],
    [t("skip_accuracy"), pct(s.skip_accuracy), ""],
    [t("avg_rr"), fmt(s.avg_rr_planned), ""],
    [t("plan_quality"), pct(s.plan_quality), ""],
  ];
  return `<div class="stat-grid">${items.map(([k, v, c]) =>
    `<div class="stat"><span class="caption">${esc(k)}</span><b class="${c}">${esc(v)}</b></div>`).join("")}</div>`;
}

function ruleValues(rule) {
  const v = { ...rule.values };
  for (const k of ["strong", "weak"]) if (k in v) v[k] = S.L.setups[v[k]] || v[k];
  return v;
}

function workOn(coaching) {
  const c = coaching;
  let body;
  if (c.work_on.length) {
    body = c.work_on.map((w, i) => {
      const txt = S.L.coach[w.key];
      return `<div class="work-item"><span class="work-no">${i + 1}</span><div>
        <b>${esc(txt.title)}</b> <span class="neg">−${fmt(w.r_lost, 1)}R</span>
        <div>${esc(fill(txt.detail, ruleValues(w)))}</div>
        <div class="advice">→ ${esc(fill(txt.advice, ruleValues(w)))}</div></div></div>`;
    }).join("");
  } else if (c.rules.every((r) => r.status === "not_enough_data")) {
    body = `<div class="sub-hint">${esc(fill(t("all_not_enough"), { need: c.min_trades, filled: c.based_on.filled }))}</div>`;
  } else {
    body = `<div class="sub-hint">${esc(t("nothing_flagged"))}</div>`;
  }
  const rules = c.rules.map((r) => {
    const tone = r.status === "work_on" ? "bad" : r.status === "ok" ? "good" : "info";
    const extra = r.status === "not_enough_data" ? ` (${fill(t("need_more"), r)})` : "";
    return { tone, text: `${S.L.coach[r.key].title}: ${t("status_" + r.status)}${extra}` };
  });
  return `<fieldset class="group"><legend>${esc(t("work_on"))}</legend>${body}
    <div class="sub-hint">${esc(fill(t("based_on"), { filled: c.based_on.filled }))}</div>
    ${sect(t("all_rules"), blist(rules), false)}</fieldset>`;
}

function splitTables(splits) {
  return SPLIT_TABS.map(([key, label]) => {
    const rows = splits[key].map((g) => `<tr><td>${esc(groupName(key, g.key))}</td><td>${g.filled}</td>
      <td>${pct(g.win_rate)}</td><td class="${signCls(g.expectancy)}">${fmtR(g.expectancy)}</td>
      <td class="${signCls(g.total_r)}">${fmtR(g.total_r)}</td><td>${pct(g.plan_quality)}</td>
      <td class="verdict ${g.verdict}">${esc(t("verdict_" + g.verdict))}</td></tr>`).join("");
    return sect(t(label), rows ? `<table class="grid"><tr><th>${t("group")}</th><th>${t("trades")}</th>
      <th>${t("win_rate")}</th><th>${t("expectancy")}</th><th>${t("total_r")}</th><th>${t("plan_quality")}</th>
      <th>${t("verdict")}</th></tr>${rows}</table>` : `<div class="sub-hint">–</div>`, key === "detector");
  }).join("");
}

// simple SVG line chart: one point per session
function lineChart(title, values, { percent = false, zero = false } = {}) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  const W = 460, H = 150, P = { l: 44, r: 10, t: 10, b: 22 };
  if (!pts.length) return `<div class="chart-box"><div class="caption">${esc(title)}</div><div class="sub-hint">–</div></div>`;
  let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (percent) { lo = 0; hi = 1; }
  if (hi === lo) { hi += 1; lo -= 1; }
  const n = Math.max(values.length - 1, 1);
  const x = (i) => P.l + (values.length === 1 ? (W - P.l - P.r) / 2 : (i / n) * (W - P.l - P.r));
  const y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
  const lab = (v) => (percent ? Math.round(v * 100) + "%" : (v > 0 ? "+" : "") + v.toFixed(2));
  const ticks = [lo, (lo + hi) / 2, hi].map((v) =>
    `<line class="gridline" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${P.l - 4}" y="${y(v) + 4}" text-anchor="end">${lab(v)}</text>`).join("");
  const zl = zero && lo < 0 && hi > 0 ? `<line class="zeroline" x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}"/>` : "";
  const path = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const dots = pts.map(([i, v]) => `<circle class="dot ${zero ? signCls(v) : ""}" cx="${x(i)}" cy="${y(v)}" r="3.5"><title>#${i + 1}: ${lab(v)}</title></circle>`).join("");
  const xl = `<text class="axis" x="${P.l}" y="${H - 6}">#1</text><text class="axis" x="${W - P.r}" y="${H - 6}" text-anchor="end">#${values.length}</text>`;
  return `<div class="chart-box"><div class="caption">${esc(title)}</div>
    <svg viewBox="0 0 ${W} ${H}" class="line-chart">${ticks}${zl}<path class="line" d="${path}"/>${dots}${xl}</svg></div>`;
}

function sessionsTable(sessions) {
  const rows = sessions.slice().reverse().map((p, k) => `<tr><td>#${sessions.length - k}</td><td>${esc(p.date)}</td>
    <td>${p.trades} / ${p.rounds}</td><td class="${signCls(p.expectancy)}">${fmtR(p.expectancy)}</td>
    <td class="${signCls(p.total_r)}">${fmtR(p.total_r)}</td><td>${pct(p.plan_quality)}</td>
    <td><button class="xp-btn small" data-export="${esc(p.session_id)}">${esc(t("export"))}</button></td></tr>`).join("");
  return `<table class="grid"><tr><th>#</th><th>${t("date")}</th><th>${t("trades")}</th><th>${t("expectancy")}</th>
    <th>${t("total_r")}</th><th>${t("plan_quality")}</th><th></th></tr>${rows}</table>`;
}

// ---------- screens ----------
function renderReport() {
  const box = $("overlayBox");
  const tabs = `<div class="tabs">
    ${R.session ? `<button class="tab ${R.tab === "session" ? "on" : ""}" data-tab="session">${t("tab_session")}</button>` : ""}
    <button class="tab ${R.tab === "alltime" ? "on" : ""}" data-tab="alltime">${t("tab_alltime")}</button></div>`;
  let body = "";
  if (R.tab === "session" && R.session) {
    body = statGrid(R.session.stats) + workOn(R.session.coaching) + splitTables(R.session.splits);
  } else if (R.progress) {
    const p = R.progress;
    body = !p.sessions.length ? `<div class="sub-hint">${t("no_sessions")}</div>` : statGrid(p.stats)
      + `<div class="charts">${lineChart(t("chart_expectancy"), p.sessions.map((s) => s.expectancy), { zero: true })}
         ${lineChart(t("chart_plan"), p.sessions.map((s) => s.plan_quality), { percent: true })}</div>`
      + workOn(p.coaching) + splitTables(p.splits) + sect(t("sessions"), sessionsTable(p.sessions), true);
  } else {
    body = `<div class="sub-hint">…</div>`;
  }
  const exportBtn = R.session ? `<button id="btnExport" class="xp-btn">${t("export")} <kbd>E</kbd></button>` : "";
  const newBtn = `<button id="btnNew" class="xp-btn go">${S.phase === "report" ? t("new_session") : t("back")} <kbd>Enter</kbd></button>`;
  box.innerHTML = `${tabs}<div class="report-scroll">${body}</div>
    <div class="report-foot">${exportBtn}<span id="exportMsg" class="sub-hint">${esc(R.exportMsg)}</span>${newBtn}</div>`;
  box.querySelectorAll("[data-tab]").forEach((b) => { b.onclick = () => switchTab(b.dataset.tab); });
  box.querySelectorAll("[data-export]").forEach((b) => { b.onclick = () => exportSession(b.dataset.export); });
  if ($("btnExport")) $("btnExport").onclick = () => exportSession(R.session.session_id);
  $("btnNew").onclick = closeReport;
}

async function switchTab(tab) {
  R.tab = tab;
  if (tab === "alltime" && !R.progress) {
    renderReport();
    R.progress = await api("/api/progress");
  }
  renderReport();
}

async function exportSession(sessionId) {
  R.exportMsg = t("exporting"); renderReport();
  try {
    const res = await api(`/api/session/${encodeURIComponent(sessionId)}/export`, { method: "POST" });
    R.exportMsg = fill(t("exported"), { path: res.path });
  } catch (err) { R.exportMsg = err.message; }
  renderReport();
}

function openDialog(title) {
  $("dialogTitle").textContent = title;
  $("overlay").querySelector(".dialog").classList.add("wide");
  $("overlay").hidden = false;
}

/** Session report after the last round (all-time tab one click away). */
async function showReport() {
  setPhase("report");
  R.tab = "session"; R.progress = null; R.exportMsg = "";
  R.session = await api(`/api/session/${S.sessionId}/report`);
  openDialog(t("report"));
  renderReport();
}

/** All-time progress, opened from the start screen. */
async function showProgress() {
  setPhase("progress");
  R.tab = "alltime"; R.session = null; R.exportMsg = ""; R.progress = null;
  openDialog(t("progress"));
  renderReport();
  try { R.progress = await api("/api/progress"); } catch (err) { R.exportMsg = err.message; }
  renderReport();
}

/** Leave the report: a fresh start screen. */
function closeReport() { location.reload(); }

function reportKey(key) {
  if (key === "e" && R.session) { exportSession(R.session.session_id); return true; }
  if (key === "tab") { if (R.session) switchTab(R.tab === "session" ? "alltime" : "session"); return true; }
  return false;
}
