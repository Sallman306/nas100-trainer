# NAS100 Trade Trainer
Spec: docs/spec.md (follow it; ask before changing a decision in it).

## Stack
Python 3.13, pandas 3, pyarrow, MetaTrader5, FastAPI, uvicorn, pytest.
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
- Collect data: python collect.py (MT5 terminal must be open and logged in)
- Check a candle vs MT5: python collect.py --check YYYY-MM-DD
- Build scenarios: python scenarios.py
- Run app: uvicorn server:app --reload, then open http://localhost:8000
- Tests: pytest -q