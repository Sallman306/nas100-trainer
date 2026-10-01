"""Rule-based round explanations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.grading import PlanChecks
from engine.replay import Order, simulate
from engine.story import market_story
from engine.trade_story import skip_story, trade_story

TZ = "America/New_York"
FREEZE = pd.Timestamp("2026-03-02 13:30", tz="UTC")  # 08:30 NY


def scenario(**kw) -> pd.Series:
    base = {"detector": "sweep", "direction_hint": "short", "level_name": "asian_high", "level_price": 105.0,
            "close": 100.0, "atr": 10.0, "h1_trend": "down", "freeze_time_utc": FREEZE,
            "asian_high": 105.0, "asian_low": 80.0, "london_high": float("nan"), "london_low": float("nan"),
            "pdh": 130.0, "pdl": 60.0, "or_high": float("nan"), "or_low": float("nan"),
            "fvg_top": float("nan"), "fvg_bottom": float("nan"),
            "long_hit_target": False, "short_hit_target": True, "long_best_r": 0.5, "short_best_r": 3.0,
            "best_possible_r": 3.0}
    base.update(kw)
    return pd.Series(base)


def bars(closes: list[float], start: pd.Timestamp, freq: str) -> pd.DataFrame:
    c = np.array(closes, float)
    o = np.concatenate([[100.0], c[:-1]])
    return pd.DataFrame({"time_utc": pd.date_range(start, periods=len(c), freq=freq, tz="UTC"),
                         "open": o, "high": np.maximum(o, c) + 1, "low": np.minimum(o, c) - 1, "close": c})


AFTER = bars([103, 104, 104, 95, 85, 76, 70, 72], FREEZE + pd.Timedelta(minutes=5), "5min")
BEFORE = bars([95, 97, 99, 100], FREEZE - pd.Timedelta(minutes=15), "5min")


def test_story_main_move_levels_and_verdict() -> None:
    st = market_story(scenario(), BEFORE, AFTER, TZ)
    assert st.main_dir == "down" and round(st.main_atr, 1) == 3.1
    assert st.levels_hit == {"asian_high": "rejected", "asian_low": "broke"}
    texts = [b["text"] for b in st.why]
    assert "WITH the H1 trend" in " ".join(texts) and "worked" in texts[-1] and st.why[-1]["tone"] == "good"
    assert st.why[0]["tone"] == "good"  # 3.1 ATR >= 3R: a big move
    assert "wicked above the Asian high" in st.trigger
    assert [e.time_utc for e in st.events] == sorted(e.time_utc for e in st.events)


def test_tight_stop_then_tp_reports_stop_needed() -> None:
    m1 = bars([103, 108, 104, 95, 85, 76, 70], FREEZE + pd.Timedelta(minutes=5), "1min")
    order = Order("short", "market", 100.0, 104.0, 80.0)
    end = FREEZE + pd.Timedelta(hours=1)
    trade = simulate(m1, order, FREEZE + pd.Timedelta(minutes=5), end, 100.0, 0.0)
    assert trade.exit_reason == "sl"
    checks = PlanChecks(5.0, True, False, True, 101.0)
    st = market_story(scenario(), BEFORE, AFTER, TZ)
    ts = trade_story(scenario(), order, trade, checks, st, m1, FREEZE + pd.Timedelta(minutes=5), end, TZ)
    assert ts.stop_needed == 109.0
    assert "stop too tight" in ts.lesson and any("hit your TP later" in p["text"] for p in ts.points)
    assert all(p["tone"] in ("good", "bad", "warn", "info") for p in ts.points)


def test_skip_story() -> None:
    st = market_story(scenario(), BEFORE, AFTER, TZ)
    assert "SHORT" in skip_story(scenario(), st).points[0]["text"]
    calm = scenario(short_hit_target=False)
    assert "patience" in skip_story(calm, st).lesson


def test_ideal_setup_takes_the_big_move() -> None:
    from engine.ideal import ideal_setup
    m1 = bars([101, 103, 99, 90, 80, 70, 65, 68], FREEZE + pd.Timedelta(minutes=5), "1min")
    ideal = ideal_setup(scenario(), m1, BEFORE, 0.0, 2, 3.0, TZ)
    assert ideal["decision"] == "short" and ideal["side"] == "short"
    assert ideal["sl"] == 105.0  # worst pullback 104 + 0.1 ATR buffer
    assert ideal["tp"] == round(100 - 0.9 * (100 - 64), 2) and ideal["r"] >= 3


def test_ideal_waits_for_the_top_when_price_spikes_first() -> None:
    from engine.ideal import ideal_setup
    # spike up to ~129 first, then a big drop to ~41; a short at the freeze would need a huge stop
    closes = [94, 90, 105, 125, 128, 118, 100, 80, 60, 45, 42]
    m5 = bars(closes, FREEZE + pd.Timedelta(minutes=5), "5min")
    ideal = ideal_setup(scenario(atr=5.0), m5, BEFORE, 0.0, 2, 3.0, TZ, after_m5=m5)
    assert ideal["kind"] == "wait" and ideal["side"] == "short" and ideal["decision"] == "short"
    assert ideal["sl"] > 129 and "WAIT" in ideal["points"][0]["text"]


def test_ideal_setup_says_skip_without_a_big_move() -> None:
    from engine.ideal import ideal_setup
    m1 = bars([101, 99, 102, 98, 101, 99], FREEZE + pd.Timedelta(minutes=5), "1min")
    ideal = ideal_setup(scenario(), m1, BEFORE, 0.0, 2, 3.0, TZ)
    assert ideal["decision"] == "skip" and "SKIP" in ideal["points"][0]["text"]
