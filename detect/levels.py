"""Key levels per trading day: Asian, London and previous futures-day high/low.

All levels end before the practice window opens, so they never leak future bars.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from detect.config import DetectConfig

LEVEL_COLUMNS = ["asian_high", "asian_low", "london_high", "london_low", "pdh", "pdl"]


def ny_times(m5: pd.DataFrame, tz: str) -> pd.Series:
    """Bar open times in the display timezone."""
    return m5["time_utc"].dt.tz_convert(tz)


def futures_day(ny: pd.Series, day_start: time) -> pd.Series:
    """Futures-day label: bars from day_start on D-1 up to day_start on D belong to D."""
    shift = timedelta(hours=24) - timedelta(hours=day_start.hour, minutes=day_start.minute)
    return (ny + shift).dt.date


def session_bounds(day: date, span: tuple[time, time], tz: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """NY start/end of a level session for trading day `day`.

    The end is anchored on `day`; if start >= end the session began the previous evening.
    """
    start, end = span
    end_dt = datetime.combine(day, end)
    start_day = day if start < end else day - timedelta(days=1)
    start_dt = datetime.combine(start_day, start)
    return pd.Timestamp(start_dt, tz=tz), pd.Timestamp(end_dt, tz=tz)


def _high_low(m5: pd.DataFrame, ny: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp) -> tuple[float, float]:
    """High and low of bars opening in [lo, hi); NaN if none."""
    mask = (ny >= lo) & (ny < hi)
    if not mask.any():
        return float("nan"), float("nan")
    return float(m5.loc[mask, "high"].max()), float(m5.loc[mask, "low"].min())


def daily_levels(m5: pd.DataFrame, days: list[date], cfg: DetectConfig) -> pd.DataFrame:
    """One row per trading day with the six key levels (NaN when data is missing)."""
    ny = ny_times(m5, cfg.tz)
    fday = futures_day(ny, cfg.day_start)
    day_hl = m5.groupby(fday.to_numpy()).agg(high=("high", "max"), low=("low", "min"))
    labels = sorted(day_hl.index)
    rows = []
    for day in days:
        ah, al = _high_low(m5, ny, *session_bounds(day, cfg.asian, cfg.tz))
        lh, ll = _high_low(m5, ny, *session_bounds(day, cfg.london, cfg.tz))
        prev = [d for d in labels if d < day]
        pdh, pdl = (day_hl.loc[prev[-1], "high"], day_hl.loc[prev[-1], "low"]) if prev else (float("nan"),) * 2
        rows.append((day, ah, al, lh, ll, float(pdh), float(pdl)))
    return pd.DataFrame(rows, columns=["day", *LEVEL_COLUMNS]).set_index("day")
