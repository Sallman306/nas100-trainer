// NAS100 Trade Trainer – practice round UI (no build step, Lightweight Charts v4 from CDN).
"use strict";

const $ = (id) => document.getElementById(id);
const SETUPS = ["sweep", "bos", "orb", "fvg_retest", "no_trade", "other"];
const BIASES = ["with", "against", "none"];
const LINE_COLORS = { entry: "#4c8dff", sl: "#ef5350", tp: "#26a69a" };
const LEVEL_COLORS = { Asian: "#b388ff", London: "#f0b429", PDH: "#90a4ae", PDL: "#90a4ae" };
const SPEED_MS = { 1: 1000, 5: 200 };
const DRAG_PX = 7;

const S = {
  L: null, lang: "en", meta: null,
  sessionId: null, drill: "", rounds: 10,
  round: null, phase: "start", // start | decide | replay | result | report
  tf: "M5", tfUsed: new Set(), decision: null, orderType: "market",
  lines: { entry: null, sl: null, tp: null }, priceLines: {}, levelLines: [],
  confidence: 3, speed: loadSpeed(), replayTimer: null, result: null, markers: [],
  dragging: null,
};

// ---------- helpers ----------
function loadSpeed() {
  try { const v = Number(localStorage.getItem("speed")); return [0, 1, 5].includes(v) ? v : 5; } catch { return 5; }
}
function saveSpeed(v) { try { localStorage.setItem("speed", String(v)); } catch { /* ignore */ } }
function t(key) { return (S.L && S.L[key]) || key; }
function fmt(x, d = 2) { return x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toFixed(d); }
function fmtR(x) { return x === null || x === undefined ? "–" : (x > 0 ? "+" : "") + Number(x).toFixed(2) + "R"; }
function pct(x) { return x === null || x === undefined ? "–" : Math.round(x * 100) + "%"; }
function hhmm(time) {
  const d = new Date(time * 1000);
  return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
}
function setMsg(text) { $("msg").textContent = text || ""; }
async function api(url, opts) {
  const res = await fetch(url, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

// ---------- labels ----------
async function loadLabels() {
  const all = await (await fetch("labels.json")).json();
  try { S.lang = localStorage.getItem("lang") || "en"; } catch { S.lang = "en"; }
  S.L = all[S.lang] || all.en;
  document.querySelectorAll("[data-l]").forEach((el) => { el.textContent = t(el.dataset.l); });
  $("selSetup").innerHTML = SETUPS.map((k) => `<option value="${k}">${S.L.setups[k]}</option>`).join("");
  $("selBias").innerHTML = BIASES.map((k) => `<option value="${k}">${S.L.biases[k]}</option>`).join("");
  $("confRow").innerHTML = [1, 2, 3, 4, 5].map((n) => `<button data-conf="${n}">${n}</button>`).join("");
}

// ---------- chart ----------
const chart = LightweightCharts.createChart($("chart"), {
  autoSize: true,
  layout: { background: { color: "#0f1218" }, textColor: "#8590a3" },
  grid: { vertLines: { color: "#1a202b" }, horzLines: { color: "#1a202b" } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: "#262d3a" },
  timeScale: { borderColor: "#262d3a", timeVisible: true, secondsVisible: false, rightOffset: 15,
    tickMarkFormatter: (time) => hhmm(time) },
  localization: { timeFormatter: (time) => hhmm(time), priceFormatter: (p) => p.toFixed(2) },
});
const series = chart.addCandlestickSeries({
  upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350",
});

function showTf(tf) {
  if (!S.round || S.phase === "replay") return;
  if (S.phase === "result" && tf !== "M5") return; // replay bars exist on M5 only
  S.tf = tf;
  if (S.phase === "decide") S.tfUsed.add(tf);
  document.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("on", b.dataset.tf === tf));
  const data = S.phase === "result" ? S.round.charts.M5.concat(S.result.replay) : S.round.charts[tf];
  series.setData(data);
  const n = S.round.charts[tf].length;
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 140), to: n + 15 });
}

