"""Trade simulation on M1 bars: fills, TP/SL, time-out.

Rules (docs/spec.md, "Trade evaluation"):
- market entry fills at the freeze close + spread (spread always against the trader);
- a pending entry fills only if an M1 bar touches it before the time-out;
- TP/SL are checked on M1 bars; a bar touching both counts as SL (loss);
- on the fill bar of a pending order only the SL is checked (the TP may have come first);
- trades still open at the time-out close at the last bar's close.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SIDES = ("long", "short")
ORDER_TYPES = ("market", "pending")


@dataclass(frozen=True)
class Order:
    """A planned trade. `entry` is the planned price (the freeze close for market orders)."""

    side: str
    order_type: str
    entry: float
    sl: float
    tp: float

    @property
    def sign(self) -> float:
        """+1 for long, -1 for short."""
        return 1.0 if self.side == "long" else -1.0

    @property
    def risk(self) -> float:
        """Planned risk in points (1R)."""
        return abs(self.entry - self.sl)

    def validate(self) -> None:
        """Raise ValueError if the order is inconsistent."""
        if self.side not in SIDES or self.order_type not in ORDER_TYPES:
            raise ValueError(f"bad side/order_type: {self.side}/{self.order_type}")
        if not all(np.isfinite([self.entry, self.sl, self.tp])):
            raise ValueError("entry, sl and tp must be numbers")
        if self.side == "long" and not self.sl < self.entry < self.tp:
            raise ValueError("long needs SL < entry < TP")
        if self.side == "short" and not self.tp < self.entry < self.sl:
            raise ValueError("short needs TP < entry < SL")


@dataclass(frozen=True)
class TradeResult:
    """Outcome of one simulated trade (times are UTC)."""

    filled: bool
    fill_price: float
    fill_time: pd.Timestamp | None
    exit_price: float
    exit_time: pd.Timestamp | None
    exit_reason: str  # tp | sl | timeout | not_filled
    result_r: float
    mfe_r: float
    mae_r: float


def _find_fill(order: Order, ref: float, o: np.ndarray, h: np.ndarray, l: np.ndarray) -> tuple[int, float]:
    """Index of the fill bar and the raw (pre-spread) fill price; (-1, nan) if never touched."""
    if order.entry < ref:
        hits = np.flatnonzero(l <= order.entry)
        return (int(hits[0]), float(min(o[hits[0]], order.entry))) if hits.size else (-1, float("nan"))
    hits = np.flatnonzero(h >= order.entry)
    return (int(hits[0]), float(max(o[hits[0]], order.entry))) if hits.size else (-1, float("nan"))


def simulate(m1: pd.DataFrame, order: Order, start_utc: pd.Timestamp, timeout_utc: pd.Timestamp,
             ref_price: float, spread: float) -> TradeResult:
    """Run `order` on M1 bars opening in [start_utc, timeout_utc).

    start_utc is the close time of the freeze bar; ref_price is the freeze close.
    """
    order.validate()
    times = m1["time_utc"]
    lo, hi = times.searchsorted(start_utc), times.searchsorted(timeout_utc)
    bars = m1.iloc[lo:hi]
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t = bars["time_utc"].reset_index(drop=True)
    if order.order_type == "market":
        k, raw = 0, ref_price
    else:
        k, raw = _find_fill(order, ref_price, o, h, l)
        if k < 0:
            return TradeResult(False, float("nan"), None, float("nan"), None, "not_filled", 0.0, 0.0, 0.0)
    fill = raw + order.sign * spread
    if len(o) == 0:
        return TradeResult(True, fill, start_utc, fill, start_utc, "timeout", -spread / order.risk, 0.0, 0.0)
    fill_time = t.iloc[k] if order.order_type == "pending" else start_utc
    exit_i, exit_price, reason = len(o) - 1, float(c[-1]), "timeout"
    for i in range(k, len(o)):
        if order.side == "long":
            sl_hit, tp_hit = l[i] <= order.sl, h[i] >= order.tp
        else:
            sl_hit, tp_hit = h[i] >= order.sl, l[i] <= order.tp
        on_fill_bar = order.order_type == "pending" and i == k
        if on_fill_bar:
            tp_hit = False
        if sl_hit:
            gap = min(o[i], order.sl) if order.side == "long" else max(o[i], order.sl)
            exit_i, exit_price, reason = i, float(order.sl if on_fill_bar else gap), "sl"
            break
        if tp_hit:
            gap = max(o[i], order.tp) if order.side == "long" else min(o[i], order.tp)
            exit_i, exit_price, reason = i, float(gap), "tp"
            break
    seg_h, seg_l = h[k:exit_i + 1], l[k:exit_i + 1]
    fav = (seg_h.max() - fill) if order.side == "long" else (fill - seg_l.min())
    adv = (fill - seg_l.min()) if order.side == "long" else (seg_h.max() - fill)
    return TradeResult(
        filled=True, fill_price=fill, fill_time=fill_time,
        exit_price=exit_price, exit_time=t.iloc[exit_i], exit_reason=reason,
        result_r=order.sign * (exit_price - fill) / order.risk,
        mfe_r=max(float(fav), 0.0) / order.risk, mae_r=max(float(adv), 0.0) / order.risk,
    )
