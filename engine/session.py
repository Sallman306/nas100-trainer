"""Practice sessions: serve rounds frozen at the freeze bar, take decisions, grade, log."""
from __future__ import annotations

import time as clock
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from engine.config import PracticeConfig
from engine.grading import grade_skip, plan_checks
from engine.market import CHART_TFS, ChartClock, MarketData, timeout_utc
from engine.picker import plan_session
from engine.replay import Order, simulate
from engine.report import session_stats
from engine.tradelog import append_row, played_ids, read_rows

LEVELS = [("asian_high", "Asian H"), ("asian_low", "Asian L"), ("london_high", "London H"),
          ("london_low", "London L"), ("pdh", "PDH"), ("pdl", "PDL")]
DECISIONS = ("long", "short", "skip")


def jsonable(value: object) -> object:
    """Recursively turn numpy scalars into Python ones and NaN into None."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


class RoundError(Exception):
    """A request that cannot be served (unknown id, already committed, bad input)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Round:
    """One served round and, once committed, its result."""

    round_id: str
    session_id: str
    round_no: int
    scenario: pd.Series
    served_at: float
    result: dict | None = None


@dataclass
class Session:
    """A practice session: the planned scenarios and the rounds served so far."""

    session_id: str
    drill: str | None
    plan: list[str]
    rounds: list[Round] = field(default_factory=list)

    @property
    def done(self) -> bool:
        """All planned rounds committed."""
        return len(self.rounds) == len(self.plan) and all(r.result for r in self.rounds)


