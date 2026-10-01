"""Rule-based breakdown of the user's own decision: fill, exit, what the stop/target
needed to be, levels in the way, and one lesson. Short toned bullets (see story.bullet).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.grading import PlanChecks
from engine.replay import Order, TradeResult
from engine.story import LEVEL_LABELS, SETUP_NAMES, Story, bullet, ny_hhmm, scenario_levels


@dataclass
class TradeStory:
    """Bullets about the user's decision, a one-line lesson and an optional "stop needed" price."""

    points: list[dict]
    lesson: str
    stop_needed: float | None = None


def _window(m1: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """M1 bars opening in [start, end)."""
    t = m1["time_utc"]
    return m1.iloc[t.searchsorted(start):t.searchsorted(end)]


def _first(mask: np.ndarray) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def trade_story(s: pd.Series, order: Order, trade: TradeResult, checks: PlanChecks, story: Story,
                m1: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, tz: str) -> TradeStory:
    """Explain a long/short decision. `start`..`end` is the replay window (freeze close..time-out)."""
    atr, long = float(s["atr"]), order.side == "long"
    win = _window(m1, start, end)
    h, l = win["high"].to_numpy(float), win["low"].to_numpy(float)
    right_dir = story.main_dir == ("up" if long else "down")
    pts = [
        bullet("info", f"{order.side.upper()} · risk {order.risk:.0f} pts ({order.risk / atr:.1f} ATR) · "
                       f"target {abs(order.tp - order.entry):.0f} pts · R:R {checks.rr_planned:.1f}"),
        bullet("good" if right_dir else "bad",
               f"The big move went {story.main_dir.upper()} → your direction was {'right' if right_dir else 'wrong'}"),
    ]
    if not trade.filled:
        if len(h):
            closest = float(l.min()) if order.entry < float(s["close"]) else float(h.max())
            pts.append(bullet("bad", f"Entry {order.entry:.2f} never reached (closest {closest:.2f}, "
                                     f"{abs(closest - order.entry):.0f} pts away)"))
        return TradeStory(pts, "The entry never came. Enter at market, or put the limit where price actually trades.")

    minutes = int((trade.exit_time - trade.fill_time).total_seconds() // 60) if trade.exit_time is not None else 0
    how = "market" if order.order_type == "market" else "limit"
    pts.append(bullet("info", f"Filled {trade.fill_price:.2f} at {ny_hhmm(trade.fill_time, tz)} ({how})"))
    exit_name = {"tp": "TP hit", "sl": "SL hit", "timeout": "Closed at 17:00"}[trade.exit_reason]
    tone = "good" if trade.result_r > 0 else "bad" if trade.result_r < 0 else "info"
    pts.append(bullet(tone, f"{exit_name} at {ny_hhmm(trade.exit_time, tz)} after {minutes} min → {trade.result_r:+.2f}R"))
    pts.append(bullet("info", f"Best open profit {trade.mfe_r:+.2f}R · worst −{trade.mae_r:.2f}R"))
    if checks.swing_price == checks.swing_price:
        side = "low" if long else "high"
        pts.append(bullet("good", f"SL beyond the swing {side} {checks.swing_price:.2f} (protected by structure)")
                   if checks.sl_beyond_swing else
                   bullet("bad", f"SL inside the swing {side} {checks.swing_price:.2f} – in the noise"))

    fill_i = int(win["time_utc"].searchsorted(trade.fill_time)) if len(win) else 0
    tp_mask = h >= order.tp if long else l <= order.tp
    tp_i = _first(tp_mask[fill_i:])
    levels = scenario_levels(s)
    for k in (k for k, p in levels.items() if (order.entry < p < order.tp) or (order.tp < p < order.entry)):
        status = story.levels_hit.get(k)
        if tp_i is not None:
            pts.append(bullet("info", f"{LEVEL_LABELS[k].capitalize()} {levels[k]:.2f} was in the way – price got through"))
        elif status == "rejected":
            pts.append(bullet("bad", f"{LEVEL_LABELS[k].capitalize()} {levels[k]:.2f} blocked your TP – price turned there"))
        else:
            pts.append(bullet("info", f"{LEVEL_LABELS[k].capitalize()} {levels[k]:.2f} sat before your TP"))

    stop_needed, lesson = None, ""
    if trade.exit_reason == "sl":
        if tp_i is not None:
            k = fill_i + tp_i
            stop_needed = float(l[fill_i:k + 1].min()) if long else float(h[fill_i:k + 1].max())
            need = abs(trade.fill_price - stop_needed)
            pts.append(bullet("bad", f"Price hit your TP later ({ny_hhmm(win['time_utc'].iloc[k], tz)}). "
                                     f"Stop needed: beyond {stop_needed:.2f} ({need:.0f} pts / {need / atr:.1f} ATR)"))
            lesson = (f"Right idea, stop too tight. Put the SL beyond the level that kills the idea "
                      f"(here {stop_needed:.2f}) and trade smaller.")
        elif right_dir:
            lesson = "Right direction, bad timing: you were stopped before the big move. Wait for the trigger or use a structural stop."
        elif str(s["h1_trend"]) in ("up", "down") and (s["h1_trend"] == "up") != long:
            lesson = "You fought the H1 trend and the trend won. Trade with the H1 bias, or wait for a clear reversal."
        else:
            lesson = f"Wrong direction: price was drawn {story.main_dir} toward liquidity. Check which level price is hunting first."
    elif trade.exit_reason == "tp":
        rest = h[fill_i:] if long else l[fill_i:]
        best_r = ((float(rest.max()) - trade.fill_price) if long else (trade.fill_price - float(rest.min()))) / order.risk
        if best_r > trade.result_r + 1.0:
            pts.append(bullet("info", f"Price kept going to {best_r:+.1f}R – a runner would have paid more"))
            lesson = "Good trade. Take part at the target and let a runner ride to the next key level."
        else:
            lesson = "Good trade – plan and outcome matched. Repeat this process."
    else:
        pts.append(bullet("bad", f"TP needed {checks.rr_planned:.1f}R, the trade only reached {trade.mfe_r:+.1f}R"))
        lesson = "The target was beyond what the day offered. Aim at the nearest key level."
    return TradeStory(pts, lesson, stop_needed)


def skip_story(s: pd.Series, story: Story, target_r: float = 3.0) -> TradeStory:
    """Explain a skip: was there a big (+target_r) trade, and which side."""
    long_ok, short_ok = bool(s["long_hit_target"]), bool(s["short_hit_target"])
    if not (long_ok or short_ok):
        return TradeStory([bullet("good", f"No {target_r:.0f}R move either way (1-ATR stop) – nothing big to catch")],
                          "Good patience. Skipping is a position.")
    sides = " and ".join(x for x, ok in (("LONG", long_ok), ("SHORT", short_ok)) if ok)
    pts = [bullet("bad", f"A {sides} from the freeze price made +{target_r:.0f}R before −1R (1-ATR stop)")]
    if s["detector"] == "no_trade":
        return TradeStory(pts, "No setup was present, so missing this is fine – a move without a signal is not an edge.")
    return TradeStory(pts, f"The {SETUP_NAMES.get(str(s['detector']), s['detector'])} signal worked here. "
                           f"Review the setup and what stopped you from taking it.")
