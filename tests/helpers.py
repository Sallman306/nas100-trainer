"""Synthetic bar builders shared by tests."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_m1(start_utc: str, minutes: int, base: float = 20000.0) -> pd.DataFrame:
    """Continuous M1 bars starting at `start_utc`; prices rise 1 point per bar."""
    times = pd.date_range(start_utc, periods=minutes, freq="1min", tz="UTC")
    opens = base + np.arange(minutes, dtype=float)
    return pd.DataFrame(
        {
            "time_utc": times,
            "open": opens,
            "high": opens + 2.0,
            "low": opens - 1.0,
            "close": opens + 0.5,
            "tick_volume": np.full(minutes, 10, dtype="int64"),
            "spread": np.full(minutes, 15, dtype="int64"),
        }
    )


def make_random_m1(start_utc: str, days: int, seed: int = 1, base: float = 20000.0) -> pd.DataFrame:
    """Random-walk M1 bars on weekdays (24h), with occasional jumps so setups appear."""
    rng = np.random.default_rng(seed)
    times = pd.date_range(start_utc, periods=days * 1440, freq="1min", tz="UTC")
    times = times[times.dayofweek < 5]
    steps = rng.normal(0.0, 2.0, len(times))
    jumps = rng.random(len(times)) < 0.01
    steps[jumps] += rng.normal(0.0, 25.0, jumps.sum())
    close = base + np.cumsum(steps)
    opens = np.concatenate([[base], close[:-1]])
    wick = np.abs(rng.normal(0.0, 1.5, (2, len(times))))
    return pd.DataFrame(
        {
            "time_utc": times,
            "open": opens,
            "high": np.maximum(opens, close) + wick[0],
            "low": np.minimum(opens, close) - wick[1],
            "close": close,
            "tick_volume": np.full(len(times), 10, dtype="int64"),
            "spread": np.full(len(times), 15, dtype="int64"),
        }
    )
