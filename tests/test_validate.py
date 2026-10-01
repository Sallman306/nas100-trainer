"""Duplicate, gap and monthly count checks."""
from datetime import time

import pandas as pd

from data_io.validate import count_duplicates, find_gaps, rows_per_month
from tests.helpers import make_m1

NY = "America/New_York"
START, END = time(8, 0), time(12, 0)


def test_duplicates_counted() -> None:
    m1 = make_m1("2026-07-15 13:30", 5)
    m1 = pd.concat([m1, m1.iloc[:2]], ignore_index=True)
    assert count_duplicates(m1.time_utc) == 2


def test_gap_inside_session_flagged() -> None:
    # 09:00-09:09 NY, then resume at 09:30 NY -> 20 missing minutes
    m1 = pd.concat([make_m1("2026-07-15 13:00", 10), make_m1("2026-07-15 13:30", 10)], ignore_index=True)
    gaps = find_gaps(m1.time_utc, 5, NY, START, END)
    assert len(gaps) == 1
    assert gaps.minutes.iloc[0] == 20
    assert gaps.gap_start.iloc[0].strftime("%H:%M") == "09:10"


def test_short_gap_ignored() -> None:
    m1 = pd.concat([make_m1("2026-07-15 13:00", 10), make_m1("2026-07-15 13:15", 10)], ignore_index=True)
    assert find_gaps(m1.time_utc, 5, NY, START, END).empty  # 5 missing minutes, not > 5


def test_gap_outside_session_ignored() -> None:
    # 14:00 -> 16:00 NY gap (outside 08:00-12:00)
    m1 = pd.concat([make_m1("2026-07-15 17:50", 10), make_m1("2026-07-15 20:00", 10)], ignore_index=True)
    assert find_gaps(m1.time_utc, 5, NY, START, END).empty


def test_weekend_gap_ignored() -> None:
    # Friday 17:00 NY close -> Sunday 18:00 NY open
    m1 = pd.concat([make_m1("2026-07-17 20:50", 10), make_m1("2026-07-19 22:00", 10)], ignore_index=True)
    assert find_gaps(m1.time_utc, 5, NY, START, END).empty


def test_rows_per_month_uses_ny_calendar() -> None:
    # 2026-08-01 02:00 UTC is still July 31 in New York
    m1 = pd.concat([make_m1("2026-08-01 02:00", 3), make_m1("2026-08-03 14:00", 2)], ignore_index=True)
    counts = rows_per_month(m1.time_utc, NY)
    assert counts[pd.Period("2026-07", "M")] == 3
    assert counts[pd.Period("2026-08", "M")] == 2
