# NAS100 Trade Trainer – Build Instructions

Sep 30, 2026 · @Sallman

## Goal and scope

A local practice tool that freezes the NAS100 chart at a real decision moment in the 8–10 AM New York window, lets you place entry, TP and SL, then replays the next candles to show the outcome and grade you.

- **Learn:** see many real setups fast, the way a flight simulator works for pilots.
- **Build a strategy:** every trade is tagged and logged, so patterns that work show up in the stats.
- **Practice:** drill one setup type until the numbers are consistent.
- **Out of scope (v1):** live trading, order execution, other symbols. Keep the code symbol-agnostic so XAUUSD can be added later.

## Decisions and defaults

Items marked *default* were not specified; change them in `config.yaml` without touching code.

| Topic | Choice |
| --- | --- |
| Platform | Python backend + local web page in the browser |
| Chart library | TradingView Lightweight Charts (free, fast, looks like TradingView) |
| Round type | Bar replay that starts at a detected strategic point, not a random point |
| Trading window | 08:00–10:00 New York time (covers the 09:30 cash open) |
| Timeframes | *default:* execute on M5, context on M15 and H1, switchable on the frozen moment |
| Data history | *default:* 12 months of M1 from MT5, resampled to M5/M15/H1/H4 |
| Feedback | *default:* stats + rule checklist in the app; AI coaching outside the app (export pasted into Claude chat or Claude Code) |
| Risk unit | Results in R (1R = SL distance), plus points; account size optional |
| Spread | *default:* fixed 1.5 points added on entry, editable |

## Architecture and folder structure

Everything runs on your PC: Python does the data and grading, the browser only draws and collects your decisions.

&#91;embedded content: architecture · 8 parts, one loop\]

Data flows once from MT5 into files; each practice round then runs between the server and the browser, and every decision lands in the trade log that feeds the report.

```
nas100-trainer/
├── config.yaml          # symbol, server offset, window, spread, session length
├── collect.py           # MT5 → Parquet
├── scenarios.py         # strategic point detectors
├── engine/
│   ├── replay.py        # fills, TP/SL resolution on M1
│   ├── grading.py       # R result, plan quality, skip grading
│   └── feedback.py      # stats + coaching rules
├── server.py            # FastAPI endpoints
├── web/
│   ├── index.html
│   ├── app.js           # Lightweight Charts, drag lines, replay
│   └── labels.json      # EN/FR text
├── data/                # parquet files (git-ignored)
├── logs/trades.csv
└── tests/test_lookahead.py
```

## Data layer: NAS100 from MT5

One script, `collect.py`, pulls M1 candles once, stores them as Parquet, and only appends new bars on later runs.

1. Install: `pip install MetaTrader5 pandas pyarrow pyyaml fastapi uvicorn`. MT5 terminal must be open and logged in (Windows only; under WSL2 run this step in Windows Python).
2. Find the broker's symbol name (often `NAS100`, `US100` or `USTEC`) with `mt5.symbols_get()` and set it in `config.yaml`.
3. Pull in monthly chunks with `mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start, end)`; brokers cap rows per call.
4. Convert timestamps: MT5 returns broker server time. Store `server_offset_hours` in config, convert to UTC, then to `America/New_York` (handles DST).
5. Save `data/nas100_m1.parquet` with columns `time_utc, open, high, low, close, tick_volume, spread`.
6. Resample to M5, M15, H1, H4 with pandas `resample` (open=first, high=max, low=min, close=last) and cache each file.
7. Validate: no duplicate timestamps, flag gaps over 5 minutes inside session hours, print a row count per month.

**Check:** a 09:30 NY candle on the chart matches the same candle in MT5 after offset conversion.

## Strategic point detection

`scenarios.py` scans every trading day once and saves decision moments to `data/scenarios.parquet`; each practice round loads one of them.

**Detectors (M5, 08:00–10:00 NY only):**

| Type | Trigger | Freeze bar |
| --- | --- | --- |
| Liquidity sweep | Wick beyond Asian, London or previous-day high/low, close back inside within 3 bars | Close of the reclaim candle |
| Displacement / BOS | Candle body > 1.5× ATR(14) closing beyond the last swing high/low | Close of that candle |
| Opening range break | Close outside the 09:30–09:45 range | Close of the break candle |
| FVG retest | Price returns into an unfilled fair value gap from the window | First touch of the gap |
| No-trade (control) | Random bar in the window with no detector firing | That bar |

Key levels: Asian 20:00–00:00 NY, London 02:00–05:00 NY, previous day = 18:00–17:00 NY futures day. All editable.

**Rules that keep it honest:**

- **No lookahead.** Detectors only read bars up to and including the freeze bar; write a unit test that shifts future data and confirms the scenario list is unchanged.
- **Keep 20–30% no-trade rounds.** If every round has a big move after it, you learn to always trade. "Skip" must be a valid, scorable answer.
- **Store the answer, hide it.** Save the next 120 M5 bars' max favourable and max adverse move (MFE/MAE) in both directions, used only for grading.
- **Balance types.** Sample rounds evenly across detector types and long/short, unless you choose a drill (e.g. sweeps only).

