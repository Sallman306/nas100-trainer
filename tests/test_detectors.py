"""Hand-built bar sequences for each detector."""
from __future__ import annotations

from datetime import time

import numpy as np

from detect.config import DetectConfig
from detect.detectors import Bars, Day, detect_bos, detect_fvg_retests, detect_orb, detect_sweeps

CFG = DetectConfig()


def bars(o, h, l, c, atr=10.0, sh=np.nan, sl=np.nan) -> Bars:
    n = len(o)
    return Bars(np.array(o, float), np.array(h, float), np.array(l, float), np.array(c, float),
                np.full(n, atr), np.full(n, sh), np.full(n, sl))


def day(n: int, levels: dict | None = None, start: int = 0, first: time = time(8, 0)) -> Day:
    clock = [time(first.hour + (first.minute + 5 * k) // 60, (first.minute + 5 * k) % 60) for k in range(n - start)]
    return Day(np.arange(start, n), clock, levels or {})


def test_sweep_single_wick_fires_short() -> None:
    b = bars([95, 96, 98], [97, 98, 101], [94, 95, 97], [96, 98, 99])
    sigs = detect_sweeps(b, day(3, {"asian_high": 100.0}), CFG)
    assert [(s.pos, s.direction, s.level_name) for s in sigs] == [(2, "short", "asian_high")]


def test_sweep_reclaim_within_three_bars() -> None:
    c = [95, 101, 102, 103, 99]
    b = bars(c, [x + 1 for x in c], [x - 1 for x in c], c)
    assert [s.pos for s in detect_sweeps(b, day(5, {"pdh": 100.0}), CFG)] == [4]


def test_sweep_too_slow_is_not_a_sweep() -> None:
    c = [95, 101, 102, 103, 104, 99]  # four closes beyond before the reclaim
    b = bars(c, [x + 1 for x in c], [x - 1 for x in c], c)
    assert detect_sweeps(b, day(6, {"pdh": 100.0}), CFG) == []


def test_sweep_low_fires_long_once_per_level() -> None:
    c = [105, 101, 101, 103, 101]
    lows = [104, 98, 100.5, 102, 99]
    b = bars(c, [x + 1 for x in c], lows, c)
    sigs = detect_sweeps(b, day(5, {"london_low": 100.0}), CFG)
    assert [(s.pos, s.direction) for s in sigs] == [(1, "long")]


def test_bos_needs_big_body_and_break() -> None:
    b = bars([95, 95], [99, 113], [94, 94], [98, 112], atr=10.0, sh=100.0, sl=80.0)
    assert [(s.pos, s.direction) for s in detect_bos(b, day(2, start=1), CFG)] == [(1, "long")]
    small = bars([95, 99], [99, 113], [94, 98], [98, 112], atr=10.0, sh=100.0, sl=80.0)  # body 13 < 15
    assert detect_bos(small, day(2, start=1), CFG) == []


def test_bos_short() -> None:
    b = bars([85, 85], [86, 86], [84, 60], [84, 66], atr=10.0, sh=120.0, sl=80.0)
    assert [(s.pos, s.direction) for s in detect_bos(b, day(2, start=1), CFG)] == [(1, "short")]


def test_orb_first_close_outside_each_side() -> None:
    # bars at 09:30, 09:35, 09:40 form the range 90..110; 09:45 breaks up, 09:55 breaks down
    c = [100, 105, 95, 111, 112, 89]
    h = [110, 108, 100, 112, 113, 101]
    l = [92, 90, 94, 99, 100, 88]
    b = bars(c, h, l, c)
    sigs = detect_orb(b, day(6, first=time(9, 30)), CFG)
    assert [(s.pos, s.direction, s.level_price) for s in sigs] == [(3, "long", 110.0), (5, "short", 90.0)]


def test_fvg_retest_long() -> None:
    o = [98, 100, 106, 108, 106]
    h = [100, 107, 109, 109, 107]
    l = [97, 99, 105, 106, 104]  # gap between bar0 high 100 and bar2 low 105
    c = [99, 106, 108, 107, 103]
    sigs = detect_fvg_retests(bars(o, h, l, c, atr=5.0), day(5), CFG)
    assert [(s.pos, s.direction, s.info["fvg_top"], s.info["fvg_bottom"]) for s in sigs] == [(4, "long", 105.0, 100.0)]


def test_fvg_closing_through_gap_is_not_a_retest() -> None:
    o = [98, 100, 106, 108, 106]
    h = [100, 107, 109, 109, 107]
    l = [97, 99, 105, 106, 95]
    c = [99, 106, 108, 107, 97]  # first touch closes below the gap
    assert detect_fvg_retests(bars(o, h, l, c, atr=5.0), day(5), CFG) == []
