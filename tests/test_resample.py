"""M1 -> M5/M15/H1/H4 aggregation."""
import pandas as pd
import pytest

from data_io.resample import resample_ohlc
from data_io.timeconv import ServerClock
from tests.helpers import make_m1

CLOCK = ServerClock("ny_plus_7")


def test_m5_ohlc_rules() -> None:
    m1 = make_m1("2026-07-15 13:30", 10)  # 09:30-09:39 NY
    m5 = resample_ohlc(m1, "M5", CLOCK)
    assert len(m5) == 2
    first = m5.iloc[0]
    assert first.time_utc == pd.Timestamp("2026-07-15 13:30", tz="UTC")
    assert first.open == m1.open.iloc[0]
    assert first.close == m1.close.iloc[4]
    assert first.high == m1.high.iloc[:5].max()
    assert first.low == m1.low.iloc[:5].min()
    assert first.tick_volume == 50


def test_bucket_labels_are_bar_open_times_and_partial_bucket_kept() -> None:
    m1 = make_m1("2026-07-15 13:32", 5)  # 13:32..13:36
    m5 = resample_ohlc(m1, "M5", CLOCK)
    assert list(m5.time_utc) == [pd.Timestamp("2026-07-15 13:30", tz="UTC"), pd.Timestamp("2026-07-15 13:35", tz="UTC")]


def test_empty_buckets_dropped() -> None:
    m1 = pd.concat([make_m1("2026-07-15 13:30", 5), make_m1("2026-07-15 15:00", 5)], ignore_index=True)
    m15 = resample_ohlc(m1, "M15", CLOCK)
    assert len(m15) == 2


@pytest.mark.parametrize(
    "start_utc, expected_h4_open_ny",
    [
        ("2026-07-15 13:30", "09:00"),  # summer
        ("2026-01-15 14:30", "09:00"),  # winter
    ],
)
def test_h4_aligned_to_server_clock(start_utc: str, expected_h4_open_ny: str) -> None:
    """MT5 H4 bars open at 00/04/08/12/16/20 server time = 09:00 NY for the cash open bar."""
    h4 = resample_ohlc(make_m1(start_utc, 30), "H4", CLOCK)
    assert h4.time_utc.iloc[0].tz_convert("America/New_York").strftime("%H:%M") == expected_h4_open_ny


def test_h1_and_types() -> None:
    h1 = resample_ohlc(make_m1("2026-07-15 13:00", 120), "H1", CLOCK)
    assert len(h1) == 2
    assert str(h1.time_utc.dt.tz) == "UTC"
    assert h1.tick_volume.dtype == "int64"


def test_unknown_timeframe() -> None:
    with pytest.raises(ValueError):
        resample_ohlc(make_m1("2026-07-15 13:00", 5), "M7", CLOCK)
