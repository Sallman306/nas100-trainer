"""logs/trades.csv: one row per round, columns fixed by the spec."""
from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = [
    "session_id", "round", "scenario_id", "detector", "freeze_time_ny", "tf_used", "decision",
    "entry", "sl", "tp", "rr_planned", "setup_tag", "bias_tag", "confidence", "note", "filled",
    "result_r", "exit_reason", "mfe_r", "mae_r", "best_possible_r", "sl_beyond_swing", "rr_ok",
    "with_bias", "seconds_to_decide",
]


def _fmt(value: object) -> object:
    """Round floats for a readable CSV; None becomes an empty cell."""
    if value is None:
        return ""
    if isinstance(value, float):
        return "" if value != value else round(value, 3)
    return value


def append_row(path: Path, row: dict) -> None:
    """Append one round; write the header first if the file is new or empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerow({k: _fmt(row.get(k)) for k in COLUMNS})


def read_rows(path: Path, session_id: str | None = None) -> list[dict]:
    """All logged rows (as strings), optionally only one session's."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if session_id is None or r["session_id"] == session_id]


def played_ids(path: Path) -> set[str]:
    """Scenario ids already logged (used to prefer unseen scenarios)."""
    return {r["scenario_id"] for r in read_rows(path)}
