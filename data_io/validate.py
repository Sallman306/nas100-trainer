"""Data quality checks: duplicates, gaps inside session hours, rows per month."""
from __future__ import annotations

from datetime import time, timedelta

import pandas as pd


def count_duplicates(times_utc: pd.Series) -> int:
    """Number of rows whose timestamp already appeared earlier."""
    return int(times_utc.duplicated().sum())


def _overlaps_session(gap_start: pd.Timestamp, gap_end: pd.Timestamp, start: time, end: time) -> bool:
    """True if [gap_start, gap_end) overlaps any weekday window [start, end) (local time)."""
    day = gap_start.normalize()
    while day <= gap_end:
        if day.weekday() < 5:
            win_start = day.replace(hour=start.hour, minute=start.minute)
            win_end = day.replace(hour=end.hour, minute=end.minute)
            if gap_start < win_end and gap_end > win_start:
                return True
        day = (day + timedelta(days=1)).normalize()
    return False


def find_gaps(
    times_utc: pd.Series,
    max_minutes: int,
    tz: str,
    session_start: time,
    session_end: time,
) -> pd.DataFrame:
    """List missing-data stretches longer than `max_minutes` that touch weekday session hours.

    A gap runs from the first missing minute after a bar to the next bar's time.
    Returned times are in `tz`. Full-day holidays show up here too; that is expected.
    """
    local = pd.Series(pd.DatetimeIndex(times_utc).tz_convert(tz)).sort_values().reset_index(drop=True)
    prev, nxt = local.iloc[:-1].reset_index(drop=True), local.iloc[1:].reset_index(drop=True)
    step = nxt - prev
    mask = step > pd.Timedelta(minutes=max_minutes + 1)
    rows = []
    for p, n in zip(prev[mask], nxt[mask]):
        gap_start = p + pd.Timedelta(minutes=1)
        if _overlaps_session(gap_start, n, session_start, session_end):
            rows.append({"gap_start": gap_start, "gap_end": n, "minutes": int((n - gap_start).total_seconds() // 60)})
    return pd.DataFrame(rows, columns=["gap_start", "gap_end", "minutes"])


def rows_per_month(times_utc: pd.Series, tz: str) -> pd.Series:
    """Row count per calendar month in `tz`."""
    local = pd.DatetimeIndex(times_utc).tz_convert(tz).tz_localize(None)
    return pd.Series(1, index=local).groupby(local.to_period("M")).size().rename("rows")
