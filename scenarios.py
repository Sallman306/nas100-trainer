"""Scan every trading day for strategic points and save data/scenarios.parquet.

Usage:
    python scenarios.py
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from data_io.settings import load_settings
from detect.config import DetectConfig, load_detect_config
from detect.controls import control_candidates, control_count, pick_controls
from detect.detectors import DETECTORS, Bars, Day, Signal
from detect.indicators import atr, h1_trend_at, last_swing_levels
from detect.levels import LEVEL_COLUMNS, daily_levels, ny_times
from detect.outcomes import scenario_outcomes

BAR_MINUTES = 5


@dataclass
class Detection:
    """Detector output for the whole data set (before outcomes are attached)."""

    bars: Bars
    days: list[Day]
    signals: dict[int, list[Signal]]  # freeze position -> all signals on that bar
    candidates: list[int]             # no-trade control candidates


def make_bars(m5: pd.DataFrame, cfg: DetectConfig) -> Bars:
    """Price arrays and causal indicators for the detectors."""
    sh, sl = last_swing_levels(m5, cfg.swing_bars)
    return Bars(
        open=m5["open"].to_numpy(float), high=m5["high"].to_numpy(float),
        low=m5["low"].to_numpy(float), close=m5["close"].to_numpy(float),
        atr=atr(m5, cfg.atr_period).to_numpy(float), swing_high=sh, swing_low=sl,
    )


def window_days(m5: pd.DataFrame, cfg: DetectConfig) -> list[Day]:
    """Group the practice-window bars by NY date.

    A day is used only if it has a bar at the window start (causal: no need to know
    how many bars come later).
    """
    ny = ny_times(m5, cfg.tz)
    clock = ny.dt.time
    mask = (clock >= cfg.window_start) & (clock < cfg.window_end)
    by_day: dict = defaultdict(list)
    for pos in np.flatnonzero(mask.to_numpy()):
        by_day[ny.iloc[pos].date()].append(int(pos))
    days = [d for d, pos in sorted(by_day.items()) if clock.iloc[pos[0]] == cfg.window_start]
    levels = daily_levels(m5, days, cfg)
    return [
        Day(np.array(by_day[d]), [clock.iloc[p] for p in by_day[d]], levels.loc[d].to_dict())
        for d in days
    ]


def detect(m5: pd.DataFrame, cfg: DetectConfig) -> Detection:
    """Run all detectors on every day; collect control candidates."""
    m5 = m5.sort_values("time_utc").reset_index(drop=True)
    bars = make_bars(m5, cfg)
    days = window_days(m5, cfg)
    signals: dict[int, list[Signal]] = defaultdict(list)
    candidates: list[int] = []
    for day in days:
        day_positions: set[int] = set()
        for fn in DETECTORS.values():
            for sig in fn(bars, day, cfg):
                signals[sig.pos].append(sig)
                day_positions.add(sig.pos)
        candidates += control_candidates([int(p) for p in day.positions], day_positions, cfg.control_cooldown_bars)
    return Detection(bars, days, dict(signals), candidates)


def primary(sigs: list[Signal], priority: tuple[str, ...]) -> Signal:
    """The signal used to label a bar when several detectors fire on it."""
    rank = {name: i for i, name in enumerate(priority)}
    return min(sigs, key=lambda s: rank.get(s.detector, len(rank)))


def _day_context(day: Day, bars: Bars, cfg: DetectConfig) -> dict[int, dict[str, float]]:
    """Per freeze position: the opening range, only once it is complete."""
    start, end = cfg.opening_range
    rng = [p for p, t in zip(day.positions, day.clock) if start <= t < end]
    out = {}
    for p, t in zip(day.positions, day.clock):
        done = bool(rng) and t >= end
        out[int(p)] = {
            "or_high": float(bars.high[rng].max()) if done else float("nan"),
            "or_low": float(bars.low[rng].min()) if done else float("nan"),
        }
    return out


def build_scenarios(m1: pd.DataFrame, m5: pd.DataFrame, h1: pd.DataFrame, cfg: DetectConfig) -> pd.DataFrame:
    """Detections + controls + hidden outcomes, one row per scenario."""
    m5 = m5.sort_values("time_utc").reset_index(drop=True)
    m1 = m1.sort_values("time_utc").reset_index(drop=True)
    det = detect(m5, cfg)
    n_ctrl = control_count(len(det.signals), cfg.control_share)
    controls = set(pick_controls(det.candidates, n_ctrl, cfg.seed))
    b = det.bars
    rows = []
    for day in det.days:
        ctx = _day_context(day, b, cfg)
        for pos in (int(p) for p in day.positions):
            if pos in det.signals:
                sig = primary(det.signals[pos], cfg.priority)
                also = sorted({s.detector for s in det.signals[pos]} - {sig.detector})
            elif pos in controls:
                sig, also = Signal(pos, "no_trade", "none"), []
            else:
                continue
            t = m5["time_utc"].iloc[pos]
            risk = cfg.stop_atr * b.atr[pos]
            row = {
                "scenario_id": f"{t:%Y%m%d_%H%M}_{sig.detector}",
                "day_ny": str(t.tz_convert(cfg.tz).date()),
                "freeze_time_utc": t,
                "detector": sig.detector,
                "also_detected": "+".join(also),
                "direction_hint": sig.direction,
                "level_name": sig.level_name,
                "level_price": sig.level_price,
                **{k: day.levels[k] for k in LEVEL_COLUMNS},
                **ctx[pos],
                "fvg_top": sig.info.get("fvg_top", float("nan")),
                "fvg_bottom": sig.info.get("fvg_bottom", float("nan")),
                "swing_high": b.swing_high[pos],
                "swing_low": b.swing_low[pos],
                "close": b.close[pos],
                "atr": b.atr[pos],
                "h1_trend": h1_trend_at(h1, t + pd.Timedelta(minutes=BAR_MINUTES), cfg.h1_fast, cfg.h1_slow, cfg.h1_flat_atr),
            }
            row.update(scenario_outcomes(m1, t + pd.Timedelta(minutes=BAR_MINUTES),
                                         cfg.horizon_bars * BAR_MINUTES, b.close[pos], risk, cfg.target_r))
            rows.append(row)
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, n_days: int) -> None:
    """Counts per detector and average per trading day."""
    print(f"Trading days scanned: {n_days}")
    if df.empty:
        print("No scenarios found.")
        return
    counts = df["detector"].value_counts()
    print(f"{'detector':<12}{'count':>7}{'per day':>9}{'long':>6}{'short':>7}")
    for name, n in counts.items():
        sub = df[df["detector"] == name]
        print(f"{name:<12}{n:>7}{n / n_days:>9.2f}"
              f"{(sub['direction_hint'] == 'long').sum():>6}{(sub['direction_hint'] == 'short').sum():>7}")
    share = (df["detector"] == "no_trade").mean()
    print(f"{'TOTAL':<12}{len(df):>7}{len(df) / n_days:>9.2f}   no-trade share {share:.0%}")


def main() -> None:
    """Load M1/M5/H1 Parquet, build scenarios, save and summarise."""
    settings = load_settings()
    cfg = load_detect_config()
    m1 = pd.read_parquet(settings.parquet_path("M1"))
    m5 = pd.read_parquet(settings.parquet_path("M5"))
    h1 = pd.read_parquet(settings.parquet_path("H1"))
    df = build_scenarios(m1, m5, h1, cfg)
    path = settings.data_dir / cfg.scenarios_file
    df.to_parquet(path, index=False)
    print(f"Saved {path} : {len(df)} scenarios")
    print_summary(df, len(window_days(m5.sort_values("time_utc").reset_index(drop=True), cfg)))


if __name__ == "__main__":
    main()
