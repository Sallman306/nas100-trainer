"""The four setup detectors. Each walks the window forward bar by bar and, when it
evaluates bar i, reads only positions <= i (the freeze bar is i itself).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

import numpy as np

from detect.config import DetectConfig


@dataclass
class Bars:
    """Full M5 arrays plus causal indicators (value at t uses bars <= t)."""

    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    swing_high: np.ndarray
    swing_low: np.ndarray


@dataclass
class Day:
    """Positions (into Bars) of one day's window bars and their NY clock times."""

    positions: np.ndarray
    clock: list[time]
    levels: dict[str, float]


@dataclass
class Signal:
    """A detection: the freeze bar position and what was seen."""

    pos: int
    detector: str
    direction: str
    level_name: str = ""
    level_price: float = float("nan")
    info: dict[str, float] = field(default_factory=dict)


SWEEP_LEVELS = (
    ("asian_high", "high"), ("asian_low", "low"),
    ("london_high", "high"), ("london_low", "low"),
    ("pdh", "high"), ("pdl", "low"),
)


def _sweep_at(b: Bars, i: int, level: float, side: str, k: int) -> bool:
    """True if bar i reclaims `level` after a wick beyond it within the last k bars."""
    sign = 1.0 if side == "high" else -1.0
    beyond = lambda x: sign * (x - level) > 0  # noqa: E731
    if beyond(b.close[i]) or b.close[i] == level:
        return False
    # walk back over closes that stayed beyond the level; j = first bar of the excursion
    j = i
    while j - 1 >= 0 and i - (j - 1) <= k and beyond(b.close[j - 1]):
        j -= 1
    if j - 1 < 0 or beyond(b.close[j - 1]):
        return False  # excursion longer than k bars, or no inside close before it
    extreme = b.high[j:i + 1].max() if side == "high" else b.low[j:i + 1].min()
    return bool(beyond(extreme))


def detect_sweeps(b: Bars, day: Day, cfg: DetectConfig) -> list[Signal]:
    """Wick beyond an Asian/London/prev-day level, close back inside within N bars."""
    out = []
    for name, side in SWEEP_LEVELS:
        level = day.levels.get(name, float("nan"))
        if not np.isfinite(level):
            continue
        for i in day.positions:
            if _sweep_at(b, int(i), level, side, cfg.sweep_reclaim_bars):
                out.append(Signal(int(i), "sweep", "short" if side == "high" else "long", name, level))
                break  # one sweep per level per day
    return out


def detect_bos(b: Bars, day: Day, cfg: DetectConfig) -> list[Signal]:
    """Displacement: body > X*ATR closing beyond the last confirmed swing."""
    out = []
    for i in (int(p) for p in day.positions):
        if i < 1 or not np.isfinite(b.atr[i - 1]):
            continue
        body = b.close[i] - b.open[i]
        if abs(body) <= cfg.displacement_atr * b.atr[i - 1]:
            continue
        sh, sl = b.swing_high[i - 1], b.swing_low[i - 1]
        if body > 0 and np.isfinite(sh) and b.close[i] > sh >= b.close[i - 1]:
            out.append(Signal(i, "bos", "long", "swing_high", float(sh)))
        elif body < 0 and np.isfinite(sl) and b.close[i] < sl <= b.close[i - 1]:
            out.append(Signal(i, "bos", "short", "swing_low", float(sl)))
    return out


def detect_orb(b: Bars, day: Day, cfg: DetectConfig) -> list[Signal]:
    """First close above / below the opening range (one signal per side)."""
    start, end = cfg.opening_range
    rng = [p for p, t in zip(day.positions, day.clock) if start <= t < end]
    if not rng:
        return []
    or_high = float(b.high[rng].max())
    or_low = float(b.low[rng].min())
    info = {"or_high": or_high, "or_low": or_low}
    out: list[Signal] = []
    done = {"long": False, "short": False}
    for i, t in zip(day.positions, day.clock):
        if t < end:
            continue
        i = int(i)
        if not done["long"] and b.close[i] > or_high:
            out.append(Signal(i, "orb", "long", "or_high", or_high, info))
            done["long"] = True
        if not done["short"] and b.close[i] < or_low:
            out.append(Signal(i, "orb", "short", "or_low", or_low, info))
            done["short"] = True
    return out


def detect_fvg_retests(b: Bars, day: Day, cfg: DetectConfig) -> list[Signal]:
    """First return into an unfilled fair value gap formed inside the window."""
    pos = [int(p) for p in day.positions]
    first = pos[0]
    gaps: list[dict] = []  # active gaps, each known from its confirmation bar c
    out = []
    for i in pos:
        # 1) price action of bar i against gaps confirmed before i
        for g in gaps:
            if g["done"] or g["c"] >= i:
                continue
            if g["dir"] == "long" and b.low[i] <= g["top"]:
                g["done"] = True
                if b.close[i] >= g["bottom"]:
                    out.append(Signal(i, "fvg_retest", "long", "fvg_top", g["top"], {"fvg_top": g["top"], "fvg_bottom": g["bottom"]}))
            elif g["dir"] == "short" and b.high[i] >= g["bottom"]:
                g["done"] = True
                if b.close[i] <= g["top"]:
                    out.append(Signal(i, "fvg_retest", "short", "fvg_bottom", g["bottom"], {"fvg_top": g["top"], "fvg_bottom": g["bottom"]}))
        # 2) does bar i complete a new gap (bars i-2, i-1, i all in the window)?
        if i - 2 >= first and np.isfinite(b.atr[i]):
            min_size = cfg.fvg_min_atr * b.atr[i]
            if b.low[i] - b.high[i - 2] > min_size:
                gaps.append({"c": i, "dir": "long", "top": float(b.low[i]), "bottom": float(b.high[i - 2]), "done": False})
            elif b.low[i - 2] - b.high[i] > min_size:
                gaps.append({"c": i, "dir": "short", "top": float(b.low[i - 2]), "bottom": float(b.high[i]), "done": False})
    return out


DETECTORS = {
    "sweep": detect_sweeps,
    "bos": detect_bos,
    "orb": detect_orb,
    "fvg_retest": detect_fvg_retests,
}