function drawLevels() {
  S.levelLines.forEach((l) => series.removePriceLine(l));
  S.levelLines = S.round.levels.map((lv) => series.createPriceLine({
    price: lv.price, color: LEVEL_COLORS[lv.name.split(" ")[0]] || "#90a4ae", lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: lv.name,
  }));
}

function drawTradeLines() {
  for (const k of ["entry", "sl", "tp"]) {
    const price = S.lines[k];
    if (price === null) {
      if (S.priceLines[k]) { series.removePriceLine(S.priceLines[k]); delete S.priceLines[k]; }
      continue;
    }
    const opts = { price, color: LINE_COLORS[k], lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true, title: t(k).toUpperCase() };
    if (S.priceLines[k]) S.priceLines[k].applyOptions(opts);
    else S.priceLines[k] = series.createPriceLine(opts);
  }
}

// ---------- dragging trade lines ----------
function lineNear(y) {
  if (S.phase !== "decide" || !S.decision || S.decision === "skip") return null;
  let best = null, bestD = DRAG_PX;
  for (const k of ["entry", "sl", "tp"]) {
    if (S.lines[k] === null) continue;
    const c = series.priceToCoordinate(S.lines[k]);
    if (c !== null && Math.abs(c - y) <= bestD) { best = k; bestD = Math.abs(c - y); }
  }
  return best;
}
function localY(e) { return e.clientY - $("chart").getBoundingClientRect().top; }
function startDrag(e) {
  const k = lineNear(localY(e));
  if (!k) return;
  S.dragging = k;
  chart.applyOptions({ handleScroll: false, handleScale: false });
  e.preventDefault(); e.stopPropagation();
}
$("chart").addEventListener("mousedown", startDrag, true);
$("chart").addEventListener("pointerdown", (e) => { if (lineNear(localY(e))) { e.stopPropagation(); } }, true);
window.addEventListener("mousemove", (e) => {
  if (!S.dragging) { $("chart").classList.toggle("near-line", !!lineNear(localY(e))); return; }
  const p = series.coordinateToPrice(localY(e));
  if (p === null) return;
  S.lines[S.dragging] = Math.round(p * 4) / 4;
  if (S.dragging === "entry") S.orderType = "pending";
  syncInputs(); drawTradeLines(); updatePlan();
});
window.addEventListener("mouseup", () => {
  if (!S.dragging) return;
  S.dragging = null;
  chart.applyOptions({ handleScroll: true, handleScale: true });
});

// ---------- decision panel ----------
function syncInputs() {
  $("inEntry").value = S.lines.entry ?? "";
  $("inSl").value = S.lines.sl ?? "";
  $("inTp").value = S.lines.tp ?? "";
}

function orderValid() {
  const { entry, sl, tp } = S.lines;
  if ([entry, sl, tp].some((v) => v === null || Number.isNaN(v))) return false;
  return S.decision === "long" ? sl < entry && entry < tp : tp < entry && entry < sl;
}

function updatePlan() {
  const { entry, sl, tp } = S.lines;
  const risk = Math.abs(entry - sl);
  $("rrOut").textContent = risk > 0 ? fmt(Math.abs(tp - entry) / risk) : "–";
  $("riskOut").textContent = fmt(risk, 1);
  $("btnMarket").classList.toggle("on", S.orderType === "market");
  const fill = S.decision === "long" ? S.round.price + S.round.spread : S.round.price - S.round.spread;
  $("orderType").textContent = S.orderType === "market"
    ? `${t("market").replace(/ \(.*\)/, "")} @ ${fmt(S.round.price)} → fill ${fmt(fill)} (spread ${S.round.spread})`
    : `${t("pending")} @ ${fmt(entry)} – fills only if touched before ${S.round.timeout}`;
  setMsg(orderValid() ? "" : t(S.decision === "long" ? "invalid_long" : "invalid_short"));
}

function decide(d) {
  if (S.phase !== "decide") return;
  S.decision = d;
  $("btnLong").classList.toggle("on", d === "long");
  $("btnShort").classList.toggle("on", d === "short");
  $("btnSkip").classList.toggle("on", d === "skip");
  if (d === "skip") {
    S.lines = { entry: null, sl: null, tp: null };
    $("orderBox").hidden = true; setMsg("");
  } else {
    const p = S.round.price, a = S.round.atr, sign = d === "long" ? 1 : -1;
    S.orderType = "market";
    S.lines = { entry: p, sl: round4(p - sign * a), tp: round4(p + sign * a * S.round.min_rr) };
    $("orderBox").hidden = false;
    syncInputs(); updatePlan();
  }
  drawTradeLines();
}
function round4(x) { return Math.round(x * 4) / 4; }

