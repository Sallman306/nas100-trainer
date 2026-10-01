"""The ideal setup: the best structural trade on the big move, found in hindsight.

Two kinds of plan, both sides, best R wins:
- "now": enter at market at the freeze (spread included), stop beyond the nearest
  swing at the freeze – or beyond the worst price before the move's extreme if that
  swing broke – and target 90% of the way to the extreme;
- "wait": let the turn happen first. Once an M5 candle closes beyond the range of
  the turning candle (the top before the big drop, or the bottom before the big
  rally), enter at that close, stop beyond the turn, target 90% of the move.
If even the best plan is below the big-move target, the ideal decision was to skip.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from detect.indicators import swing_points
from engine.story import bullet, ny_hhmm

TARGET_SHARE = 0.9   # take 90% of the move – nobody sells the exact top
STOP_BUFFER_ATR = 0.1
MIN_STOP_ATR = 0.5


def _last_swing(history_m5: pd.DataFrame, kind: str, beyond: float, long: bool, swing_bars: int) -> float:
    """Most recent confirmed swing low below (long) / high above (short) the entry; nan if none."""
    pts = swing_points(history_m5.reset_index(drop=True), swing_bars)
    pts = pts[(pts["kind"] == kind) & ((pts["price"] < beyond) if long else (pts["price"] > beyond))]
    return float(pts["price"].iloc[-1]) if len(pts) else float("nan")


def _plan(side: str, entry: float, fill: float, stop: float, extreme: float, extreme_time: pd.Timestamp,
          tp_time_fn, **extra) -> dict:
    """Common plan fields: target 90% of the way to the extreme, risk/reward in points and R."""
    long = side == "long"
    tp = fill + TARGET_SHARE * (extreme - fill) if long else fill - TARGET_SHARE * (fill - extreme)
    risk, reward = abs(fill - stop), (tp - fill) if long else (fill - tp)
    return {
        "side": side, "entry": round(entry, 2), "fill": round(fill, 2), "sl": round(stop, 2), "tp": round(tp, 2),
        "risk_pts": risk, "reward_pts": reward, "r": reward / risk if risk > 0 and reward > 0 else 0.0,
        "extreme": float(extreme), "extreme_time": extreme_time, "tp_time": tp_time_fn(tp) if reward > 0 else None,
        **extra,
    }


def now_plan(side: str, close: float, atr: float, spread: float, after_m1: pd.DataFrame,
             history_m5: pd.DataFrame, swing_bars: int) -> dict | None:
    """Enter at market at the freeze (see module doc)."""
    if after_m1.empty:
        return None
    long = side == "long"
    h, l = after_m1["high"].to_numpy(float), after_m1["low"].to_numpy(float)
    t = after_m1["time_utc"]
    fill = close + spread if long else close - spread
    k = int(h.argmax()) if long else int(l.argmin())
    adverse = float(l[:k + 1].min()) if long else float(h[:k + 1].max())
    swing = _last_swing(history_m5, "low" if long else "high", close, long, swing_bars)
    buffer = STOP_BUFFER_ATR * atr
    if long:
        base = adverse if not np.isfinite(swing) else min(swing, adverse)
        stop = min(base - buffer, fill - MIN_STOP_ATR * atr)
    else:
        base = adverse if not np.isfinite(swing) else max(swing, adverse)
        stop = max(base + buffer, fill + MIN_STOP_ATR * atr)
    used_swing = bool(np.isfinite(swing)) and ((swing <= adverse) if long else (swing >= adverse))

    def tp_time(tp: float) -> pd.Timestamp | None:
        hit = np.flatnonzero(h >= tp) if long else np.flatnonzero(l <= tp)
        return t.iloc[int(hit[0])] if hit.size else None

    return _plan(side, close, fill, stop, h[k] if long else l[k], t.iloc[k], tp_time,
                 kind="now", entry_time=None, stop_reason="swing" if used_swing else "adverse", swing=swing)


def wait_plan(side: str, atr: float, spread: float, after_m5: pd.DataFrame) -> dict | None:
    """Enter after the turn before the big move is confirmed (see module doc)."""
    if after_m5 is None or len(after_m5) < 3:
        return None
    long = side == "long"
    h, l, c = (after_m5[k].to_numpy(float) for k in ("high", "low", "close"))
    t = after_m5["time_utc"]
    k = int(h.argmax()) if long else int(l.argmin())          # the move's extreme
    if k < 2:
        return None
    p = int(l[:k].argmin()) if long else int(h[:k].argmax())  # the turn before it
    beyond = np.flatnonzero(c[p + 1:k] > h[p]) if long else np.flatnonzero(c[p + 1:k] < l[p])
    if not beyond.size:
        return None
    e = p + 1 + int(beyond[0])
    fill = c[e] + spread if long else c[e] - spread
    buffer = STOP_BUFFER_ATR * atr
    stop = min(l[p] - buffer, fill - MIN_STOP_ATR * atr) if long else max(h[p] + buffer, fill + MIN_STOP_ATR * atr)

    def tp_time(tp: float) -> pd.Timestamp | None:
        hit = np.flatnonzero(h[e + 1:] >= tp) if long else np.flatnonzero(l[e + 1:] <= tp)
        return t.iloc[e + 1 + int(hit[0])] if hit.size else None

    return _plan(side, float(c[e]), fill, stop, h[k] if long else l[k], t.iloc[k], tp_time,
                 kind="wait", entry_time=t.iloc[e], turn_time=t.iloc[p], turn_price=float(l[p] if long else h[p]))


def _describe(best: dict, big: bool, target_r: float, tz: str) -> list[dict]:
    """Short bullets for the chosen plan."""
    side, long = best["side"].upper(), best["side"] == "long"
    size = f"{best['r']:+.1f}R ({best['reward_pts']:.0f} pts for {best['risk_pts']:.0f} pts risk)"
    pts = [] if big else [bullet("warn", f"No {target_r:.0f}R move with a sensible stop – the ideal decision was SKIP")]
    if best["kind"] == "wait":
        turn = "bottom" if long else "top"
        pts.append(bullet("good" if big else "warn",
                          f"WAIT, then {side} at {best['entry']:.2f} ({ny_hhmm(best['entry_time'], tz)}) → {size}"))
        pts.append(bullet("info", f"Trigger: the {turn} at {best['turn_price']:.2f} ({ny_hhmm(best['turn_time'], tz)}) was "
                                  f"confirmed when a candle closed {'above its high' if long else 'below its low'}"))
        stop_why = f"just {'below the bottom' if long else 'above the top'} that started the move"
    else:
        pts.append(bullet("good" if big else "warn", f"{side} at market {best['entry']:.2f} (at the freeze) → {size}"))
        stop_why = (f"beyond the swing {'low' if long else 'high'} {best['swing']:.2f} – structure held"
                    if best["stop_reason"] == "swing" else "beyond the worst pullback before the move")
    pts.append(bullet("info", f"SL {best['sl']:.2f}: {stop_why}"))
    pts.append(bullet("info", f"TP {best['tp']:.2f}: 90% of the way to the {'high' if long else 'low'} "
                              f"{best['extreme']:.2f} ({ny_hhmm(best['extreme_time'], tz)})"
                              + (f", reached {ny_hhmm(best['tp_time'], tz)}" if best["tp_time"] is not None else "")))
    return pts


def ideal_setup(s: pd.Series, after_m1: pd.DataFrame, history_m5: pd.DataFrame, spread: float,
                swing_bars: int, target_r: float, tz: str, after_m5: pd.DataFrame | None = None) -> dict:
    """Pick the best plan (now / wait, long / short) and describe it in short bullets."""
    close, atr = float(s["close"]), float(s["atr"])
    plans = [now_plan(x, close, atr, spread, after_m1, history_m5, swing_bars) for x in ("long", "short")]
    plans += [wait_plan(x, atr, spread, after_m5) for x in ("long", "short")]
    plans = [p for p in plans if p]
    if not plans:
        return {"decision": "skip", "points": [bullet("info", "No data after the freeze.")]}
    best = max(plans, key=lambda p: p["r"])
    big = best["r"] >= target_r and best["reward_pts"] >= target_r * atr
    return {
        "decision": best["side"] if big else "skip", "side": best["side"], "kind": best["kind"],
        "entry": best["entry"], "sl": best["sl"], "tp": best["tp"], "r": round(best["r"], 2),
        "points": _describe(best, big, target_r, tz), "entry_time_utc": best["entry_time"],
    }