class Practice:
    """Session manager used by server.py."""

    def __init__(self, market: MarketData, cfg: PracticeConfig, seed: int | None = None) -> None:
        self.market = market
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.sessions: dict[str, Session] = {}
        self.rounds: dict[str, Round] = {}
        self.by_id = market.scenarios.set_index("scenario_id", drop=False)

    # ----- sessions and rounds -----
    def new_session(self, drill: str | None = None, rounds: int | None = None) -> Session:
        """Plan a new session (unplayed scenarios first)."""
        n = rounds or self.cfg.session_rounds
        try:
            plan = plan_session(self.market.scenarios, n, drill or None, played_ids(self.cfg.log_file),
                                self.cfg.no_trade_share, self.rng)
        except ValueError as exc:
            raise RoundError(str(exc), 404) from exc
        sid = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        session = Session(sid, drill or None, plan)
        self.sessions[sid] = session
        return session

    def next_round(self, session_id: str | None, drill: str | None = None, rounds: int | None = None) -> dict:
        """Serve the next round (re-serves an uncommitted one); {"done": True} at the end."""
        session = self.sessions.get(session_id or "") or self.new_session(drill, rounds)
        if session.rounds and session.rounds[-1].result is None:
            return self._payload(session.rounds[-1], session)
        if len(session.rounds) >= len(session.plan):
            return {"done": True, "session_id": session.session_id}
        scen = self.by_id.loc[session.plan[len(session.rounds)]]
        rnd = Round(uuid.uuid4().hex[:12], session.session_id, len(session.rounds) + 1, scen, clock.monotonic())
        session.rounds.append(rnd)
        self.rounds[rnd.round_id] = rnd
        return self._payload(rnd, session)

    def _payload(self, rnd: Round, session: Session) -> dict:
        """Everything the browser needs to draw the frozen chart (no hidden fields)."""
        s, cfg = rnd.scenario, self.cfg
        freeze = s["freeze_time_utc"]
        chart = ChartClock(freeze, cfg.tz, cfg.fake_date)
        charts = {tf: chart.bars_json(self.market.history(tf, freeze, cfg.history_days.get(tf, 2))) for tf in CHART_TFS}
        levels = [{"name": label, "price": round(float(s[k]), 2)} for k, label in LEVELS if pd.notna(s[k])]
        return jsonable({
            "done": False, "session_id": session.session_id, "round_id": rnd.round_id,
            "round_no": rnd.round_no, "total_rounds": len(session.plan), "drill": session.drill,
            "freeze_time": chart.to_chart(freeze), "price": round(float(s["close"]), 2),
            "atr": round(float(s["atr"]), 2), "spread": cfg.spread, "min_rr": cfg.min_rr,
            "timeout": cfg.timeout.strftime("%H:%M"), "charts": charts, "levels": levels,
        })

    # ----- commit -----
    def submit(self, round_id: str, form: dict) -> dict:
        """Grade a committed decision, log it, return the result and replay bars."""
        rnd = self.rounds.get(round_id)
        if rnd is None:
            raise RoundError("unknown round", 404)
        if rnd.result is not None:
            raise RoundError("round already committed", 409)
        decision = form.get("decision")
        if decision not in DECISIONS:
            raise RoundError("decision must be long, short or skip", 422)
        s, cfg = rnd.scenario, self.cfg
        freeze = s["freeze_time_utc"]
        end = timeout_utc(freeze, cfg.timeout, cfg.tz)
        row = self._base_row(rnd, form)
        result: dict = {"decision": decision}
        if decision == "skip":
            row.update(exit_reason=grade_skip(s), result_r=0.0, entry=None, sl=None, tp=None)
        else:
            price = round(float(s["close"]), 2)  # the price the user saw
            order = self._order(decision, form, price)
            trade = simulate(self.market.bars["M1"], order, self.market.freeze_end(freeze), end, price, cfg.spread)
            checks = plan_checks(order, self.market.history("M5", freeze, cfg.history_days.get("M5", 2)),
                                 str(s["h1_trend"]), cfg.min_rr, cfg.swing_bars)
            row.update(entry=order.entry, sl=order.sl, tp=order.tp, rr_planned=checks.rr_planned,
                       filled=trade.filled, result_r=trade.result_r, exit_reason=trade.exit_reason,
                       mfe_r=trade.mfe_r if trade.filled else None, mae_r=trade.mae_r if trade.filled else None,
                       sl_beyond_swing=checks.sl_beyond_swing, rr_ok=checks.rr_ok, with_bias=checks.with_bias)
            chart = ChartClock(freeze, cfg.tz, cfg.fake_date)
            result.update(order_type=order.order_type, fill_price=trade.fill_price, exit_price=trade.exit_price,
                          fill_time=chart.to_chart(trade.fill_time) if trade.fill_time is not None else None,
                          exit_time=chart.to_chart(trade.exit_time) if trade.exit_time is not None else None,
                          swing_price=checks.swing_price)
        append_row(cfg.log_file, row)
        result.update({k: row.get(k) for k in ("result_r", "exit_reason", "filled", "rr_planned", "mfe_r", "mae_r",
                                                "sl_beyond_swing", "rr_ok", "with_bias", "best_possible_r")})
        result.update(self._reveal(rnd))
        rnd.result = result
        session = self.sessions[rnd.session_id]
        result.update(round_no=rnd.round_no, total_rounds=len(session.plan), session_done=session.done)
        return jsonable(result)

    def report(self, session_id: str) -> dict:
        """Logged rounds of a session and their basic stats."""
        rows = read_rows(self.cfg.log_file, session_id)
        if not rows and session_id not in self.sessions:
            raise RoundError("unknown session", 404)
        return {"session_id": session_id, "stats": jsonable(session_stats(rows)), "rows": rows}

    def _order(self, decision: str, form: dict, close: float) -> Order:
        """Build and validate the order; market orders use the freeze close as entry."""
        order_type = form.get("order_type", "market")
        try:
            entry = close if order_type == "market" else float(form["entry"])
            order = Order(decision, order_type, entry, float(form["sl"]), float(form["tp"]))
            order.validate()
        except (KeyError, TypeError, ValueError) as exc:
            raise RoundError(f"invalid order: {exc}", 422) from exc
        return order

    def _base_row(self, rnd: Round, form: dict) -> dict:
        """Trade-log fields shared by trades and skips."""
        s = rnd.scenario
        tfs = form.get("tf_used") or ["M5"]
        return {
            "session_id": rnd.session_id, "round": rnd.round_no, "scenario_id": s["scenario_id"],
            "detector": s["detector"], "decision": form["decision"],
            "freeze_time_ny": s["freeze_time_utc"].tz_convert(self.cfg.tz).strftime("%Y-%m-%d %H:%M"),
            "tf_used": "+".join(tfs) if isinstance(tfs, list) else str(tfs),
            "setup_tag": form.get("setup_tag", ""), "bias_tag": form.get("bias_tag", ""),
            "confidence": form.get("confidence", ""), "note": str(form.get("note", ""))[:500],
            "best_possible_r": float(s["best_possible_r"]),
            "seconds_to_decide": round(clock.monotonic() - rnd.served_at, 1),
        }

    def _reveal(self, rnd: Round) -> dict:
        """Hidden answers shown after commit: detector, best possible trade, replay bars."""
        s, cfg = rnd.scenario, self.cfg
        freeze = s["freeze_time_utc"]
        chart = ChartClock(freeze, cfg.tz, cfg.fake_date)
        replay = self.market.after("M5", freeze, timeout_utc(freeze, cfg.timeout, cfg.tz))
        best_side = "long" if s["long_best_r"] >= s["short_best_r"] else "short"
        return {
            "detector": s["detector"], "also_detected": s["also_detected"], "direction_hint": s["direction_hint"],
            "level_name": s["level_name"], "level_price": None if pd.isna(s["level_price"]) else float(s["level_price"]),
            "h1_trend": s["h1_trend"], "best_side": best_side, "best_possible_r": float(s["best_possible_r"]),
            "skip_grade": grade_skip(s), "freeze_time_ny": s["freeze_time_utc"].tz_convert(cfg.tz).strftime("%a %Y-%m-%d %H:%M"),
            "replay": chart.bars_json(replay),
        }
