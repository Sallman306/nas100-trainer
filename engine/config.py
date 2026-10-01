"""Typed practice-app settings, read from config.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

import yaml

from data_io.settings import DEFAULT_CONFIG, _parse_time


@dataclass(frozen=True)
class PracticeConfig:
    """Settings for rounds, grading and logging."""

    tz: str = "America/New_York"
    timeout: time = time(12, 0)
    spread: float = 1.5
    session_rounds: int = 10
    no_trade_share: float = 0.25
    min_rr: float = 2.0
    stop_atr: float = 1.0
    target_r: float = 2.0
    swing_bars: int = 2
    history_days: dict[str, int] = field(default_factory=lambda: {"M5": 2, "M15": 5, "H1": 15})
    fake_date: date = date(2000, 1, 3)
    log_file: Path = Path("logs/trades.csv")


def load_practice_config(path: Path | str = DEFAULT_CONFIG) -> PracticeConfig:
    """Read the practice-related sections of config.yaml."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    pr = raw.get("practice", {})
    out = raw.get("outcome", {})
    d = PracticeConfig()
    log_file = Path(pr.get("log_file", str(d.log_file)))
    if not log_file.is_absolute():
        log_file = path.parent / log_file
    return PracticeConfig(
        tz=raw.get("session", {}).get("tz", d.tz),
        timeout=_parse_time(raw.get("session", {}).get("timeout", "12:00")),
        spread=float(raw.get("spread_points", d.spread)),
        session_rounds=int(pr.get("session_rounds", d.session_rounds)),
        no_trade_share=float(pr.get("no_trade_share", d.no_trade_share)),
        min_rr=float(pr.get("min_rr", d.min_rr)),
        stop_atr=float(out.get("stop_atr", d.stop_atr)),
        target_r=float(out.get("target_r", d.target_r)),
        swing_bars=int(raw.get("detectors", {}).get("swing_bars", d.swing_bars)),
        history_days={k: int(v) for k, v in pr.get("history_days", d.history_days).items()},
        fake_date=date.fromisoformat(str(pr.get("fake_date", d.fake_date))),
        log_file=log_file,
    )