function setMarket() {
  if (S.phase !== "decide" || !S.decision || S.decision === "skip") return;
  S.orderType = "market"; S.lines.entry = S.round.price;
  syncInputs(); drawTradeLines(); updatePlan();
}

function onPriceInput(k, value) {
  if (S.phase !== "decide") return;
  const v = parseFloat(value);
  S.lines[k] = Number.isNaN(v) ? null : v;
  if (k === "entry") S.orderType = v === S.round.price ? "market" : "pending";
  drawTradeLines(); updatePlan();
}

function setConfidence(n) {
  S.confidence = n;
  document.querySelectorAll("[data-conf]").forEach((b) => b.classList.toggle("on", Number(b.dataset.conf) === n));
}
function cycleSelect(id) {
  const el = $(id);
  el.selectedIndex = (el.selectedIndex + 1) % el.options.length;
}
function setSpeed(v) {
  S.speed = v; saveSpeed(v);
  document.querySelectorAll("[data-speed]").forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === v));
  if (S.phase === "replay") restartReplayTimer();
}

function lockInputs(locked) {
  document.querySelectorAll("#decidePanel input, #decidePanel select").forEach((el) => { el.disabled = locked; });
  document.querySelectorAll("#decidePanel button:not([data-speed])").forEach((el) => { el.disabled = locked; });
}

// ---------- rounds ----------
async function nextRound() {
  const q = new URLSearchParams();
  if (S.sessionId) q.set("session_id", S.sessionId);
  if (S.drill) q.set("drill", S.drill);
  q.set("rounds", S.rounds);
  const r = await api("/api/round/next?" + q.toString());
  S.sessionId = r.session_id;
  if (r.done) return showReport();
  S.round = r; S.result = null; S.phase = "decide";
  S.decision = null; S.orderType = "market"; S.lines = { entry: null, sl: null, tp: null };
  S.tfUsed = new Set(); S.markers = [];
  series.setMarkers([]);
  drawTradeLines(); drawLevels();
  $("resultPanel").hidden = true; $("decidePanel").hidden = false; $("orderBox").hidden = true;
  ["btnLong", "btnShort", "btnSkip"].forEach((id) => $(id).classList.remove("on"));
  $("selSetup").value = "other"; $("selBias").value = "none"; $("inNote").value = ""; setConfidence(3);
  lockInputs(false); setMsg(t("choose"));
  const drill = r.drill ? ` · ${t("drill")}: ${S.L.setups[r.drill] || r.drill}` : "";
  $("roundInfo").textContent = `${t("round")} ${r.round_no}/${r.total_rounds}${drill}`;
  showTf("M5");
}

