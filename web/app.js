// NAS100 Trade Trainer – practice round UI (no build step, Lightweight Charts v4 from CDN).
"use strict";

const $ = (id) => document.getElementById(id);
const SETUPS = ["sweep", "bos", "orb", "fvg_retest", "no_trade", "other"];
const BIASES = ["with", "against", "none"];
const LINE = {
  entry: { color: "#0050ef", width: 2, style: 0 },
  sl: { color: "#e00000", width: 3, style: 0 },
  tp: { color: "#00d000", width: 3, style: 0 },
};
const LEVEL_COLORS = { Asian: "#8e44ad", London: "#d98200", PDH: "#555555", PDL: "#555555" };
const EVENT_COLORS = { level: "#8e44ad", extreme: "#0050ef", candle: "#e08a00", move: "#009090" };
const SPEED_MS = { 1: 600, 5: 120 };
const DRAG_PX = 8;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const CHART_THEMES = {
  light: { layout: { background: { color: "#ffffff" }, textColor: "#222" },
    grid: { vertLines: { color: "#eeeeee" }, horzLines: { color: "#eeeeee" } } },
  dark: { layout: { background: { color: "#161618" }, textColor: "#cfcfcf" },
    grid: { vertLines: { color: "#262628" }, horzLines: { color: "#262628" } } },
};

const S = {
  L: null, lang: "en", meta: null,
  sessionId: null, drill: "", rounds: 10,
  round: null, phase: "start", // start | decide | replay | result | report
  tf: "M5", tfUsed: new Set(), decision: null, orderType: "market",
  lines: { entry: null, sl: null, tp: null }, priceLines: {}, levelLines: [], extraLines: [],
  confidence: 3, speed: loadSpeed(), replayTimer: null, replayIndex: 0, result: null, markers: [],
  dragging: null, nowTime: null, theme: loadTheme(), showIdeal: false, idealLines: [],
};

// ---------- helpers ----------
function loadSpeed() {
  try { const v = Number(localStorage.getItem("speed")); return [0, 1, 5].includes(v) ? v : 5; } catch { return 5; }
}
function saveSpeed(v) { try { localStorage.setItem("speed", String(v)); } catch { /* ignore */ } }
function loadTheme() { try { return localStorage.getItem("theme") === "dark" ? "dark" : "light"; } catch { return "light"; } }
function t(key) { return (S.L && S.L[key]) || key; }
function fmt(x, d = 2) { return x === null || x === undefined || Number.isNaN(Number(x)) ? "–" : Number(x).toFixed(d); }
function fmtR(x) { return x === null || x === undefined ? "–" : (x > 0 ? "+" : "") + Number(x).toFixed(2) + "R"; }
function pct(x) { return x === null || x === undefined ? "–" : Math.round(x * 100) + "%"; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function hhmm(time) {
  const d = new Date(time * 1000);
  return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
}
function dayHhmm(time) { return WEEKDAYS[new Date(time * 1000).getUTCDay()] + " " + hhmm(time); }
function mt5(time) { return hhmm(time + (S.round ? S.round.mt5_offset_min * 60 : 0)); }
function round4(x) { return Math.round(x * 4) / 4; }
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
  $("confRow").innerHTML = [1, 2, 3, 4, 5].map((n) => `<button class="xp-btn" data-conf="${n}">${n}</button>`).join("");
}

// ---------- chart ----------
const chart = LightweightCharts.createChart($("chart"), {
  autoSize: true,
  layout: { background: { color: "#ffffff" }, textColor: "#222", fontFamily: "Tahoma, Segoe UI, sans-serif", fontSize: 12 },
  grid: { vertLines: { color: "#eeeeee" }, horzLines: { color: "#eeeeee" } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: "#a0a0a0" },
  timeScale: {
    borderColor: "#a0a0a0", timeVisible: true, secondsVisible: false, rightOffset: 20,
    // day boundaries show the weekday, everything else the New York clock time
    tickMarkFormatter: (time, type) => (type <= LightweightCharts.TickMarkType.DayOfMonth
      ? WEEKDAYS[new Date(time * 1000).getUTCDay()] : hhmm(time)),
  },
  localization: { timeFormatter: (time) => dayHhmm(time) + " ET", priceFormatter: (p) => p.toFixed(2) },
});
const series = chart.addCandlestickSeries({
  upColor: "#2e9e5b", downColor: "#e0413c", borderUpColor: "#1f7a43", borderDownColor: "#b22a26",
  wickUpColor: "#1f7a43", wickDownColor: "#b22a26",
});

