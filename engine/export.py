""""Export for review": one Markdown file per session for AI coaching outside the app.

The file holds the session's trade-log rows plus, per round, the context at the freeze
bar (detector, H1/M15 trend, key levels, last M5 bars) and the M5 bars that followed.
No API calls: the user pastes or attaches the file in a Claude chat or Claude Code.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from detect.indicators import h1_trend_at
from engine.config import PracticeConfig
from engine.market import MarketData
from engine.tradelog import COLUMNS

KEY_LEVELS = [("asian_high", "Asian high"), ("asian_low", "Asian low"), ("london_high", "London high"),
              ("london_low", "London low"), ("pdh", "Previous day high"), ("pdl", "Previous day low"),
              ("or_high", "Opening range high"), ("or_low", "Opening range low"), ("fvg_top", "FVG top"),
              ("fvg_bottom", "FVG bottom"), ("swing_high", "Last swing high"), ("swing_low", "Last swing low")]
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

COACHING_PROMPT = """You are my NAS100 trading coach. Attached is my practice session export (NY session, 08:00-10:00, M5 execution).
For each round: was the decision (long/short/skip) reasonable given the context at the freeze bar only, not the outcome? Was the SL placed beyond the level that invalidates the idea? Was the TP realistic vs the nearest liquidity?
Then give me:
1. My 3 strengths, with round numbers.
2. My 3 most costly mistakes, with round numbers and what I should have done.
3. One drill for the next session (setup type + rule to follow).
4. Patterns across rounds (direction, setup type, confidence vs result).
Keep it short and specific. Judge the process, not the result."""


def export_path(export_dir: Path, session_id: str) -> Path:
    """exports/session_<id>.md; rejects ids that could escape the folder."""
    if not SAFE_ID.match(session_id):
        raise ValueError(f"bad session id {session_id!r}")
    return export_dir / f"session_{session_id}.md"


def write_export(rows: list[dict], scenarios: pd.DataFrame, market: MarketData, cfg: PracticeConfig,
                 session_id: str) -> Path:
    """Write the session's export file and return its path."""
    path = export_path(cfg.export_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session_markdown(rows, scenarios, market, cfg, session_id), encoding="utf-8")
    return path


def session_markdown(rows: list[dict], scenarios: pd.DataFrame, market: MarketData, cfg: PracticeConfig,
                     session_id: str) -> str:
    """The whole export as Markdown. `scenarios` is indexed by scenario_id."""
    rows = sorted(rows, key=lambda r: int(r["round"]))
    parts = [
        f"# Practice session {session_id}",
        f"Exported {datetime.now():%Y-%m-%d %H:%M}. All times are New York (ET). "
        f"Prices in points; 1R = the planned stop distance. Spread {cfg.spread} points added on entry. "
        f"Trades still open at {cfg.timeout:%H:%M} ET are closed (time-out).",
        "## Coaching prompt", f"```text\n{COACHING_PROMPT}\n```",
        "## Summary", _summary(rows),
        "## Trade log (CSV)", f"```csv\n{_csv(rows)}```",
    ]
    for r in rows:
        scen = scenarios.loc[r["scenario_id"]] if r["scenario_id"] in scenarios.index else None
        parts.append(_round(r, scen, market, cfg))
    return "\n\n".join(parts) + "\n"


