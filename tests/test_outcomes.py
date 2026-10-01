"""Hidden MFE/MAE and target-before-stop logic."""
from __future__ import annotations

import numpy as np
import pandas as pd

from detect.controls import control_candidates, control_count, pick_controls
from detect.outcomes import scenario_outcomes, side_outcome


def test_long_hits_target_first() -> None:
    high = np.array([102, 105, 121, 101])
    low = np.array([99, 98, 104, 80])
    out = side_outcome(high, low, 100.0, 10.0, 2.0, "long")
    assert out["hit_target"] and out["mfe_pts"] == 21 and out["mae_pts"] == 20
    assert out["best_r"] == 2.1


def test_same_bar_target_and_stop_is_a_loss() -> None:
    out = side_outcome(np.array([101, 125]), np.array([99, 85]), 100.0, 10.0, 2.0, "long")
    assert not out["hit_target"]
    assert out["best_r"] == 0.1  # only the bar before the stop bar counts


def test_short_side_mirrors() -> None:
    out = side_outcome(np.array([101, 102]), np.array([95, 79]), 100.0, 10.0, 2.0, "short")
    assert out["hit_target"] and out["mfe_r"] == 2.1 and out["mae_r"] == 0.2


def test_scenario_outcomes_window() -> None:
    times = pd.date_range("2026-03-02 13:00", periods=10, freq="1min", tz="UTC")
    m1 = pd.DataFrame({"time_utc": times, "high": np.arange(10) + 101.0, "low": np.arange(10) + 99.0})
    out = scenario_outcomes(m1, times[2], 3, 100.0, 5.0, 2.0)  # bars 2,3,4 only
    assert out["long_mfe_pts"] == 5.0 and out["long_mae_pts"] == 0.0
    assert out["best_possible_r"] == 1.0


def test_controls() -> None:
    assert control_candidates([10, 11, 12, 13, 14, 15], {11}, 3) == [10, 15]
    assert control_count(75, 0.25) == 25
    picked = pick_controls(list(range(100)), 10, seed=1)
    assert picked == pick_controls(list(range(100)), 10, seed=1) and len(set(picked)) == 10