function applyTheme(name) {
  S.theme = name;
  document.documentElement.dataset.theme = name;
  chart.applyOptions(CHART_THEMES[name]);
  $("btnTheme").innerHTML = `${name === "dark" ? "☀ " + t("theme_light") : "🌙 " + t("theme_dark")} <kbd>D</kbd>`;
  try { localStorage.setItem("theme", name); } catch { /* ignore */ }
}

chart.subscribeCrosshairMove((param) => {
  $("clockCursor").textContent = param.time
    ? `${t("cursor")}: ${dayHhmm(param.time)} ET · MT5 ${mt5(param.time)}` : `${t("cursor")}: –`;
});

function updateClock() {
  if (!S.round) { $("clockFreeze").textContent = ""; return; }
  const now = S.nowTime ?? S.round.freeze_time + 300; // close of the last visible M5 candle
  const label = S.phase === "decide" ? t("frozen_at") : t("now");
  $("clockFreeze").textContent = `${label}: ${dayHhmm(now)} ET · MT5 ${mt5(now)}`;
}

function showTf(tf) {
  if (!S.round || S.phase === "replay") return;
  if (S.phase === "result" && tf !== "M5") return; // replay bars exist on M5 only
  S.tf = tf;
  if (S.phase === "decide") S.tfUsed.add(tf);
  document.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("on", b.dataset.tf === tf));
  const data = S.phase === "result" ? S.round.charts.M5.concat(S.result.replay) : S.round.charts[tf];
  series.setData(data);
  if (S.phase === "result") series.setMarkers(S.markers);
  const n = S.round.charts[tf].length;
  const extra = S.phase === "result" ? S.result.replay.length : 0;
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 130), to: n + extra + 20 });
}

function drawLevels() {
  S.levelLines.forEach((l) => series.removePriceLine(l));
  S.levelLines = S.round.levels.map((lv) => series.createPriceLine({
    price: lv.price, color: LEVEL_COLORS[lv.name.split(" ")[0]] || "#555", lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: lv.name,
  }));
}

function lineTitle(k) {
  const { entry, sl, tp } = S.lines;
  const risk = Math.abs(entry - sl);
  if (k === "tp" && risk > 0) return `TP  +${fmt(Math.abs(tp - entry) / risk, 1)}R`;
  if (k === "sl") return "SL  -1R";
  return S.orderType === "market" ? "ENTRY (mkt)" : "ENTRY (limit)";
}

function drawTradeLines() {
  for (const k of ["entry", "sl", "tp"]) {
    const price = S.lines[k];
    if (price === null) {
      if (S.priceLines[k]) { series.removePriceLine(S.priceLines[k]); delete S.priceLines[k]; }
      continue;
    }
    const opts = { price, color: LINE[k].color, lineWidth: LINE[k].width, lineStyle: LINE[k].style,
      axisLabelVisible: true, title: lineTitle(k) };
    if (S.priceLines[k]) S.priceLines[k].applyOptions(opts);
    else S.priceLines[k] = series.createPriceLine(opts);
  }
}

function clearExtraLines() {
  S.extraLines.forEach((l) => series.removePriceLine(l));
  S.extraLines = [];
}

// ---------- risk / reward zones (redrawn every frame so they follow pan/zoom) ----------
function drawZones() {
  const rw = $("zoneReward"), rk = $("zoneRisk");
  const ideal = S.showIdeal && S.result ? S.result.explain.ideal : null;
  const { entry, sl, tp } = ideal || S.lines;
  const show = S.round && (ideal || (S.decision && S.decision !== "skip")) && entry !== null && sl !== null && tp !== null;
  if (!show) { rw.hidden = true; rk.hidden = true; return; }
  const x0 = chart.timeScale().timeToCoordinate((ideal && ideal.entry_time) || S.round.freeze_time);
  const right = $("chart").clientWidth - chart.priceScale("right").width();
  const left = Math.max(0, x0 === null ? 0 : x0);
  const y = (p) => series.priceToCoordinate(p);
  const [ye, ys, yt] = [y(entry), y(sl), y(tp)];
  if ([ye, ys, yt].some((v) => v === null) || right <= left) { rw.hidden = true; rk.hidden = true; return; }
  const h = $("chart").clientHeight - chart.timeScale().height();
  place(rw, left, right, Math.min(ye, yt), Math.abs(yt - ye), h);
  place(rk, left, right, Math.min(ye, ys), Math.abs(ys - ye), h);
  // the reward zone's bright edge sits on the TP side
  rw.style.borderTop = yt < ye ? "2px solid #00d000" : "0"; rw.style.borderBottom = yt > ye ? "2px solid #00d000" : "0";
}
function place(el, left, right, top, height, maxY) {
  const bottom = Math.min(top + height, maxY);
  top = Math.max(0, top); height = Math.max(0, bottom - top);
  el.hidden = height <= 0;
  Object.assign(el.style, { left: left + "px", width: right - left + "px", top: top + "px", height: height + "px" });
}
(function loop() { drawZones(); requestAnimationFrame(loop); })();