async function commit() {
  if (S.phase !== "decide") return;
  if (!S.decision) { setMsg(t("choose")); return; }
  if (S.decision !== "skip" && !orderValid()) { updatePlan(); return; }
  const form = {
    decision: S.decision, order_type: S.orderType,
    entry: S.lines.entry, sl: S.lines.sl, tp: S.lines.tp,
    setup_tag: $("selSetup").value, bias_tag: $("selBias").value, confidence: S.confidence,
    note: $("inNote").value, tf_used: [...S.tfUsed],
  };
  lockInputs(true);
  S.phase = "replay";
  setMsg(t("locked"));
  document.activeElement && document.activeElement.blur();
  try {
    S.result = await api(`/api/round/${S.round.round_id}/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
  } catch (err) {
    S.phase = "decide"; lockInputs(false); setMsg(err.message); return;
  }
  startReplay();
}

// ---------- replay ----------
function buildMarkers() {
  const r = S.result, m = [];
  const bucket = (time) => time - (time % 300);
  if (r.fill_time !== null && r.fill_time !== undefined) {
    m.push({ time: bucket(r.fill_time), position: S.decision === "long" ? "belowBar" : "aboveBar",
      color: "#4c8dff", shape: S.decision === "long" ? "arrowUp" : "arrowDown", text: "fill " + fmt(r.fill_price) });
  }
  if (r.exit_time !== null && r.exit_time !== undefined && r.exit_reason !== "not_filled") {
    m.push({ time: bucket(r.exit_time), position: "aboveBar", color: r.result_r > 0 ? "#26a69a" : "#ef5350",
      shape: "circle", text: `${r.exit_reason} ${fmtR(r.result_r)}` });
  }
  return m.sort((a, b) => a.time - b.time);
}

function startReplay() {
  S.tf = "M5";
  document.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("on", b.dataset.tf === "M5"));
  series.setData(S.round.charts.M5);
  S.markers = buildMarkers();
  S.replayIndex = 0;
  restartReplayTimer();
}

function restartReplayTimer() {
  clearInterval(S.replayTimer);
  if (S.speed === 0) { while (replayStep()) { /* instant */ } return; }
  S.replayTimer = setInterval(() => { if (!replayStep()) clearInterval(S.replayTimer); }, SPEED_MS[S.speed]);
}

function replayStep() {
  const bars = S.result.replay;
  if (S.phase !== "replay") return false;
  if (S.replayIndex >= bars.length) { finishRound(); return false; }
  const bar = bars[S.replayIndex++];
  series.update(bar);
  series.setMarkers(S.markers.filter((m) => m.time <= bar.time));
  return true;
}

function finishRound() {
  clearInterval(S.replayTimer);
  S.phase = "result";
  series.setMarkers(S.markers);
  renderResult();
}

function renderResult() {
  const r = S.result;
  const cls = r.result_r > 0 ? "pos" : r.result_r < 0 ? "neg" : "";
  const check = (key) => (r[key] === null || r[key] === undefined ? "" :
    `<div class="${r[key] ? "ok" : "ko"}">${t(key)}</div>`);
  const isTrade = r.decision !== "skip";
  const levelTxt = r.level_name ? ` · ${r.level_name} ${fmt(r.level_price)}` : "";
  const dir = r.direction_hint && r.direction_hint !== "none" ? ` (${r.direction_hint})` : "";
  $("resultPanel").innerHTML = `
    <div class="card">
      <div class="label">${t("result")}</div>
      <div class="big ${cls}">${isTrade ? fmtR(r.result_r) : S.L.reasons[r.exit_reason]}</div>
      <div><span class="label">${t("exit_reason")}:</span> ${S.L.reasons[r.exit_reason] || r.exit_reason}
        ${isTrade && r.filled ? ` · MFE ${fmt(r.mfe_r)}R / MAE ${fmt(r.mae_r)}R` : ""}</div>
      <div><span class="label">${t("best")}:</span> ${r.best_side} ${fmtR(r.best_possible_r)}</div>
      <div><span class="label">${t("detector")}:</span> <b>${S.L.setups[r.detector] || r.detector}</b>${dir}${levelTxt}
        ${r.also_detected ? `<span class="label"> + ${r.also_detected}</span>` : ""}</div>
      <div><span class="label">${t("h1_trend")}:</span> ${r.h1_trend}</div>
      <div><span class="label">${t("real_time")}:</span> ${r.freeze_time_ny}</div>
    </div>
    ${isTrade ? `<div class="card"><div class="label">${t("plan")} (R:R ${fmt(r.rr_planned)})</div>
      ${check("rr_ok")}${check("sl_beyond_swing")}${check("with_bias")}</div>` : ""}
    <button id="btnNext" class="on">${r.session_done ? t("to_report") : t("next")}</button>`;
  $("resultPanel").hidden = false; $("decidePanel").hidden = true;
  $("btnNext").onclick = advance;
}

function advance() {
  if (S.phase !== "result") return;
  if (S.result.session_done) showReport(); else nextRound().catch((e) => setMsg(e.message));
}

// ---------- session report (Phase 4 extends) ----------
async function showReport() {
  S.phase = "report";
  const rep = await api(`/api/session/${S.sessionId}/report`);
  const s = rep.stats;
  $("overlayBox").innerHTML = `
    <h2>${t("report")}</h2>
    <table>
      <tr><td>${t("trades")}</td><td>${s.trades} / ${s.rounds}</td></tr>
      <tr><td>${t("win_rate")}</td><td>${pct(s.win_rate)}</td></tr>
      <tr><td>${t("total_r")}</td><td>${fmtR(s.total_r)}</td></tr>
      <tr><td>${t("avg_r")}</td><td>${fmtR(s.avg_r)}</td></tr>
      <tr><td>${t("skip_accuracy")}</td><td>${pct(s.skip_accuracy)}</td></tr>
      <tr><td>${t("avg_rr")}</td><td>${fmt(s.avg_rr_planned)}</td></tr>
      <tr><td>${t("plan_quality")}</td><td>${pct(s.plan_quality)}</td></tr>
    </table>
    <button id="btnNew" class="on">${t("new_session")}</button>`;
  $("overlay").hidden = false;
  $("btnNew").onclick = () => location.reload();
}

// ---------- start screen ----------
async function initStart() {
  S.meta = await api("/api/meta");
  $("selDrill").innerHTML = `<option value="">${t("drill_all")}</option>` +
    S.meta.detectors.map((d) => `<option value="${d}">${S.L.setups[d] || d}</option>`).join("");
  $("inRounds").value = S.meta.session_rounds;
  $("btnStart").onclick = startSession;
}

async function startSession() {
  if (S.phase !== "start") return;
  S.drill = $("selDrill").value;
  S.rounds = Math.max(1, parseInt($("inRounds").value, 10) || S.meta.session_rounds);
  try {
    S.sessionId = null;
    await nextRound();
    $("overlay").hidden = true;
  } catch (err) {
    S.phase = "start"; $("startMsg").textContent = err.message;
  }
}

// ---------- keyboard ----------
document.addEventListener("keydown", (e) => {
  const inField = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
  if (e.key === "Escape") { document.activeElement?.blur(); return; }
  if (e.key === "Enter") {
    e.preventDefault();
    if (S.phase === "start") startSession();
    else if (S.phase === "decide") commit();
    else if (S.phase === "result") advance();
    else if (S.phase === "report") location.reload();
    return;
  }
  if (inField || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.shiftKey && /^Digit[1-5]$/.test(e.code)) { if (S.phase === "decide") setConfidence(Number(e.code.slice(5))); return; }
  const key = e.key.toLowerCase();
  const actions = {
    1: () => showTf("M5"), 2: () => showTf("M15"), 3: () => showTf("H1"),
    l: () => decide("long"), s: () => decide("short"), k: () => decide("skip"), m: setMarket,
    t: () => S.phase === "decide" && cycleSelect("selSetup"),
    b: () => S.phase === "decide" && cycleSelect("selBias"),
    "/": () => { if (S.phase === "decide") { e.preventDefault(); $("inNote").focus(); } },
    z: () => setSpeed(1), x: () => setSpeed(5), c: () => setSpeed(0),
  };
  if (actions[key]) actions[key]();
});

// ---------- wiring ----------
document.querySelectorAll("[data-tf]").forEach((b) => { b.onclick = () => showTf(b.dataset.tf); });
document.querySelectorAll("[data-speed]").forEach((b) => { b.onclick = () => setSpeed(Number(b.dataset.speed)); });
$("btnLong").onclick = () => decide("long");
$("btnShort").onclick = () => decide("short");
$("btnSkip").onclick = () => decide("skip");
$("btnMarket").onclick = setMarket;
$("btnCommit").onclick = commit;
$("inEntry").addEventListener("input", (e) => onPriceInput("entry", e.target.value));
$("inSl").addEventListener("input", (e) => onPriceInput("sl", e.target.value));
$("inTp").addEventListener("input", (e) => onPriceInput("tp", e.target.value));

(async () => {
  await loadLabels();
  document.querySelectorAll("#confRow [data-conf]").forEach((b) => { b.onclick = () => setConfidence(Number(b.dataset.conf)); });
  setConfidence(3); setSpeed(S.speed);
  try { await initStart(); } catch (err) { $("startMsg").textContent = err.message; }
})();
