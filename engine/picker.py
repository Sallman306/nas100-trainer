"""Choose the scenarios of a session: balanced across detector types and directions."""
from __future__ import annotations

import numpy as np
import pandas as pd

NO_TRADE = "no_trade"


def control_rounds(n: int, share: float, rng: np.random.Generator) -> int:
    """Number of no-trade rounds: n*share, with the fraction rounded up at random."""
    exact = n * share
    base = int(np.floor(exact))
    return base + int(rng.random() < exact - base)


def _take(pool: pd.DataFrame, used: set[str], rng: np.random.Generator) -> str | None:
    """Random scenario id from `pool` not yet used, or None."""
    ids = [s for s in pool["scenario_id"] if s not in used]
    return str(rng.choice(ids)) if ids else None


def plan_session(scenarios: pd.DataFrame, n: int, drill: str | None, played: set[str],
                 no_trade_share: float, rng: np.random.Generator) -> list[str]:
    """Scenario ids for a session of `n` rounds.

    - drill set: only that detector, alternating long/short where possible;
    - otherwise: `no_trade_share` of rounds are controls, the rest cycle through the
      detector types (shuffled) and alternate long/short.
    Scenarios already played are avoided while unplayed ones remain.
    """
    pool = scenarios if not drill else scenarios[scenarios["detector"] == drill]
    if pool.empty:
        raise ValueError(f"no scenarios for drill {drill!r}")
    fresh = pool[~pool["scenario_id"].isin(played)]
    if len(fresh) >= n:
        pool = fresh
    detectors = sorted(set(pool["detector"]) - {NO_TRADE})
    if drill:
        slots = [drill] * n
    else:
        n_ctrl = control_rounds(n, no_trade_share, rng) if NO_TRADE in set(pool["detector"]) else 0
        order = list(rng.permutation(detectors)) if detectors else [NO_TRADE]
        slots = [NO_TRADE] * n_ctrl + [order[k % len(order)] for k in range(n - n_ctrl)]
    used: set[str] = set()
    picks: list[str] = []
    want = "long" if rng.random() < 0.5 else "short"
    for det in slots:
        sub = pool[pool["detector"] == det]
        sid = None
        if det != NO_TRADE:
            sid = _take(sub[sub["direction_hint"] == want], used, rng)
            want = "short" if want == "long" else "long"
        sid = sid or _take(sub, used, rng) or _take(pool, used, rng)
        if sid is None:
            break
        used.add(sid)
        picks.append(sid)
    return [picks[i] for i in rng.permutation(len(picks))]