// ---------- dragging trade lines ----------
function lineNear(y) {
  if (S.phase !== "decide" || !S.decision || S.decision === "skip") return null;
  let best = null, bestD = DRAG_PX;
  for (const k of ["tp", "sl", "entry"]) {
    if (S.lines[k] === null) continue;
    const c = series.priceToCoordinate(S.lines[k]);
    if (c !== null && Math.abs(c - y) <= bestD) { best = k; bestD = Math.abs(c - y); }
  }
  return best;
}
function localY(e) { return e.clientY - $("chart").getBoundingClientRect().top; }
$("chart").addEventListener("mousedown", (e) => {
  const k = lineNear(localY(e));
  if (!k) return;
  S.dragging = k;
  chart.applyOptions({ handleScroll: false, handleScale: false });
  e.preventDefault(); e.stopPropagation();
}, true);
$("chart").addEventListener("pointerdown", (e) => { if (lineNear(localY(e))) e.stopPropagation(); }, true);
window.addEventListener("mousemove", (e) => {
  if (!S.dragging) { $("chart").classList.toggle("near-line", !!lineNear(localY(e))); return; }
  const p = series.coordinateToPrice(localY(e));
  if (p === null) return;
  S.lines[S.dragging] = round4(p);
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

function showOrderInputs(on) {
  document.querySelectorAll("#orderBox .order-grid, #orderBox .readout, #orderType").forEach((el) => { el.hidden = !on; });
  $("noOrder").hidden = on;
}

function updatePlan() {
  const { entry, sl, tp } = S.lines;
  const risk = Math.abs(entry - sl);
  $("rrOut").textContent = risk > 0 ? fmt(Math.abs(tp - entry) / risk) : "–";
  $("riskOut").textContent = fmt(risk, 1);
  $("rewardOut").textContent = fmt(Math.abs(tp - entry), 1);
  $("btnMarket").classList.toggle("on", S.orderType === "market");
  const fill = S.decision === "long" ? S.round.price + S.round.spread : S.round.price - S.round.spread;
  $("orderType").textContent = S.orderType === "market"
    ? `${t("market_fill")} ${fmt(S.round.price)} → ${fmt(fill)} (spread ${S.round.spread})`
    : `${t("pending")} @ ${fmt(entry)} – ${t("pending_hint")} ${S.round.timeout} ET`;
  setMsg(orderValid() ? "" : t(S.decision === "long" ? "invalid_long" : "invalid_short"));
  drawTradeLines();
}

function decide(d) {
  if (S.phase !== "decide") return;
  S.decision = d;
  $("btnLong").classList.toggle("on", d === "long");
  $("btnShort").classList.toggle("on", d === "short");
  $("btnSkip").classList.toggle("on", d === "skip");
  $("decisionHint").textContent = t("hint_" + d);
  if (d === "skip") {
    S.lines = { entry: null, sl: null, tp: null };
    showOrderInputs(false); $("noOrder").textContent = t("no_order_skip"); setMsg("");
  } else {
    const p = S.round.price, a = S.round.atr, sign = d === "long" ? 1 : -1;
    S.orderType = "market";
    S.lines = { entry: p, sl: round4(p - sign * a), tp: round4(p + sign * a * S.round.min_rr) };
    showOrderInputs(true);
    syncInputs(); updatePlan();
  }
  drawTradeLines();
}

function setMarket() {
  if (S.phase !== "decide" || !S.decision || S.decision === "skip") return;
  S.orderType = "market"; S.lines.entry = S.round.price;
  syncInputs(); updatePlan();
}

function onPriceInput(k, value) {
  if (S.phase !== "decide") return;
  const v = parseFloat(value);
  S.lines[k] = Number.isNaN(v) ? null : v;
  if (k === "entry") S.orderType = v === S.round.price ? "market" : "pending";
  updatePlan();
}

function setConfidence(n) {
  S.confidence = n;
  document.querySelectorAll("[data-conf]").forEach((b) => b.classList.toggle("on", Number(b.dataset.conf) === n));
}
function cycleSelect(id) { const el = $(id); el.selectedIndex = (el.selectedIndex + 1) % el.options.length; }
function setSpeed(v) {
  S.speed = v; saveSpeed(v);
  document.querySelectorAll("[data-speed]").forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === v));
  if (S.phase === "replay") restartReplayTimer();
}

