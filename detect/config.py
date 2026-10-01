"""Typed settings for scenario detection, read from config.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path

import yaml

from data_io.settings import DEFAULT_CONFIG, _parse_time


@dataclass(frozen=True)
class DetectConfig:
    """Everything scenarios.py needs besides the data layer settings."""

    tz: str = "America/New_York"
    window_start: time = time(8, 0)
    window_end: time = time(10, 0)
    asian: tuple[time, time] = (time(20, 0), time(0, 0))
    london: tuple[time, time] = (time(2, 0), time(5, 0))
    day_start: time = time(18, 0)
    atr_period: int = 14
    swing_bars: int = 2
    sweep_reclaim_bars: int = 3
    displacement_atr: float = 1.5
    opening_range: tuple[time, time] = (time(9, 30), time(9, 45))
    fvg_min_atr: float = 0.1
    priority: tuple[str, ...] = ("sweep", "fvg_retest", "bos", "orb")
    control_share: float = 0.25
    control_cooldown_bars: int = 3
    seed: int = 7
    horizon_bars: int = 120
    stop_atr: float = 1.0
    target_r: float = 3.0
    h1_fast: int = 20
    h1_slow: int = 50
    h1_flat_atr: float = 0.1
    scenarios_file: str = "scenarios.parquet"


def _pair(values: list[str]) -> tuple[time, time]:
    """Parse ["HH:MM", "HH:MM"] into a (start, end) pair of times."""
    return _parse_time(values[0]), _parse_time(values[1])


def load_detect_config(path: Path | str = DEFAULT_CONFIG) -> DetectConfig:
    """Read the detection sections of config.yaml (missing keys keep defaults)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    session = raw.get("session", {})
    lv = raw.get("levels", {})
    det = raw.get("detectors", {})
    ctl = raw.get("controls", {})
    out = raw.get("outcome", {})
    h1 = raw.get("h1_trend", {})
    d = DetectConfig()
    return DetectConfig(
        tz=session.get("tz", d.tz),
        window_start=_parse_time(session.get("start", "08:00")),
        window_end=_parse_time(session.get("end", "10:00")),
        asian=_pair(lv["asian"]) if "asian" in lv else d.asian,
        london=_pair(lv["london"]) if "london" in lv else d.london,
        day_start=_parse_time(lv.get("day_start", "18:00")),
        atr_period=int(det.get("atr_period", d.atr_period)),
        swing_bars=int(det.get("swing_bars", d.swing_bars)),
        sweep_reclaim_bars=int(det.get("sweep_reclaim_bars", d.sweep_reclaim_bars)),
        displacement_atr=float(det.get("displacement_atr", d.displacement_atr)),
        opening_range=_pair(det["opening_range"]) if "opening_range" in det else d.opening_range,
        fvg_min_atr=float(det.get("fvg_min_atr", d.fvg_min_atr)),
        priority=tuple(det.get("priority", d.priority)),
        control_share=float(ctl.get("share", d.control_share)),
        control_cooldown_bars=int(ctl.get("cooldown_bars", d.control_cooldown_bars)),
        seed=int(ctl.get("seed", d.seed)),
        horizon_bars=int(out.get("horizon_bars", d.horizon_bars)),
        stop_atr=float(out.get("stop_atr", d.stop_atr)),
        target_r=float(out.get("target_r", d.target_r)),
        h1_fast=int(h1.get("fast_ema", d.h1_fast)),
        h1_slow=int(h1.get("slow_ema", d.h1_slow)),
        h1_flat_atr=float(h1.get("flat_atr", d.h1_flat_atr)),
        scenarios_file=str(raw.get("scenarios_file", d.scenarios_file)),
    )