## Practice round flow and UI

A session is 10 rounds by default; each round takes under 2 minutes.

1. **Start screen:** pick session length, drill filter (all types or one), and timeframe set.
2. **Context:** chart loads frozen at the freeze bar with \~2 days of history. Asian, London and previous-day levels drawn as dashed lines; date hidden to avoid bias.
3. **Read:** switch M5 / M15 / H1 with keys 1-2-3; the frozen moment stays at the right edge.
4. **Decide:** choose Long, Short or Skip. For a trade, drag three lines (entry, SL, TP) or type prices. The panel shows R:R and risk in points live.
5. **Tag:** pick setup type, bias (with / against H1 trend), and confidence 1–5. One optional note.
6. **Commit:** inputs lock. No edits after this.
7. **Replay:** candles play forward (speed 1×, 5×, instant). Entry fills only if price reaches it; trade ends at TP, SL or the 17:00 NY time-out (end of the futures day; was 12:00, changed 2026-09-30).
8. **Round result:** outcome in R, what the best possible trade was (from MFE/MAE), and the detector type revealed.
9. **Session report:** after the last round (see Feedback engine).

**UI rules:** dark theme, one screen, no scrolling during a round, keyboard shortcuts for every step (L / S / K for long, short, skip; Enter to commit), bilingual labels EN/FR from one `labels.json`.

## Trade evaluation and logging

The replay engine resolves each trade on M1 bars so the TP-or-SL order is correct inside a single M5 candle.

- **Fill:** market entry fills at the freeze close + spread; limit entry fills only if touched before the 17:00 NY time-out, else "not filled".
- **Same-bar conflict:** if one M1 bar hits both TP and SL, count it as a loss (conservative).
- **Skip grading:** correct skip if neither direction reached +2R before -1R using a default 1×ATR stop; otherwise "missed opportunity".
- **Plan quality, separate from outcome:** SL beyond the nearest swing (yes/no), R:R ≥ 2 (yes/no), direction matches H1 bias (yes/no). A good plan that loses is still a good plan.

Every round appends one row to `logs/trades.csv` (also kept in SQLite for queries):

```csv
session_id,round,scenario_id,detector,freeze_time_ny,tf_used,decision,entry,sl,tp,rr_planned,setup_tag,bias_tag,confidence,note,filled,result_r,exit_reason,mfe_r,mae_r,best_possible_r,sl_beyond_swing,rr_ok,with_bias,seconds_to_decide
```

## Feedback engine

The session report ends with three "work on this" items, picked by rules from your stats, not generic advice.

**Numbers shown:** win rate, average R, expectancy (avg R per trade), total R, max losing streak, skip accuracy, average R:R planned, plan-quality score (% of trades passing all three checks), and the same stats split by detector type, long/short, and confidence level. An all-time tab tracks these over sessions.

**Rule-based coaching (v1):**

| If | Feedback |
| --- | --- |
| Losses mostly hit SL within 3 bars | Stops too tight; place SL beyond the swing that the setup invalidates |
| MFE ≥ 2R but trade closed at a loss or < 1R | TP too far or no plan to manage; test a 2R fixed target |
| Expectancy positive on one detector, negative on another | Drop the weak setup; drill the strong one only |
| High-confidence trades no better than low | Confidence is not calibrated; write the reason before tagging |
| Many missed opportunities on skips | Too passive on clear setups; review those charts |
| Many trades on no-trade rounds | Overtrading; require two confluences before entry |
| Against-bias trades lose more | Trade only with the H1 bias for the next 3 sessions |

Minimum 20 trades before any per-setup verdict; below that, the report says "not enough data".

**AI coaching (outside the app):** no API calls in the code. An **Export for review** button writes `exports/session_<id>.md` with the session's CSV rows plus, per round: detector type, H1/M15 trend, key levels, the last 30 M5 bars at the freeze point, and the 30 bars after. You paste or attach that file in a Claude chat or Claude Code with the coaching prompt below.

## Build phases and acceptance checks

Build in this order; each phase is usable on its own and ends with a check you can tick.

**Phase 1: Data**

- [ ] `collect.py` pulls 12 months of M1 and resamples to M5/M15/H1/H4
- [ ] 09:30 NY candle matches MT5 after time conversion

**Phase 2: Scenarios**

- [ ] `scenarios.py` finds sweeps, BOS, opening range breaks, FVG retests, no-trade rounds
- [ ] Lookahead test passes; at least 3 scenarios per trading day on average

**Phase 3: Practice MVP**

- [ ] FastAPI serves `/api/round/next`, `/api/round/{id}/submit`, `/api/session/{id}/report`
- [ ] Browser chart freezes, takes Long/Short/Skip with draggable entry/SL/TP, replays, shows R
- [ ] Trades written to `logs/trades.csv`