# ---------- pieces ----------
def _num(value: str) -> float | None:
    """CSV cell as a float, or None when empty / not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cell(value: object) -> str:
    """Display value for a table/bullet: '–' for empty."""
    return "–" if value is None or value == "" else str(value)


def _summary(rows: list[dict]) -> str:
    """A few headline numbers so the coach sees the session at a glance."""
    trades = [r for r in rows if r["decision"] != "skip" and r["filled"] == "True"]
    rs = [_num(r["result_r"]) or 0.0 for r in trades]
    skips = [r for r in rows if r["decision"] == "skip"]
    correct = sum(r["exit_reason"] == "correct_skip" for r in skips)
    wins = sum(x > 0 for x in rs)
    lines = [
        f"- Rounds: {len(rows)} · trades filled: {len(trades)} · skips: {len(skips)} "
        f"(correct {correct}, missed opportunity {len(skips) - correct})",
        f"- Total: {sum(rs):+.2f}R · win rate: {f'{wins / len(rs):.0%}' if rs else '–'} · "
        f"average: {f'{sum(rs) / len(rs):+.2f}R' if rs else '–'}",
    ]
    return "\n".join(lines)


def _csv(rows: list[dict]) -> str:
    """The session's rows exactly as logged in logs/trades.csv."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _round(r: dict, scen: pd.Series | None, market: MarketData, cfg: PracticeConfig) -> str:
    """One round: context at the freeze, my decision and result, M5 bars before and after."""
    head = f"## Round {r['round']}: {r['detector']}"
    if scen is None:
        return f"{head}\n\nScenario {r['scenario_id']} is no longer in the scenario file; only the log row is available."
    freeze = scen["freeze_time_utc"]
    end = market.freeze_end(freeze)
    ny = lambda t: t.tz_convert(cfg.tz)  # noqa: E731
    fast, slow, flat = cfg.trend
    m15 = h1_trend_at(market.bars["M15"], end, fast, slow, flat, span=pd.Timedelta(minutes=15))
    also = f" (also: {scen['also_detected']})" if scen["also_detected"] else ""
    level = (f" · trigger level: {scen['level_name']} {scen['level_price']:.2f}"
             if scen["level_name"] and pd.notna(scen["level_price"]) else "")
    context = [
        f"- Freeze bar: {ny(freeze):%a %Y-%m-%d %H:%M} ET (decision made at its close, {ny(end):%H:%M} ET)",
        f"- Detector: {scen['detector']}{also} · direction hint: {scen['direction_hint']}{level}",
        f"- Trend at the freeze: H1 {scen['h1_trend']} · M15 {m15}",
        f"- Price at the freeze close: {scen['close']:.2f} · ATR(14) M5: {scen['atr']:.2f}",
    ]
    levels = "\n".join(f"| {label} | {scen[k]:.2f} |" for k, label in KEY_LEVELS if pd.notna(scen[k]))
    level_table = f"| Level | Price |\n|---|---|\n{levels}" if levels else "No key levels for this day."
    n = cfg.export_bars
    before = market.history("M5", freeze, 1).tail(n)
    after = market.after("M5", freeze, end + pd.Timedelta(days=4)).head(n)
    return "\n\n".join([
        head, "### Context at the freeze (all I could see)", "\n".join(context), level_table,
        "### My decision", _decision(r),
        "### Result (hidden during the round)", _result(r, scen),
        f"### Last {len(before)} M5 bars up to the freeze", _bars(before, cfg.tz, mark=freeze),
        f"### Next {len(after)} M5 bars after the freeze", _bars(after, cfg.tz),
    ])


def _decision(r: dict) -> str:
    """Decision, order and tags as logged."""
    lines = [f"- Decision: **{r['decision']}**"]
    if r["decision"] != "skip":
        lines.append(f"- Entry {_cell(r['entry'])} · SL {_cell(r['sl'])} · TP {_cell(r['tp'])} · "
                     f"planned R:R {_cell(r['rr_planned'])}")
    lines.append(f"- Tags: setup {_cell(r['setup_tag'])} · bias {_cell(r['bias_tag'])} · "
                 f"confidence {_cell(r['confidence'])}/5 · timeframes looked at: {_cell(r['tf_used'])}")
    lines.append(f"- Note: {_cell(r['note'])} · time to decide: {_cell(r['seconds_to_decide'])} s")
    return "\n".join(lines)


def _result(r: dict, scen: pd.Series) -> str:
    """Outcome, plan checks and the best trade the scenario offered."""
    if r["decision"] == "skip":
        lines = [f"- Skip graded: {_cell(r['exit_reason']).replace('_', ' ')}"]
    else:
        lines = [f"- Filled: {_cell(r['filled'])} · exit: {_cell(r['exit_reason'])} · result: {_cell(r['result_r'])}R",
                 f"- MFE {_cell(r['mfe_r'])}R · MAE {_cell(r['mae_r'])}R (in R of my stop)",
                 f"- Plan checks: SL beyond swing {_cell(r['sl_beyond_swing'])} · R:R ok {_cell(r['rr_ok'])} · "
                 f"with H1 bias {_cell(r['with_bias'])}"]
    lines.append(f"- Best possible with a 1×ATR stop: long {scen['long_best_r']:.2f}R · "
                 f"short {scen['short_best_r']:.2f}R")
    return "\n".join(lines)


def _bars(df: pd.DataFrame, tz: str, mark: pd.Timestamp | None = None) -> str:
    """OHLC table in New York time; the freeze bar is marked."""
    if df.empty:
        return "No bars."
    rows = []
    for t, o, h, lo, c in zip(df["time_utc"], df["open"], df["high"], df["low"], df["close"]):
        flag = " ← freeze" if mark is not None and t == mark else ""
        rows.append(f"| {t.tz_convert(tz):%H:%M}{flag} | {o:.2f} | {h:.2f} | {lo:.2f} | {c:.2f} |")
    return "| Time ET | Open | High | Low | Close |\n|---|---|---|---|---|\n" + "\n".join(rows)
