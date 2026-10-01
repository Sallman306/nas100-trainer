"""Server time <-> UTC conversion, including DST switches."""
import pandas as pd
import pytest

from data_io.timeconv import ServerClock, to_ny

NY_PLUS_7 = ServerClock("ny_plus_7")


@pytest.mark.parametrize(
    "server, expected_utc",
    [
        ("2026-01-15 16:30", "2026-01-15 14:30"),  # winter: server GMT+2, NY 09:30 EST
        ("2026-07-15 16:30", "2026-07-15 13:30"),  # summer: server GMT+3, NY 09:30 EDT
        ("2026-03-09 16:30", "2026-03-09 13:30"),  # Monday after US DST start (Mar 8 2026)
        ("2026-11-02 16:30", "2026-11-02 14:30"),  # Monday after US DST end (Nov 1 2026)
    ],
)
def test_ny_plus_7_maps_server_to_utc(server: str, expected_utc: str) -> None:
    out = NY_PLUS_7.to_utc(pd.DatetimeIndex([server]))
    assert out[0] == pd.Timestamp(expected_utc, tz="UTC")


@pytest.mark.parametrize("day", ["2026-01-15", "2026-03-09", "2026-07-15", "2026-11-02"])
def test_0930_ny_is_1630_server_all_year(day: str) -> None:
    ny = to_ny(NY_PLUS_7.to_utc(pd.DatetimeIndex([f"{day} 16:30"])))
    assert ny[0].strftime("%Y-%m-%d %H:%M") == f"{day} 09:30"


def test_round_trip_ny_plus_7_over_a_year() -> None:
    utc = pd.date_range("2026-01-01", "2026-12-31", freq="37min", tz="UTC")
    back = NY_PLUS_7.to_utc(NY_PLUS_7.from_utc(utc))
    # Only the Sunday ~02:00 NY DST hour may not round-trip; market is closed then.
    mismatches = utc[back != utc]
    assert all(t.tz_convert("America/New_York").weekday() == 6 for t in mismatches)
    assert len(mismatches) <= 4


def test_fixed_offset() -> None:
    clock = ServerClock("fixed", 2)
    out = clock.to_utc(pd.DatetimeIndex(["2026-07-15 16:30"]))
    assert out[0] == pd.Timestamp("2026-07-15 14:30", tz="UTC")
    assert clock.from_utc(out)[0] == pd.Timestamp("2026-07-15 16:30")


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        ServerClock("gmt_plus_3")


def test_from_utc_rejects_naive() -> None:
    with pytest.raises(ValueError):
        NY_PLUS_7.from_utc(pd.DatetimeIndex(["2026-01-01 00:00"]))
