"""Rule-based breakdown of the user's own decision: fill, exit, what the stop/target
needed to be, levels in the way, and one lesson.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.grading import PlanChecks
from engine.replay import Order, TradeResult
from engine.story import LEVEL_LABELS, SETUP_NAMES, Story, ny_hhmm, scenario_levels


@dataclass
class TradeStory:
    """Bullets about the user's trade, a one-line lesson and an optional "stop needed" price."""

    points: list[str]
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
    pts: list[str] = []
    stop_needed = None
    win = _window(m1, start, end)
    h, l = win["high"].to_numpy(float), win["low"].to_numpy(float)

    against = story.main_dir != ("up" if long else "down")
    trend = str(s["h1_trend"])
    pts.append(f"You went {order.side.upper()} with risk {order.risk:.1f} pts ({order.risk / atr:.2f} ATR) and target "
               f"{abs(order.tp - order.entry):.1f} pts (R:R {checks.rr_planned:.2f}). "
               f"The main move was {story.main_dir.upper()} {story.main_atr:.1f} ATR – "
               + ("AGAINST your direction." if against else "IN your direction."))

    if not trade.filled:
        if len(h):
            closest = float(l.min()) if order.entry < float(s["close"]) else float(h.max())
            pts.append(f"Your pending entry at {order.entry:.2f} was never reached; the closest price was {closest:.2f} "
                       f"({abs(closest - order.entry):.1f} pts away).")
        return TradeStory(pts, "The entry never came. If the setup is valid at the freeze, enter at market or place the "
                               "limit where price actually trades (e.g. the gap/level edge).")

    minutes = int((trade.exit_time - trade.fill_time).total_seconds() // 60) if trade.exit_time is not None else 0
    fill_txt = "at market" if order.order_type == "market" else f"when price came to {order.entry:.2f}"
    pts.append(f"Filled {fill_txt} at {trade.fill_price:.2f} (spread included) at {ny_hhmm(trade.fill_time, tz)} ET.")
    reason = {"tp": "hit your TP", "sl": "hit your SL", "timeout": "was closed by the 17:00 time-out"}[trade.exit_reason]
    pts.append(f"The trade {reason} at {ny_hhmm(trade.exit_time, tz)} ET after {minutes} min, result {trade.result_r:+.2f}R. "
               f"Best open profit along the way: {trade.mfe_r:+.2f}R, worst drawdown: -{trade.mae_r:.2f}R.")

    if checks.swing_price == checks.swing_price:
        side = "below the swing low" if long else "above the swing high"
        pts.append(f"Your SL was {'' if checks.sl_beyond_swing else 'NOT '}{side} at {checks.swing_price:.2f}"
                   + (" – it was protected by structure." if checks.sl_beyond_swing else
                      " – it sat inside normal noise where a retest could take it."))

    fill_i = int(win["time_utc"].searchsorted(trade.fill_time)) if len(win) else 0
    tp_mask = h >= order.tp if long else l <= order.tp
    tp_i = _first(tp_mask[fill_i:])

    levels = scenario_levels(s)
    blockers = [k for k, p in levels.items() if (order.entry < p < order.tp) or (order.tp < p < order.entry)]
    for k in blockers:
        status = story.levels_hit.get(k)
        if tp_i is not None:
            tail = " Price paused there but eventually reached your TP." if status == "rejected" else " Price got through it."
        else:
            tail = {"rejected": " Price tested it and turned – it blocked your target.",
                    "broke": " Price broke through it but still fell short of your TP."}.get(status or "", " Price never got there.")
        pts.append(f"The {LEVEL_LABELS[k]} ({levels[k]:.2f}) sat between your entry and TP.{tail}")
    lesson = ""
    if trade.exit_reason == "sl":
        if tp_i is not None:
            k = fill_i + tp_i
            stop_needed = float(l[fill_i:k + 1].min()) if long else float(h[fill_i:k + 1].max())
            t_tp = win["time_utc"].iloc[k]
            need = abs(trade.fill_price - stop_needed)
            pts.append(f"After stopping you out, price DID reach your TP at {ny_hhmm(t_tp, tz)} ET. To survive, the stop "
                       f"needed to be beyond {stop_needed:.2f} (risk {need:.1f} pts = {need / atr:.1f} ATR instead of "
                       f"{order.risk:.1f}). Your direction was right – the stop was too tight.")
            lesson = (f"Right idea, stop too tight: put the SL beyond the level that invalidates the setup "
                      f"(here beyond {stop_needed:.2f}) and size the position down instead.")
        else:
            pts.append("Price never reached your TP before 17:00 – the direction/target was wrong, not only the stop.")
            if against and trend in ("up", "down") and (trend == "up") != long:
                lesson = "You traded against the H1 trend and the trend won. Trade with the H1 bias or wait for a confirmed reversal."
            else:
                lesson = (f"The direction was wrong: price was drawn {story.main_dir} toward liquidity. Before entering, "
                          f"check which nearby level price is more likely to run for.")
    elif trade.exit_reason == "tp":
        rest = h[fill_i:] if long else l[fill_i:]
        best = (float(rest.max()) - trade.fill_price) if long else (trade.fill_price - float(rest.min()))
        best_r = best / order.risk
        if best_r > trade.result_r + 1.0:
            pts.append(f"Price kept going to {best_r:+.1f}R before 17:00 – a runner or a target at the next level would "
                       f"have paid more.")
            lesson = "Good trade. Consider taking part at 2R and leaving a runner to the next key level."
        else:
            pts.append("Price did not go much further after your TP – a well-placed target.")
            lesson = "Good trade: plan and outcome matched. Repeat this exact process."
    else:
        pts.append(f"Neither SL nor TP was hit by 17:00. The TP needed {checks.rr_planned:.1f}R but the trade only reached "
                   f"{trade.mfe_r:+.1f}R.")
        lesson = "The target was beyond what the day offered – aim for the nearest key level instead of a fixed far target."
    return TradeStory(pts, lesson, stop_needed)


def skip_story(s: pd.Series, story: Story) -> TradeStory:
    """Explain a skip: was there a +2R trade, and which side."""
    long_ok, short_ok = bool(s["long_hit_target"]), bool(s["short_hit_target"])
    if not (long_ok or short_ok):
        return TradeStory(["Neither a long nor a short with a 1-ATR stop reached +2R before -1R."],
                          "Good patience – nothing clean happened. Skipping is a position.")
    sides = " and ".join(x for x, ok in (("LONG", long_ok), ("SHORT", short_ok)) if ok)
    pts = [f"A {sides} at the freeze price with a 1-ATR stop reached +2R before the stop.",
           f"Best possible: {float(s['best_possible_r']):+.1f}R ({'long' if s['long_best_r'] >= s['short_best_r'] else 'short'})."]
    if s["detector"] == "no_trade":
        return TradeStory(pts, "No setup was present, so missing this is fine – a move without a signal is not an edge.")
    return TradeStory(pts, f"The {SETUP_NAMES.get(str(s['detector']), s['detector'])} signal was valid and worked. Review the trigger "
                           f"above and ask what stopped you from taking it.")
