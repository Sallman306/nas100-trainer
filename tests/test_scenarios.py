"""End-to-end scenario build on synthetic data."""
from __future__ import annotations

from datetime import date, time

import pandas as pd

from data_io.resample import resample_ohlc
from data_io.timeconv import ServerClock
from detect.config import DetectConfig
from detect.levels import daily_levels, session_bounds
from scenarios import build_scenarios
from tests.helpers import make_random_m1

CLOCK = ServerClock("ny_plus_7")


def test_session_bounds_wrap_midnight() -> None:
    lo, hi = session_bounds(date(2026, 3, 3), (time(20, 0), time(0, 0)), "America/New_York")
    assert str(lo) == "2026-03-02 20:00:00-05:00" and str(hi) == "2026-03-03 00:00:00-05:00"


def test_levels_use_previous_futures_day() -> None:
    m1 = make_random_m1("2026-03-02 00:00", 4, seed=2)
    m5 = resample_ohlc(m1, "M5", CLOCK)
    lv = daily_levels(m5, [date(2026, 3, 4)], DetectConfig()).iloc[0]
    ny = m5["time_utc"].dt.tz_convert("America/New_York")
    prev = m5[(ny >= "2026-03-02 18:00") & (ny < "2026-03-03 18:00")]
    assert lv["pdh"] == prev["high"].max() and lv["pdl"] == prev["low"].min()
    lon = m5[(ny >= "2026-03-04 02:00") & (ny < "2026-03-04 05:00")]
    assert lv["london_high"] == lon["high"].max()


def test_build_scenarios_columns_and_share() -> None:
    m1 = make_random_m1("2026-03-02 00:00", 19, seed=5)
    m5 = resample_ohlc(m1, "M5", CLOCK)
    h1 = resample_ohlc(m1, "H1", CLOCK)
    cfg = DetectConfig()
    df = build_scenarios(m1, m5, h1, cfg)
    for col in ["scenario_id", "freeze_time_utc", "detector", "direction_hint", "asian_high", "pdh",
                "atr", "h1_trend", "long_mfe_pts", "long_mae_r", "short_mfe_r", "best_possible_r"]:
        assert col in df.columns
    assert df["scenario_id"].is_unique
    share = (df["detector"] == "no_trade").mean()
    assert 0.2 <= share <= 0.3
    clock = df["freeze_time_utc"].dt.tz_convert("America/New_York").dt.time
    assert ((clock >= time(8, 0)) & (clock < time(10, 0))).all()
    assert (df[["long_mfe_pts", "long_mae_pts", "short_mfe_pts", "short_mae_pts"]] >= 0).all().all()
    assert len(df) / df["day_ny"].nunique() >= 3
