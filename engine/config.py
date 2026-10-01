"""Typed practice-app settings, read from config.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

import yaml

from data_io.settings import DEFAULT_CONFIG, _parse_time
from data_io.timeconv import ServerClock
from engine.feedback import FeedbackConfig


@dataclass(frozen=True)
class PracticeConfig:
    """Settings for rounds, grading and logging."""

    tz: str = "America/New_York"
    window: tuple[time, time] = (time(8, 0), time(10, 0))
    timeout: time = time(17, 0)
    spread: float = 1.5
    session_rounds: int = 10
    no_trade_share: float = 0.25
    min_rr: float = 3.0
    stop_atr: float = 1.0
    target_r: float = 3.0
    swing_bars: int = 2
    history_days: dict[str, int] = field(default_factory=lambda: {"M5": 2, "M15": 5, "H1": 15})
    fake_date: date = date(2000, 1, 3)
    log_file: Path = Path("logs/trades.csv")
    export_dir: Path = Path("exports")
    export_bars: int = 30
    trend: tuple[int, int, float] = (20, 50, 0.1)  # EMA fast, EMA slow, flat band in ATR
    server_clock: ServerClock = ServerClock()
    feedback: FeedbackConfig = FeedbackConfig()


def load_practice_config(path: Path | str = DEFAULT_CONFIG) -> PracticeConfig:
    """Read the practice-related sections of config.yaml."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    pr = raw.get("practice", {})
    out = raw.get("outcome", {})
    d = PracticeConfig()
    log_file = _under(path.parent, pr.get("log_file", str(d.log_file)))
    trend = raw.get("h1_trend", {})
    return PracticeConfig(
        tz=raw.get("session", {}).get("tz", d.tz),
        window=(_parse_time(raw.get("session", {}).get("start", "08:00")),
                _parse_time(raw.get("session", {}).get("end", "10:00"))),
        timeout=_parse_time(raw.get("session", {}).get("timeout", "17:00")),
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
        export_dir=_under(path.parent, pr.get("export_dir", str(d.export_dir))),
        export_bars=int(pr.get("export_bars", d.export_bars)),
        trend=(int(trend.get("fast_ema", d.trend[0])), int(trend.get("slow_ema", d.trend[1])),
               float(trend.get("flat_atr", d.trend[2]))),
        server_clock=ServerClock(raw.get("server_time", {}).get("mode", "ny_plus_7"),
                                 float(raw.get("server_time", {}).get("fixed_offset_hours", 2))),
        feedback=_feedback(raw.get("feedback", {}), float(out.get("target_r", d.target_r))),
    )


def _under(root: Path, value: str) -> Path:
    """`value` as a path; relative paths are taken from the config file's folder."""
    p = Path(value)
    return p if p.is_absolute() else root / p


def _feedback(fb: dict, target_r: float) -> FeedbackConfig:
    """Coaching thresholds from the "feedback" section (missing keys keep defaults)."""
    d = FeedbackConfig()
    return FeedbackConfig(
        min_trades=int(fb.get("min_trades", d.min_trades)),
        top_items=int(fb.get("top_items", d.top_items)),
        quick_stop_bars=int(fb.get("quick_stop_bars", d.quick_stop_bars)),
        quick_stop_share=float(fb.get("quick_stop_share", d.quick_stop_share)),
        giveback_mfe_r=float(fb.get("giveback_mfe_r", d.giveback_mfe_r)),
        giveback_close_r=float(fb.get("giveback_close_r", d.giveback_close_r)),
        giveback_share=float(fb.get("giveback_share", d.giveback_share)),
        fixed_target_r=float(fb.get("fixed_target_r", d.fixed_target_r)),
        missed_share=float(fb.get("missed_share", d.missed_share)),
        overtrade_share=float(fb.get("overtrade_share", d.overtrade_share)),
        high_confidence=tuple(int(x) for x in fb.get("high_confidence", d.high_confidence)),
        low_confidence=tuple(int(x) for x in fb.get("low_confidence", d.low_confidence)),
        target_r=target_r,
    )
