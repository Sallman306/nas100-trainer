"""Month chunking and append-only updates, using a fake MT5 fetcher."""
from datetime import datetime

import pandas as pd

from data_io.m1_store import month_chunks, update_m1
from data_io.timeconv import ServerClock

CLOCK = ServerClock("ny_plus_7")


class FakeMT5:
    """Serves M1 bars (server time) from a fixed table and records requests."""

    def __init__(self, start: str, end: str) -> None:
        times = pd.date_range(start, end, freq="1min", inclusive="left")
        self.table = pd.DataFrame(
            {"time": times, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 3, "spread": 15}
        )
        self.calls: list[tuple[datetime, datetime]] = []

    def __call__(self, start: datetime, end: datetime) -> pd.DataFrame:
        self.calls.append((start, end))
        # MT5 copy_rates_range includes the end bar; emulate that to test dedupe.
        t = self.table
        return t[(t.time >= start) & (t.time <= end)].copy()


def test_month_chunks_split_on_month_boundaries() -> None:
    chunks = list(month_chunks(pd.Timestamp("2026-01-20"), pd.Timestamp("2026-03-05 12:00")))
    assert chunks == [
        (pd.Timestamp("2026-01-20"), pd.Timestamp("2026-02-01")),
        (pd.Timestamp("2026-02-01"), pd.Timestamp("2026-03-01")),
        (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-03-05 12:00")),
    ]


def test_first_run_pulls_history_in_monthly_chunks() -> None:
    fake = FakeMT5("2026-06-01", "2026-09-02")
    now = pd.Timestamp("2026-09-01 10:00", tz="UTC")
    m1, added = update_m1(None, fake, CLOCK, history_months=2, now_utc=now)
    assert len(fake.calls) == 3  # Jul (from Jul 1), Aug, Sep 1..2
    assert added == len(m1)
    assert m1.time_utc.is_unique and m1.time_utc.is_monotonic_increasing
    assert str(m1.time_utc.dt.tz) == "UTC"
    first_server = CLOCK.from_utc(pd.DatetimeIndex([m1.time_utc.iloc[0]]))[0]
    assert first_server == pd.Timestamp("2026-07-01 00:00")


def test_rerun_appends_only_new_bars() -> None:
    fake = FakeMT5("2026-06-01", "2026-09-10")
    m1, _ = update_m1(None, fake, CLOCK, 1, pd.Timestamp("2026-09-01 10:00", tz="UTC"))
    last = m1.time_utc.max()

    fake.calls.clear()
    m1b, added = update_m1(m1, fake, CLOCK, 1, pd.Timestamp("2026-09-03 10:00", tz="UTC"))
    assert m1b.time_utc.is_unique and m1b.time_utc.is_monotonic_increasing
    assert added == (m1b.time_utc > last).sum()
    assert added > 0
    # Re-fetch started one hour before the last stored bar, not from the beginning.
    first_req = fake.calls[0][0]
    assert first_req == CLOCK.from_utc(pd.DatetimeIndex([last]))[0] - pd.Timedelta(hours=1)
    # Old rows untouched.
    pd.testing.assert_frame_equal(m1b.iloc[: len(m1)], m1)


def test_rerun_backfills_when_history_starts_late() -> None:
    """Simulates the terminal bar limit: first run only got recent bars."""
    fake = FakeMT5("2026-06-01", "2026-09-02")
    now = pd.Timestamp("2026-09-01 10:00", tz="UTC")
    full, _ = update_m1(None, fake, CLOCK, 2, now)
    truncated = full[full.time_utc >= pd.Timestamp("2026-08-10", tz="UTC")].reset_index(drop=True)

    fake.calls.clear()
    m1, added = update_m1(truncated, fake, CLOCK, 2, now)
    assert added == len(full) - len(truncated)
    pd.testing.assert_series_equal(m1.time_utc, full.time_utc)


def test_rerun_with_no_new_data_adds_nothing() -> None:
    fake = FakeMT5("2026-06-01", "2026-08-15")
    now = pd.Timestamp("2026-09-01 10:00", tz="UTC")
    m1, _ = update_m1(None, fake, CLOCK, 2, now)
    m1b, added = update_m1(m1, fake, CLOCK, 2, now)
    assert added == 0
    assert len(m1b) == len(m1)
