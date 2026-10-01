"""Resample M1 bars to higher timeframes."""
from __future__ import annotations

import pandas as pd

from data_io.timeconv import ServerClock

RULES: dict[str, str] = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "spread": "max"}
COLUMNS = ["time_utc", "open", "high", "low", "close", "tick_volume", "spread"]


def resample_ohlc(m1: pd.DataFrame, timeframe: str, clock: ServerClock) -> pd.DataFrame:
    """Aggregate M1 bars into `timeframe` bars labelled by their open time.

    Buckets are aligned on the broker's server clock so H4 bars match the MT5 chart
    (for M5..H1 the alignment is the same in any whole-hour timezone).
    Empty buckets (weekends, breaks) are dropped, never filled.
    """
    if timeframe not in RULES:
        raise ValueError(f"unknown timeframe {timeframe!r}; expected one of {list(RULES)}")
    if m1.empty:
        return pd.DataFrame(columns=COLUMNS)
    server_idx = clock.from_utc(pd.DatetimeIndex(m1["time_utc"]))
    df = m1.drop(columns="time_utc").set_index(server_idx)
    out = df.resample(RULES[timeframe], label="left", closed="left").agg(AGG)
    out = out.dropna(subset=["open"])
    out["tick_volume"] = out["tick_volume"].astype("int64")
    out["spread"] = out["spread"].astype("int64")
    out.insert(0, "time_utc", clock.to_utc(out.index))
    return out.reset_index(drop=True)[COLUMNS]
