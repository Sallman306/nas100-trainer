# NAS100 Trade Trainer

A local practice tool for NAS100 day trading. It freezes the chart at a real decision moment
in the 08:00–10:00 New York window, lets you place entry, take profit and stop loss, then
replays the candles that followed to show the outcome and grade your decision.

- **Learn:** see many real setups fast, like a flight simulator for trading.
- **Build a strategy:** every trade is tagged by setup type (sweep, FVG retest, break of
  structure, opening range breakout) and logged, so the setups that work show up in the stats.
- **Practice:** drill one setup type until the numbers are consistent.
- **No-trade rounds:** about a quarter of the rounds have no setup, so you also practise skipping.

Everything runs on your own machine. The app makes no AI or API calls.

![Screenshot](docs/screenshot.png)
<!-- TODO: add docs/screenshot.png -->

## Requirements

- Windows (the MetaTrader5 Python package only works on Windows)
- Python 3.13
- MetaTrader 5 terminal, installed, open and logged in to a broker account that offers NAS100
  (needed only to download price data; the practice app itself works offline)

## Setup

```bat
git clone https://github.com/Sallman306/nas100-trainer.git
cd nas100-trainer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Set your broker symbol

Open `config.yaml` and set `symbol` to the exact NAS100 name your broker uses in MT5
(for example `NAS100.s`, `NAS100`, `USTEC` or `NAS100 Cash`). Check the Market Watch window
in MT5 for the name. While you are there, check `server_time` (how your broker's server clock
relates to real time) and `spread_points`.

All settings live in `config.yaml`; nothing is hard-coded.

## Usage

1. **Download price data** (MT5 must be open and logged in):

   ```bat
   python collect.py
   ```

   The first run pulls `history_months` of M1 data; later runs append only new bars.
   To compare one day's candles against MT5: `python collect.py --check YYYY-MM-DD`.

2. **Build the scenarios** (detects setups and no-trade moments in the history):

   ```bat
   python scenarios.py
   ```

3. **Start the app:** double-click `run_app.bat`, or run it from a terminal. It starts the
   server and opens http://localhost:8000 in your browser. Close the terminal window to stop it.

   (Manual alternative: `uvicorn server:app --reload`, then open http://localhost:8000.)

## AI coaching (export)

After a session, click **Export for review**. The app writes `exports/session_<id>.md` with your
trade-log rows and, for each round, the setup type, H1/M15 trend, key levels and the M5 bars
before and after the freeze point. The file ends with a ready-made coaching prompt.

Attach or paste that file into a Claude chat (or open it in Claude Code) and ask for a review.
The app itself never sends anything anywhere.

## Tests

```bat
pytest -q
```

`tests/test_lookahead.py` guards the most important rule: detectors never read bars after
the freeze bar.

## Not in the repo

These folders are created locally and are ignored by git:

- `data/` – downloaded price data and scenarios (Parquet)
- `logs/` – your trade log (`trades.csv`)
- `exports/` – coaching export files

## Project layout

```
collect.py      download M1 data from MT5, resample to M5/M15/H1/H4
scenarios.py    detect setups and build the scenario file
server.py       FastAPI app (serves web/ and the practice API)
data_io/        MT5 source, storage, time conversion, validation
detect/         indicators, levels, detectors, outcomes
engine/         sessions, grading, replay, feedback, export
web/            HTML + JS front end (TradingView Lightweight Charts)
docs/spec.md    full specification
```

## Disclaimer

This is a practice and education tool, not financial advice. Past price behaviour does not
predict future results.

## License

MIT – see [LICENSE](LICENSE).
