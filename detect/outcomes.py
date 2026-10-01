"""Hidden answers: MFE/MAE and "+target before -1R" for both directions, on M1 bars."""
from __future__ import annotations

import numpy as np
import pandas as pd


def first_index(mask: np.ndarray) -> int:
    """Index of the first True, or len(mask) if none."""
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else len(mask)


def side_outcome(high: np.ndarray, low: np.ndarray, entry: float, risk: float, target_r: float, side: str) -> dict:
    """Excursions of one direction from `entry` over the given M1 bars.

    risk is 1R in points. hit_target: +target_r reached strictly before the -1R stop
    (a bar touching both counts as stopped). best_r: largest favourable move, in R,
    on bars before the stop bar.
    """
    if high.size == 0 or risk <= 0:
        return {"mfe_pts": 0.0, "mae_pts": 0.0, "mfe_r": 0.0, "mae_r": 0.0, "hit_target": False, "best_r": 0.0}
    if side == "long":
        fav, adv = high - entry, entry - low
    else:
        fav, adv = entry - low, high - entry
    stop_i = first_index(adv >= risk)
    target_i = first_index(fav >= target_r * risk)
    hit = target_i < len(fav) and target_i < stop_i
    before_stop = fav[:stop_i]
    best = float(max(before_stop.max(), 0.0)) / risk if before_stop.size else 0.0
    mfe, mae = max(float(fav.max()), 0.0), max(float(adv.max()), 0.0)
    return {
        "mfe_pts": mfe, "mae_pts": mae, "mfe_r": mfe / risk, "mae_r": mae / risk,
        "hit_target": bool(hit), "best_r": best,
    }


def scenario_outcomes(m1: pd.DataFrame, start_utc: pd.Timestamp, minutes: int, entry: float,
                      risk: float, target_r: float) -> dict:
    """Long and short outcomes over M1 bars opening in [start_utc, start_utc + minutes)."""
    times = m1["time_utc"]
    lo = times.searchsorted(start_utc, side="left")
    hi = times.searchsorted(start_utc + pd.Timedelta(minutes=minutes), side="left")
    high = m1["high"].to_numpy()[lo:hi]
    low = m1["low"].to_numpy()[lo:hi]
    out: dict = {}
    for side in ("long", "short"):
        for key, val in side_outcome(high, low, entry, risk, target_r, side).items():
            out[f"{side}_{key}"] = val
    out["best_possible_r"] = max(out["long_best_r"], out["short_best_r"])
    return out