**Phase 4: Feedback v1**

- [ ] Session report with stats, per-setup split, and the rule-based "work on this" list
- [ ] All-time progress tab

**Phase 5: Polish and AI coaching**

- [ ] Drill mode, keyboard shortcuts, EN/FR toggle
- [ ] Export for review button writes exports/session\_\<id>.md

**Practice plan once built:** 3 sessions of 10 rounds per week; after 100 trades, keep only setups with positive expectancy and drill those.

## Building it with Claude Code

Run Claude Code in the project folder on Windows (the MetaTrader5 package is Windows-only), build one phase per session, and commit after each phase passes its checks.

**Setup (once)**

1. Create `nas100-trainer/`, run `git init`, and open Claude Code in that folder.
2. Export this doc as Markdown and save it as `docs/spec.md` in the repo. Claude Code reads it as the source of truth.
3. Create `CLAUDE.md` at the root with the block below. Claude Code loads it every session.

```markdown
# NAS100 Trade Trainer
Spec: docs/spec.md (follow it; ask before changing a decision in it).

## Stack
Python 3.11, pandas, pyarrow, MetaTrader5, FastAPI, uvicorn, pytest.
Frontend: plain HTML + JS + TradingView Lightweight Charts (CDN). No React, no build step.

## Rules
- All settings in config.yaml. No hard-coded symbol, times or spread.
- Times stored in UTC, displayed in America/New_York.
- Detectors must never read bars after the freeze bar. tests/test_lookahead.py must pass.
- TP/SL resolution on M1 bars; same-bar TP+SL = loss.
- No AI/API calls in the app. Coaching = export file only.
- Every phase: write tests, run them, show results before saying done.
- Small files, type hints, docstrings in English.

## Commands
- Collect data: python collect.py
- Build scenarios: python scenarios.py
- Run app: uvicorn server:app --reload, then open http://localhost:8000
- Tests: pytest -q
```

**Per-phase loop**

1. Paste the phase prompt. Ask for a plan first and read it before letting it write code.
2. Let it build, run the tests, and fix failures.
3. Check it yourself against the phase's acceptance checks above.
4. Commit (`git commit -m "phase 1 data"`), then `/clear` before the next phase.

**Phase prompts (copy-paste)**

```text
Phase 1. Read docs/spec.md sections "Data layer" and "Decisions and defaults". Build config.yaml and collect.py: pull 12 months of NAS100 M1 from MT5 in monthly chunks, convert server time to UTC with server_offset_hours, save data/nas100_m1.parquet, resample to M5/M15/H1/H4, validate gaps and duplicates, print rows per month. Only append new bars on re-run. Plan first.
```

```text
Phase 2. Read "Strategic point detection". Build scenarios.py with one function per detector (sweep, BOS/displacement, opening range break, FVG retest, no-trade control) on M5 inside 08:00-10:00 NY. Save data/scenarios.parquet with freeze time, type, direction, key levels, and hidden MFE/MAE for both directions over the next 120 M5 bars. Write tests/test_lookahead.py. Print counts per type and per day. Plan first.
```

```text
Phase 3. Read "Practice round flow and UI" and "Trade evaluation and logging". Build engine/replay.py, engine/grading.py, server.py (endpoints in Build phases) and web/ (index.html, app.js, labels.json). Chart frozen at the freeze bar, M5/M15/H1 switch, Long/Short/Skip, draggable entry/SL/TP with live R:R, tags, commit lock, animated replay, round result. Append each round to logs/trades.csv. Dark theme, keyboard shortcuts. Plan first.
```

```text
Phase 4. Read "Feedback engine". Build engine/feedback.py and the session report screen: all stats, splits by detector/direction/confidence, the coaching rules table as code (min 20 trades per verdict), top 3 "work on this" items, and an all-time progress tab.
```

```text
Phase 5. Add drill mode, EN/FR toggle, and an "Export for review" button that writes exports/session_<id>.md: the session CSV rows plus per round the detector, H1/M15 trend, key levels, last 30 M5 bars before freeze and 30 after (OHLC table), my decision and result.
```

**Coaching prompt (paste with the export file, in chat or Claude Code)**

```text
You are my NAS100 trading coach. Attached is my practice session export (NY session, 08:00-10:00, M5 execution).
For each round: was the decision (long/short/skip) reasonable given the context at the freeze bar only, not the outcome? Was the SL placed beyond the level that invalidates the idea? Was the TP realistic vs the nearest liquidity?
Then give me:
1. My 3 strengths, with round numbers.
2. My 3 most costly mistakes, with round numbers and what I should have done.
3. One drill for the next session (setup type + rule to follow).
4. Patterns across rounds (direction, setup type, confidence vs result).
Keep it short and specific. Judge the process, not the result.
```