function lockInputs(locked) {
  document.querySelectorAll("#decidePanel input, #decidePanel select, #decidePanel button").forEach((el) => { el.disabled = locked; });
}
function setPhase(phase) {
  S.phase = phase;
  $("phaseInfo").textContent = t("phase_" + phase);
  updateClock();
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
  S.round = r; S.result = null; S.nowTime = null;
  S.decision = null; S.orderType = "market"; S.lines = { entry: null, sl: null, tp: null };
  S.tfUsed = new Set(); S.markers = [];
  setPhase("decide");
  series.setMarkers([]); clearExtraLines(); S.showIdeal = false; drawIdeal();
  drawTradeLines(); drawLevels();
  $("zoneReward").classList.remove("flash"); $("zoneRisk").classList.remove("flash");
  $("resultPanel").hidden = true; $("decidePanel").hidden = false; $("side").classList.remove("wide");
  ["btnLong", "btnShort", "btnSkip"].forEach((id) => $(id).classList.remove("on"));
  showOrderInputs(false); $("noOrder").textContent = t("no_order");
  $("decisionHint").textContent = t("choose");
  $("selSetup").value = "other"; $("selBias").value = "none"; $("inNote").value = ""; setConfidence(3);
  lockInputs(false); setMsg("");
  const drill = r.drill ? ` · ${t("drill")}: ${S.L.setups[r.drill] || r.drill}` : "";
  $("roundInfo").textContent = `${t("round")} ${r.round_no} / ${r.total_rounds}${drill}`;
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
  setPhase("replay");
  setMsg("");
  document.activeElement && document.activeElement.blur();
  try {
    S.result = await api(`/api/round/${S.round.round_id}/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
  } catch (err) {
    setPhase("decide"); lockInputs(false); setMsg(err.message); return;
  }
  startReplay();
}

// ---------- replay ----------
function buildMarkers() {
  const r = S.result, m = [];
  const bucket = (time) => time - (time % 300);
  if (r.fill_time !== null && r.fill_time !== undefined) {
    m.push({ time: bucket(r.fill_time), position: S.decision === "long" ? "belowBar" : "aboveBar",
      color: "#0050ef", shape: S.decision === "long" ? "arrowUp" : "arrowDown", text: "FILL " + fmt(r.fill_price) });
  }
  if (r.exit_time !== null && r.exit_time !== undefined && r.exit_reason !== "not_filled") {
    m.push({ time: bucket(r.exit_time), position: "aboveBar", color: r.result_r > 0 ? "#00a000" : "#e00000",
      shape: "circle", text: `${r.exit_reason.toUpperCase()} ${fmtR(r.result_r)}` });
  }
  for (const e of r.explain.events) {
    if (!e.label) continue;
    const below = e.label === "low" || / (L|PDL)/.test(e.label);
    m.push({ time: bucket(e.time), position: below ? "belowBar" : "aboveBar",
      color: EVENT_COLORS[e.kind] || "#555", shape: "square", size: 0.6, text: e.label });
  }
  return m.sort((a, b) => a.time - b.time);
}

function startReplay() {
  S.tf = "M5";
  document.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("on", b.dataset.tf === "M5"));
  series.setData(S.round.charts.M5);
  const n = S.round.charts.M5.length;
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 90), to: n + 20 });
  S.markers = buildMarkers();
  S.replayIndex = 0;
  restartReplayTimer();
}

function restartReplayTimer() {
  clearInterval(S.replayTimer);
  if (S.speed === 0) { while (replayStep(false)) { /* instant */ } chart.timeScale().scrollToRealTime(); return; }
  S.replayTimer = setInterval(() => { if (!replayStep(true)) clearInterval(S.replayTimer); }, SPEED_MS[S.speed]);
}

function replayStep(scroll) {
  const bars = S.result.replay;
  if (S.phase !== "replay") return false;
  if (S.replayIndex >= bars.length) { finishRound(); return false; }
  const bar = bars[S.replayIndex++];
  series.update(bar);
  series.setMarkers(S.markers.filter((m) => m.time <= bar.time));
  S.nowTime = bar.time + 300;
  updateClock();
  if (scroll) chart.timeScale().scrollToRealTime(); // keep the newest candle in view
  return true;
}

function finishRound() {
  clearInterval(S.replayTimer);
  setPhase("result");
  // show the whole story: some history, the freeze, and every replayed candle
  const n = S.round.charts.M5.length;
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 60), to: n + S.result.replay.length + 8 });
  series.setMarkers(S.markers);
  const r = S.result;
  if (r.exit_reason === "tp") $("zoneReward").classList.add("flash");
  if (r.exit_reason === "sl") $("zoneRisk").classList.add("flash");
  if (r.explain.stop_needed) {
    S.extraLines.push(series.createPriceLine({ price: r.explain.stop_needed, color: "#e08a00", lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: t("stop_needed") }));
  }
  renderResult();
}

const TONES = ["good", "bad", "warn", "info"];
function blist(items) {
  return `<ul class="blist">${items.map((b) => `<li class="${TONES.includes(b.tone) ? b.tone : "info"}">${esc(b.text)}</li>`).join("")}</ul>`;
}
function sect(title, body, open) {
  return `<details class="sect"${open ? " open" : ""}><summary>${esc(title)}</summary><div class="sect-body">${body}</div></details>`;
}

function renderResult() {
  const r = S.result, x = r.explain, ideal = x.ideal;
  const isTrade = r.decision !== "skip";
  const good = isTrade ? r.result_r > 0 : r.exit_reason === "correct_skip";
  const cls = isTrade && r.result_r === 0 ? "flat" : good ? "pos" : "neg";
  const headline = isTrade ? fmtR(r.result_r) : S.L.reasons[r.exit_reason];
  const sub = isTrade ? `${S.L.reasons[r.exit_reason] || r.exit_reason} · R:R ${fmt(r.rr_planned, 1)}` : t("you_skipped");
  const dir = r.direction_hint && r.direction_hint !== "none" ? ` → ${r.direction_hint.toUpperCase()}` : "";
  const idealTxt = ideal.decision === "skip" ? "SKIP" : `${ideal.side.toUpperCase()} ${fmtR(ideal.r)}`;
  const chips = [
    [t("detector"), (S.L.setups[r.detector] || r.detector) + dir],
    [t("ideal_short"), idealTxt],
    [t("h1_trend"), String(r.h1_trend).toUpperCase()],
    [t("real_time"), `${r.freeze_time_ny} ${r.freeze_close_ny}`],
  ];
  const check = (key) => ({ tone: r[key] ? "good" : "bad", text: t(key) });
  const timeline = x.events.map((e) => `<li class="${e.kind}" data-time="${e.time}">${esc(e.text)}</li>`).join("");
  $("resultBody").innerHTML = [
    `<fieldset class="group"><legend>${t("result")}</legend>
      <div class="result-head"><span class="big-r ${cls}">${esc(headline)}</span><span>${esc(sub)}</span></div>
      <div class="chips">${chips.map(([k, v]) => `<span class="chip">${esc(k)}<b>${esc(v)}</b></span>`).join("")}</div>
    </fieldset>`,
    `<div class="lesson">${esc(x.lesson)}</div>`,
    sect(t("your_trade"), blist(x.trade), true),
    sect(t("ideal"), blist(ideal.points) +
      `<button id="btnIdeal" class="xp-btn small">${S.showIdeal ? t("hide_ideal") : t("show_ideal")} <kbd>I</kbd></button>`, true),
    sect(t("why"), blist(x.why), true),
    sect(t("timeline"), `<ul class="timeline">${timeline}</ul><div class="sub-hint">${t("timeline_hint")}</div>`, false),
    sect(t("setup_context"), `<div>${esc(x.trigger)}</div>` + blist(x.context)
      + (isTrade ? `<div class="sub-hint">${t("plan")}</div>` + blist(["rr_ok", "sl_beyond_swing", "with_bias"].map(check)) : ""), false),
  ].join("");
  $("resultBody").scrollTop = 0;
  $("resultBody").querySelectorAll(".timeline li").forEach((li) => { li.onclick = () => focusTime(Number(li.dataset.time)); });
  $("btnIdeal").onclick = toggleIdeal;
  $("btnNext").innerHTML = `${r.session_done ? t("to_report") : t("next")} <kbd>Enter</kbd>`;
  $("resultPanel").hidden = false; $("decidePanel").hidden = true; $("side").classList.add("wide");
}

// ---------- ideal setup overlay ----------
function toggleIdeal() {
  if (S.phase !== "result") return;
  S.showIdeal = !S.showIdeal;
  drawIdeal();
  const b = $("btnIdeal");
  if (b) b.innerHTML = `${S.showIdeal ? t("hide_ideal") : t("show_ideal")} <kbd>I</kbd>`;
}

function drawIdeal() {
  S.idealLines.forEach((l) => series.removePriceLine(l));
  S.idealLines = [];
  // the user's own lines step back while the ideal one is shown
  for (const k of ["entry", "sl", "tp"]) {
    if (S.priceLines[k]) S.priceLines[k].applyOptions({ lineVisible: !S.showIdeal, axisLabelVisible: !S.showIdeal });
  }
  if (!S.showIdeal || !S.result) return;
  const id = S.result.explain.ideal;
  const tag = id.decision === "skip" ? " (skip)" : "";
  const mk = (price, color, title) => series.createPriceLine({ price, color, lineWidth: 3,
    lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title });
  S.idealLines = [
    mk(id.entry, "#8e44ad", `IDEAL ${id.kind === "wait" ? "WAIT → " : ""}${id.side.toUpperCase()}${tag}`),
    mk(id.sl, "#e00000", "IDEAL SL"),
    mk(id.tp, "#00d000", `IDEAL TP ${fmtR(id.r)}`),
  ];
}

function focusTime(time) {
  const data = S.round.charts.M5.concat(S.result.replay);
  const bucket = time - (time % 300);
  const i = data.findIndex((b) => b.time >= bucket);
  if (i >= 0) chart.timeScale().setVisibleLogicalRange({ from: i - 50, to: i + 50 });
}

function advance() {
  if (S.phase !== "result") return;
  if (S.result.session_done) showReport(); else nextRound().catch((e) => setMsg(e.message));
}

// ---------- session report (Phase 4 extends) ----------
async function showReport() {
  setPhase("report");
  const rep = await api(`/api/session/${S.sessionId}/report`);
  const s = rep.stats;
  $("dialogTitle").textContent = t("report");
  $("overlayBox").innerHTML = `
    <table>
      <tr><td>${t("trades")}</td><td>${s.trades} / ${s.rounds}</td></tr>
      <tr><td>${t("win_rate")}</td><td>${pct(s.win_rate)}</td></tr>
      <tr><td>${t("total_r")}</td><td>${fmtR(s.total_r)}</td></tr>
      <tr><td>${t("avg_r")}</td><td>${fmtR(s.avg_r)}</td></tr>
      <tr><td>${t("skip_accuracy")}</td><td>${pct(s.skip_accuracy)}</td></tr>
      <tr><td>${t("avg_rr")}</td><td>${fmt(s.avg_rr_planned)}</td></tr>
      <tr><td>${t("plan_quality")}</td><td>${pct(s.plan_quality)}</td></tr>
    </table>
    <button id="btnNew" class="xp-btn go">${t("new_session")} <kbd>Enter</kbd></button>`;
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
    d: () => applyTheme(S.theme === "dark" ? "light" : "dark"),
    i: () => toggleIdeal(),
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
$("btnNext").onclick = advance;
$("btnTheme").onclick = () => applyTheme(S.theme === "dark" ? "light" : "dark");
$("inEntry").addEventListener("input", (e) => onPriceInput("entry", e.target.value));
$("inSl").addEventListener("input", (e) => onPriceInput("sl", e.target.value));
$("inTp").addEventListener("input", (e) => onPriceInput("tp", e.target.value));

(async () => {
  await loadLabels();
  applyTheme(S.theme);
  document.querySelectorAll("#confRow [data-conf]").forEach((b) => { b.onclick = () => setConfidence(Number(b.dataset.conf)); });
  setConfidence(3); setSpeed(S.speed); showOrderInputs(false);
  $("clockCursor").textContent = `${t("cursor")}: –`;
  try { await initStart(); } catch (err) { $("startMsg").textContent = err.message; }
})();
