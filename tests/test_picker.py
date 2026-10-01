"""Session planning: balance, drill filter, no-trade share."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.picker import plan_session

DETS = ["sweep", "bos", "orb", "fvg_retest"]


def scenarios() -> pd.DataFrame:
    rows = []
    for k in range(200):
        det = (DETS + ["no_trade"])[k % 5]
        direction = "none" if det == "no_trade" else ("long" if k % 2 else "short")
        rows.append({"scenario_id": f"s{k}", "detector": det, "direction_hint": direction})
    return pd.DataFrame(rows)


def test_mixed_session_balance() -> None:
    for seed in range(20):
        plan = plan_session(scenarios(), 10, None, set(), 0.25, np.random.default_rng(seed))
        df = scenarios().set_index("scenario_id").loc[plan]
        assert len(set(plan)) == 10
        assert (df["detector"] == "no_trade").sum() in (2, 3)
        counts = df[df["detector"] != "no_trade"]["detector"].value_counts()
        assert counts.max() - counts.min() <= 1 and len(counts) == 4


def test_drill_only_that_detector_both_directions() -> None:
    plan = plan_session(scenarios(), 10, "sweep", set(), 0.25, np.random.default_rng(1))
    df = scenarios().set_index("scenario_id").loc[plan]
    assert set(df["detector"]) == {"sweep"}
    assert set(df["direction_hint"]) == {"long", "short"}


def test_prefers_unplayed() -> None:
    played = {f"s{k}" for k in range(190)}
    plan = plan_session(scenarios(), 10, None, played, 0.25, np.random.default_rng(3))
    assert not set(plan) & played
