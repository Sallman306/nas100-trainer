"""Feedback engine: stats, splits, coaching rules and the 20-trade minimum."""
from __future__ import annotations

from dataclasses import replace

from engine.feedback import (FeedbackConfig, by_session, coaching, max_losing_streak, rule_against_bias,
                             rule_confidence, rule_giveback, rule_missed, rule_overtrade, rule_quick_stops,
                             rule_weak_setup, splits, stats)

CFG = FeedbackConfig()


def trade(r: float, *, side: str = "long", det: str = "sweep", conf: int = 3, mfe: float = 0.5,
          exit_reason: str | None = None, bars: int | None = 10, with_bias: bool = True, plan: bool = True,
          rr: float = 3.0, session: str = "20260901-090000-aaaa") -> dict:
    """A logged, filled trade row (strings like the CSV)."""
    reason = exit_reason or ("tp" if r > 0 else "sl")
    return {"session_id": session, "round": "1", "detector": det, "decision": side, "filled": "True",
            "result_r": str(r), "exit_reason": reason, "mfe_r": str(mfe), "confidence": str(conf),
            "rr_planned": str(rr), "sl_beyond_swing": str(plan), "rr_ok": str(plan), "with_bias": str(with_bias),
            "bars_held": bars}


def skip(reason: str = "correct_skip", det: str = "sweep", session: str = "20260901-090000-aaaa") -> dict:
    return {"session_id": session, "round": "1", "detector": det, "decision": "skip", "filled": "",
            "result_r": "0.0", "exit_reason": reason, "confidence": "3", "rr_planned": "",
            "sl_beyond_swing": "", "rr_ok": "", "with_bias": ""}


def test_stats_numbers() -> None:
    rows = [trade(3.0), trade(-1.0), trade(-1.0), trade(2.0, plan=False), skip(), skip("missed_opportunity"),
            {**trade(0.0), "filled": "False", "exit_reason": "not_filled"}]
    s = stats(rows)
    assert s["rounds"] == 7 and s["trades"] == 5 and s["filled"] == 4 and s["skips"] == 2
    assert s["win_rate"] == 0.5 and s["total_r"] == 3.0
    assert s["expectancy"] == 0.75          # per filled trade
    assert s["avg_r"] == 0.6                # per trade decision (unfilled = 0R)
    assert s["max_losing_streak"] == 2 and s["skip_accuracy"] == 0.5
    assert s["avg_rr_planned"] == 3.0 and s["plan_quality"] == 0.8


def test_empty_stats() -> None:
    s = stats([])
    assert s["trades"] == 0 and s["win_rate"] is None and s["expectancy"] is None and s["plan_quality"] is None


def test_losing_streak() -> None:
    assert max_losing_streak([1, -1, -1, 0.5, -1, -1, -1, 2]) == 3
    assert max_losing_streak([]) == 0


def test_splits_and_min_trades_verdict() -> None:
    rows = [trade(1.0, det="sweep", side="short", conf=5)] * 20 + [trade(-1.0, det="bos", conf=1)] * 5
    sp = splits(rows, 20)
    det = {g["key"]: g for g in sp["detector"]}
    assert det["sweep"]["verdict"] == "positive" and det["bos"]["verdict"] == "not_enough_data"
    assert {g["key"] for g in sp["side"]} == {"long", "short"}
    assert {g["key"] for g in sp["confidence"]} == {"1", "5"}


def test_every_rule_needs_twenty_trades() -> None:
    rows = [trade(-1.0, bars=1, mfe=2.5, with_bias=False)] * 19 + [skip("missed_opportunity")] * 19
    res = coaching(rows, CFG)
    assert res["work_on"] == []
    assert {r["status"] for r in res["rules"]} == {"not_enough_data"}


