"""Plan checks and skip grading."""
from __future__ import annotations

import pandas as pd

from engine.grading import grade_skip, plan_checks
from engine.replay import Order


def m5(lows: list[float], highs: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"open": lows, "high": highs, "low": lows, "close": highs})


# swing low at index 2 (95), swing high at index 6 (115)
LOWS = [100, 98, 95, 97, 99, 104, 108, 103, 101, 102]
HIGHS = [105, 103, 100, 102, 106, 110, 115, 109, 107, 108]


def test_long_sl_beyond_swing_rr_and_bias() -> None:
    c = plan_checks(Order("long", "market", 102, 94, 118), m5(LOWS, HIGHS), "up", 2.0, 2)
    assert c.swing_price == 95 and c.sl_beyond_swing and c.rr_ok and c.with_bias and c.all_ok
    assert c.rr_planned == 2.0


def test_long_sl_above_swing_and_against_bias() -> None:
    c = plan_checks(Order("long", "market", 102, 96, 110), m5(LOWS, HIGHS), "down", 2.0, 2)
    assert not c.sl_beyond_swing and not c.rr_ok and not c.with_bias


def test_short_uses_swing_high() -> None:
    c = plan_checks(Order("short", "market", 108, 116, 90), m5(LOWS, HIGHS), "down", 2.0, 2)
    assert c.swing_price == 115 and c.sl_beyond_swing and c.with_bias


def test_unconfirmed_swing_is_ignored() -> None:
    # the last two bars cannot confirm a swing yet, so the dip at index 8 does not count
    c = plan_checks(Order("long", "market", 102, 100.5, 120), m5(LOWS, HIGHS), "up", 2.0, 2)
    assert c.swing_price == 95 and not c.sl_beyond_swing


def test_flat_trend_is_not_with_bias() -> None:
    assert not plan_checks(Order("long", "market", 102, 94, 118), m5(LOWS, HIGHS), "flat", 2.0, 2).with_bias


def test_skip_grading() -> None:
    assert grade_skip({"long_hit_target": False, "short_hit_target": False}) == "correct_skip"
    assert grade_skip({"long_hit_target": False, "short_hit_target": True}) == "missed_opportunity"
