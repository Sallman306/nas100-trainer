"""No-trade control rounds: random window bars where no detector fired."""
from __future__ import annotations

import numpy as np


def control_candidates(window_positions: list[int], signal_positions: set[int], cooldown: int) -> list[int]:
    """Window bars with no detection on the bar itself or the previous `cooldown` bars.

    Causal: eligibility of bar i depends only on detections at bars <= i.
    """
    out = []
    for i in window_positions:
        if not any((i - k) in signal_positions for k in range(cooldown + 1)):
            out.append(i)
    return out


def control_count(n_detected: int, share: float) -> int:
    """Number of controls so that controls / (controls + detected) == share."""
    if not 0.0 <= share < 1.0:
        raise ValueError(f"controls.share must be in [0, 1), got {share}")
    return int(round(n_detected * share / (1.0 - share)))


def pick_controls(candidates: list[int], n: int, seed: int) -> list[int]:
    """Seeded random choice of `n` candidates (all of them if fewer), sorted."""
    if n >= len(candidates):
        return sorted(candidates)
    rng = np.random.default_rng(seed)
    return sorted(int(x) for x in rng.choice(np.asarray(candidates), size=n, replace=False))