def test_quick_stops() -> None:
    rows = [trade(-1.0, bars=2)] * 12 + [trade(-1.0, bars=8)] * 4 + [trade(3.0)] * 4
    r = rule_quick_stops(rows, CFG)
    assert r["status"] == "work_on" and r["values"]["quick"] == 12 and r["r_lost"] == 12.0
    assert rule_quick_stops([trade(-1.0, bars=9)] * 20, CFG)["status"] == "ok"


def test_giveback() -> None:
    rows = [trade(-1.0, mfe=2.4)] * 5 + [trade(3.0, mfe=3.0)] * 15
    r = rule_giveback(rows, CFG)
    assert r["status"] == "work_on" and r["values"]["hits"] == 5 and r["r_lost"] == 15.0  # 5 x (2 - -1)
    assert rule_giveback([trade(3.0, mfe=3.0)] * 20, CFG)["status"] == "ok"


def test_weak_setup() -> None:
    rows = [trade(1.0, det="sweep")] * 20 + [trade(-0.5, det="bos")] * 20 + [trade(-1, det="orb")] * 3
    r = rule_weak_setup(rows, CFG)
    assert r["status"] == "work_on" and r["values"]["strong"] == "sweep" and r["values"]["weak"] == "bos"
    assert r["r_lost"] == 10.0
    assert rule_weak_setup(rows[:20] + rows[40:], CFG)["status"] == "not_enough_data"  # one setup only


def test_confidence() -> None:
    rows = [trade(-0.5, conf=5)] * 20 + [trade(0.5, conf=1)] * 20
    r = rule_confidence(rows, CFG)
    assert r["status"] == "work_on" and r["r_lost"] == 20.0
    rows = [trade(1.0, conf=4)] * 20 + [trade(-0.5, conf=2)] * 20
    assert rule_confidence(rows, CFG)["status"] == "ok"


def test_missed_and_overtrade() -> None:
    rows = [skip("missed_opportunity")] * 12 + [skip()] * 8
    r = rule_missed(rows, CFG)
    assert r["status"] == "work_on" and r["r_lost"] == 36.0
    controls = [trade(-1.0, det="no_trade")] * 15 + [skip(det="no_trade")] * 5
    r = rule_overtrade(controls, CFG)
    assert r["status"] == "work_on" and r["values"]["traded"] == 15 and r["r_lost"] == 15.0
    assert rule_overtrade([skip(det="no_trade")] * 20, CFG)["status"] == "ok"


def test_against_bias() -> None:
    rows = [trade(1.0)] * 20 + [trade(-1.0, with_bias=False)] * 20
    r = rule_against_bias(rows, CFG)
    assert r["status"] == "work_on" and r["r_lost"] == 40.0


def test_top_three_ranked_by_r_lost() -> None:
    rows = ([trade(-1.0, bars=1, mfe=2.5, with_bias=False, det="bos", conf=5)] * 20
            + [trade(2.0, with_bias=True, det="sweep", conf=1)] * 20
            + [skip("missed_opportunity")] * 20)
    res = coaching(rows, CFG)
    lost = [w["r_lost"] for w in res["work_on"]]
    assert len(lost) == 3 and lost == sorted(lost, reverse=True)
    fired = [r for r in res["rules"] if r["status"] == "work_on"]
    assert len(fired) > 3 and min(lost) >= max(r["r_lost"] for r in fired if r not in res["work_on"])
    assert len(coaching(rows, replace(CFG, top_items=1))["work_on"]) == 1


def test_by_session_points() -> None:
    rows = [trade(1.0, session="20260902-100000-bbbb"), trade(-1.0, session="20260901-090000-aaaa"),
            trade(3.0, session="20260902-100000-bbbb")]
    pts = by_session(rows)
    assert [p["session_id"] for p in pts] == ["20260901-090000-aaaa", "20260902-100000-bbbb"]
    assert pts[0]["date"] == "2026-09-01" and pts[1]["expectancy"] == 2.0 and pts[1]["plan_quality"] == 1.0
