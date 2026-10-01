"""How long a logged trade was held: re-run it on M1 bars (the CSV keeps no exit time)."""
from __future__ import annotations

import pandas as pd

from engine.feedback import is_true, num
from engine.market import MarketData, timeout_utc
from engine.replay import Order, simulate

M5 = pd.Timedelta(minutes=5)


def bars_held(row: dict, scenario: pd.Series, market: MarketData, spread: float, timeout, tz: str) -> int | None:
    """M5 bars from fill to exit (1 = exited inside the first 5 minutes); None if not computable.

    None as well when the re-run ends differently from the logged trade.

    A logged entry equal to the freeze close was a market order, anything else a pending one.
    """
    if row.get("decision") not in ("long", "short") or not is_true(row.get("filled")):
        return None
    entry, sl, tp = num(row.get("entry")), num(row.get("sl")), num(row.get("tp"))
    if None in (entry, sl, tp):
        return None
    close = round(float(scenario["close"]), 2)
    order_type = "market" if abs(entry - close) < 0.006 else "pending"  # type: ignore[operator]
    try:
        order = Order(row["decision"], order_type, close if order_type == "market" else entry, sl, tp)  # type: ignore[arg-type]
        freeze = scenario["freeze_time_utc"]
        trade = simulate(market.bars["M1"], order, market.freeze_end(freeze), timeout_utc(freeze, timeout, tz),
                         close, spread)
    except ValueError:
        return None
    if trade.fill_time is None or trade.exit_time is None or trade.exit_reason != row.get("exit_reason"):
        return None  # e.g. logged under an older time-out: the replay no longer matches the log
    return int((trade.exit_time - trade.fill_time) // M5) + 1
