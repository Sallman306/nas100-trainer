"""Conversion between broker server time and UTC."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

NY_TZ = "America/New_York"
NY_PLUS_HOURS = 7
MODES = ("ny_plus_7", "fixed")


@dataclass(frozen=True)
class ServerClock:
    """Describes the broker's server clock.

    mode "ny_plus_7": server wall clock = New York wall clock + 7h, so it follows
    US daylight saving (GMT+2 in winter, GMT+3 in summer).
    mode "fixed": server wall clock = UTC + fixed_offset_hours all year.
    """

    mode: str = "ny_plus_7"
    fixed_offset_hours: float = 2.0

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"server_time.mode must be one of {MODES}, got {self.mode!r}")

    def to_utc(self, server_times: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """Convert naive server wall-clock times to tz-aware UTC times."""
        idx = pd.DatetimeIndex(server_times)
        if self.mode == "fixed":
            return (idx - pd.Timedelta(hours=self.fixed_offset_hours)).tz_localize("UTC")
        ny_wall = idx - pd.Timedelta(hours=NY_PLUS_HOURS)
        # Ambiguous/nonexistent NY hours fall on Sunday ~02:00 NY, when the market is closed.
        ny = ny_wall.tz_localize(
            NY_TZ,
            ambiguous=np.zeros(len(ny_wall), dtype=bool),
            nonexistent="shift_forward",
        )
        return ny.tz_convert("UTC")

    def from_utc(self, utc_times: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """Convert tz-aware UTC times to naive server wall-clock times."""
        idx = pd.DatetimeIndex(utc_times)
        if idx.tz is None:
            raise ValueError("from_utc expects tz-aware UTC times")
        if self.mode == "fixed":
            return idx.tz_convert("UTC").tz_localize(None) + pd.Timedelta(hours=self.fixed_offset_hours)
        return idx.tz_convert(NY_TZ).tz_localize(None) + pd.Timedelta(hours=NY_PLUS_HOURS)


def to_ny(utc_times: pd.Series | pd.DatetimeIndex, tz: str = NY_TZ) -> pd.DatetimeIndex:
    """Convert tz-aware UTC times to the display timezone (New York by default)."""
    return pd.DatetimeIndex(utc_times).tz_convert(tz)
