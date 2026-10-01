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
from engine.export import write_export
from engine.feedback import progress_report, session_report
from engine.holding import bars_held
from engine.ideal import ideal_setup
from engine.story import Story, market_story
from engine.trade_story import TradeStory, skip_story, trade_story
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
        self._held: dict[tuple[str, str], int | None] = {}

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
            "mt5_offset_min": self._mt5_offset_min(freeze),
        })

    def _mt5_offset_min(self, t: pd.Timestamp) -> int:
        """Minutes to add to New York time to get the MT5 server clock (for the status bar)."""
        server = self.cfg.server_clock.from_utc(pd.DatetimeIndex([t]))[0]
        return int((server - t.tz_convert(self.cfg.tz).tz_localize(None)).total_seconds() // 60)

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
        story = market_story(s, self.market.history("M5", freeze, cfg.history_days.get("M5", 2)),
                             self.market.after("M5", freeze, end), cfg.tz, cfg.target_r)
        if decision == "skip":
            row.update(exit_reason=grade_skip(s), result_r=0.0, entry=None, sl=None, tp=None)
            mine = skip_story(s, story, cfg.target_r)
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
            mine = trade_story(s, order, trade, checks, story, self.market.bars["M1"],
                               self.market.freeze_end(freeze), end, cfg.tz)
        result["explain"] = self._explain(story, mine, ChartClock(freeze, cfg.tz, cfg.fake_date))
        m1 = self.market.bars["M1"]
        after_m1 = m1[(m1["time_utc"] >= self.market.freeze_end(freeze)) & (m1["time_utc"] < end)]
        ideal = ideal_setup(s, after_m1, self.market.history("M5", freeze, cfg.history_days.get("M5", 2)),
                            cfg.spread, cfg.swing_bars, cfg.target_r, cfg.tz, self.market.after("M5", freeze, end))
        when = ideal.pop("entry_time_utc", None)
        ideal["entry_time"] = ChartClock(freeze, cfg.tz, cfg.fake_date).to_chart(when) if when is not None else None
        result["explain"]["ideal"] = ideal
        result["target_r"] = cfg.target_r
        append_row(cfg.log_file, row)
        result.update({k: row.get(k) for k in ("result_r", "exit_reason", "filled", "rr_planned", "mfe_r", "mae_r",
                                                "sl_beyond_swing", "rr_ok", "with_bias", "best_possible_r")})
        result.update(self._reveal(rnd))
        rnd.result = result
        session = self.sessions[rnd.session_id]
        result.update(round_no=rnd.round_no, total_rounds=len(session.plan), session_done=session.done)
        return jsonable(result)

    def report(self, session_id: str) -> dict:
        """Session report: stats, splits, and coaching from the all-time log."""
        all_rows = self._rows()
        rows = [r for r in all_rows if r["session_id"] == session_id]
        if not rows and session_id not in self.sessions:
            raise RoundError("unknown session", 404)
        rep = session_report(rows, all_rows, self.cfg.feedback)
        return jsonable({"session_id": session_id, **rep, "rows": rows})

    def export(self, session_id: str) -> dict:
        """Write exports/session_<id>.md for AI coaching outside the app."""
        rows = read_rows(self.cfg.log_file, session_id)
        if not rows:
            raise RoundError("no logged rounds for this session", 404)
        try:
            path = write_export(rows, self.by_id, self.market, self.cfg, session_id)
        except ValueError as exc:
            raise RoundError(str(exc), 422) from exc
        return {"session_id": session_id, "path": str(path), "rounds": len(rows)}

    def progress(self) -> dict:
        """All-time tab: every logged session."""
        return jsonable(progress_report(self._rows(), self.cfg.feedback))

    def _rows(self) -> list[dict]:
        """All logged rows, each with "bars_held" (cached) for the quick-stop rule."""
        rows = read_rows(self.cfg.log_file)
        for r in rows:
            key = (r["session_id"], r["round"])
            if key not in self._held:
                scen = self.by_id.loc[r["scenario_id"]] if r["scenario_id"] in self.by_id.index else None
                self._held[key] = None if scen is None else bars_held(
                    r, scen, self.market, self.cfg.spread, self.cfg.timeout, self.cfg.tz)
            r["bars_held"] = self._held[key]
        return rows

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

    @staticmethod
    def _explain(story: Story, mine: TradeStory, chart: ChartClock) -> dict:
        """Explanation for the result card; event times converted to chart time."""
        return {
            "trigger": story.trigger, "context": story.context, "why": story.why,
            "main_dir": story.main_dir, "main_atr": round(story.main_atr, 2),
            "events": [{"time": chart.to_chart(e.time_utc), "text": e.text, "kind": e.kind, "price": e.price, "label": e.label}
                       for e in story.events],
            "trade": mine.points, "lesson": mine.lesson, "stop_needed": mine.stop_needed,
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
            "skip_grade": grade_skip(s), "freeze_time_ny": s["freeze_time_utc"].tz_convert(cfg.tz).strftime("%a %Y-%m-%d"),
            "freeze_close_ny": self.market.freeze_end(freeze).tz_convert(cfg.tz).strftime("%H:%M"),
            "replay": chart.bars_json(replay),
        }
