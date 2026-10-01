"""Load config.yaml into a typed Settings object."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path

import yaml

from data_io.timeconv import ServerClock

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def _parse_time(value: str) -> time:
    """Parse "HH:MM" into a time object."""
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))


@dataclass(frozen=True)
class Settings:
    """All settings needed by the data layer."""

    symbol: str
    file_prefix: str
    history_months: int
    clock: ServerClock
    session_tz: str
    session_start: time
    session_end: time
    session_timeout: time
    gap_alert_minutes: int
    spread_points: float
    data_dir: Path
    timeframes: tuple[str, ...]

    def parquet_path(self, timeframe: str) -> Path:
        """Path of the Parquet file for a timeframe, e.g. data/nas100_m5.parquet."""
        return self.data_dir / f"{self.file_prefix}_{timeframe.lower()}.parquet"


def load_settings(path: Path | str = DEFAULT_CONFIG) -> Settings:
    """Read config.yaml; relative data_dir is resolved next to the config file."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    st = raw.get("server_time", {})
    session = raw["session"]
    data_dir = Path(raw.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = path.parent / data_dir
    return Settings(
        symbol=raw["symbol"],
        file_prefix=raw.get("file_prefix", raw["symbol"].split(".")[0].lower()),
        history_months=int(raw.get("history_months", 12)),
        clock=ServerClock(st.get("mode", "ny_plus_7"), float(st.get("fixed_offset_hours", 2))),
        session_tz=session.get("tz", "America/New_York"),
        session_start=_parse_time(session["start"]),
        session_end=_parse_time(session["end"]),
        session_timeout=_parse_time(session["timeout"]),
        gap_alert_minutes=int(raw.get("gap_alert_minutes", 5)),
        spread_points=float(raw.get("spread_points", 1.5)),
        data_dir=data_dir,
        timeframes=tuple(raw.get("timeframes", ["M5", "M15", "H1", "H4"])),
    )
