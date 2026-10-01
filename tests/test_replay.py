"""Fill and TP/SL resolution on M1 bars."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.replay import Order, simulate

START = pd.Timestamp("2026-03-02 13:40", tz="UTC")  # freeze bar close (08:40 NY)
TIMEOUT = pd.Timestamp("2026-03-02 17:00", tz="UTC")  # 12:00 NY


def m1(rows: list[tuple[float, float, float, float]], start: pd.Timestamp = START) -> pd.DataFrame:
    """M1 bars from (open, high, low, close) tuples, one minute apart."""
    times = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"time_utc": times, "open": o, "high": h, "low": l, "close": c})


def run(rows, order, spread=1.0, start=START, timeout=TIMEOUT):
    return simulate(m1(rows, start), order, start, timeout, 100.0, spread)


def test_market_long_hits_tp() -> None:
    res = run([(100, 105, 99, 104), (104, 121, 103, 120)], Order("long", "market", 100, 90, 120))
    assert res.filled and res.exit_reason == "tp"
    assert res.fill_price == 101.0 and res.exit_price == 120.0
    assert res.result_r == pytest.approx((120 - 101) / 10)


def test_same_bar_tp_and_sl_is_loss() -> None:
    res = run([(100, 125, 85, 100)], Order("long", "market", 100, 90, 120))
    assert res.exit_reason == "sl" and res.result_r == pytest.approx((90 - 101) / 10)


def test_short_market_sl() -> None:
    res = run([(100, 102, 98, 101), (101, 111, 100, 110)], Order("short", "market", 100, 110, 80), spread=1.5)
    assert res.fill_price == 98.5 and res.exit_reason == "sl"
    assert res.result_r == pytest.approx(-(110 - 98.5) / 10)


def test_pending_never_touched_is_not_filled() -> None:
    res = run([(100, 101, 96, 97)] * 5, Order("long", "pending", 95, 90, 110))
    assert not res.filled and res.exit_reason == "not_filled" and res.result_r == 0.0


def test_pending_touch_after_timeout_is_not_filled() -> None:
    late = TIMEOUT - pd.Timedelta(minutes=1)
    rows = [(100, 101, 99, 100), (100, 101, 94, 95)]  # touch happens at 12:00, i.e. too late
    res = simulate(m1(rows, late), Order("long", "pending", 95, 90, 110), late, TIMEOUT, 100.0, 1.0)
    assert not res.filled


def test_pending_fill_bar_counts_sl_not_tp() -> None:
    res = run([(100, 112, 89, 100)], Order("long", "pending", 95, 90, 110))
    assert res.filled and res.exit_reason == "sl" and res.exit_price == 90
    res = run([(100, 111, 94, 100), (100, 101, 99, 100)], Order("long", "pending", 95, 90, 110))
    assert res.exit_reason == "timeout"  # TP on the fill bar may have come before the fill


def test_buy_stop_above_price_and_gap_fill() -> None:
    res = run([(100, 103, 99, 102), (106, 107, 105, 106), (106, 131, 105, 130)], Order("long", "pending", 104, 94, 124))
    assert res.fill_price == 107.0  # gapped over 104 -> opened at 106, + spread 1
    assert res.exit_reason == "tp"


def test_gap_through_stop_exits_at_open() -> None:
    res = run([(100, 101, 99, 100), (85, 86, 84, 85)], Order("long", "market", 100, 90, 120))
    assert res.exit_reason == "sl" and res.exit_price == 85


def test_timeout_exits_at_last_close_and_ignores_later_bars() -> None:
    start = TIMEOUT - pd.Timedelta(minutes=2)
    rows = [(100, 102, 99, 101), (101, 103, 100, 102), (102, 200, 101, 199)]  # 3rd bar is at 12:00
    res = simulate(m1(rows, start), Order("long", "market", 100, 90, 150), start, TIMEOUT, 100.0, 1.0)
    assert res.exit_reason == "timeout" and res.exit_price == 102
    assert res.mfe_r == pytest.approx((103 - 101) / 10)


def test_invalid_order_rejected() -> None:
    with pytest.raises(ValueError):
        Order("long", "market", 100, 110, 120).validate()
    with pytest.raises(ValueError):
        Order("short", "market", 100, 90, 80).validate()
