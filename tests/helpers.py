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
