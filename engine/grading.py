"""Grading: plan quality (independent of the outcome) and skip decisions."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from detect.indicators import swing_points
from engine.replay import Order


@dataclass(frozen=True)
class PlanChecks:
    """The three plan-quality checks from the spec."""

    rr_planned: float
    rr_ok: bool
    sl_beyond_swing: bool
    with_bias: bool
    swing_price: float  # the swing used for the SL check (nan if none)

    @property
    def all_ok(self) -> bool:
        """True when the plan passes all three checks."""
        return self.rr_ok and self.sl_beyond_swing and self.with_bias


def rr_planned(order: Order) -> float:
    """Reward-to-risk of the plan, from the planned entry."""
    return abs(order.tp - order.entry) / order.risk


def nearest_swing(history_m5: pd.DataFrame, order: Order, swing_bars: int) -> float:
    """Most recent confirmed swing on the stop side of the entry (low for long, high for short).

    `history_m5` must end at the freeze bar, so only swings known at the freeze count.
    """
    pts = swing_points(history_m5.reset_index(drop=True), swing_bars)
    if order.side == "long":
        pts = pts[(pts["kind"] == "low") & (pts["price"] < order.entry)]
    else:
        pts = pts[(pts["kind"] == "high") & (pts["price"] > order.entry)]
    return float(pts["price"].iloc[-1]) if len(pts) else float("nan")


def plan_checks(order: Order, history_m5: pd.DataFrame, h1_trend: str, min_rr: float, swing_bars: int) -> PlanChecks:
    """SL beyond the nearest swing, R:R >= min_rr, direction with the H1 bias."""
    rr = rr_planned(order)
    swing = nearest_swing(history_m5, order, swing_bars)
    if swing != swing:  # nan: no swing on that side
        beyond = False
    else:
        beyond = order.sl < swing if order.side == "long" else order.sl > swing
    bias = (order.side == "long" and h1_trend == "up") or (order.side == "short" and h1_trend == "down")
    return PlanChecks(rr, rr >= min_rr - 1e-9, bool(beyond), bool(bias), swing)


def grade_skip(scenario: pd.Series | dict) -> str:
    """"correct_skip" if neither side reached +target R before -1R (1xATR stop), else "missed_opportunity"."""
    missed = bool(scenario["long_hit_target"]) or bool(scenario["short_hit_target"])
    return "missed_opportunity" if missed else "correct_skip"
