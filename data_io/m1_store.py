"""Build and incrementally update the M1 dataset from a chunk fetcher."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pandas as pd

from data_io.timeconv import ServerClock

M1_COLUMNS = ["time_utc", "open", "high", "low", "close", "tick_volume", "spread"]
APPEND_OVERLAP = pd.Timedelta(hours=1)
BACKFILL_TOLERANCE = pd.Timedelta(days=4)  # ignore a missing weekend/holiday at the start

# (start, end) in naive server time -> DataFrame with a naive server-time "time" column + OHLC.
ChunkFetcher = Callable[[datetime, datetime], pd.DataFrame]


def month_chunks(start: pd.Timestamp, end: pd.Timestamp) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split [start, end) into pieces that never cross a calendar month boundary."""
    cur = start
    while cur < end:
        nxt = min((cur + pd.offsets.MonthBegin(1)).normalize(), end)
        yield cur, nxt
        cur = nxt


def fetch_range(fetch: ChunkFetcher, start: pd.Timestamp, end: pd.Timestamp, clock: ServerClock) -> pd.DataFrame:
    """Fetch [start, end) server time month by month and return M1 rows with time_utc."""
    parts = []
    for a, b in month_chunks(start, end):
        chunk = fetch(a.to_pydatetime(), b.to_pydatetime())
        if chunk is not None and not chunk.empty:
            parts.append(chunk)
    if not parts:
        return pd.DataFrame(columns=M1_COLUMNS)
    raw = pd.concat(parts, ignore_index=True)
    raw = raw[(raw["time"] >= start) & (raw["time"] < end)]
    out = raw.drop(columns="time")
    out.insert(0, "time_utc", clock.to_utc(pd.DatetimeIndex(raw["time"])))
    return out[M1_COLUMNS].reset_index(drop=True)


def merge_bars(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Combine old and new bars; on duplicate timestamps the newer row wins."""
    if existing is None or existing.empty:
        merged = new
    elif new.empty:
        merged = existing
    else:
        merged = pd.concat([existing, new], ignore_index=True)
    merged = merged.drop_duplicates(subset="time_utc", keep="last")
    return merged.sort_values("time_utc").reset_index(drop=True)


def update_m1(
    existing: pd.DataFrame | None,
    fetch: ChunkFetcher,
    clock: ServerClock,
    history_months: int,
    now_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    """Return (updated M1 frame, number of new rows).

    First run pulls `history_months` back from now. Later runs re-fetch from one hour
    before the last stored bar, and also backfill older history if the stored data
    starts later than `history_months` ago (e.g. the terminal's bar limit was raised).
    """
    now_server = clock.from_utc(pd.DatetimeIndex([now_utc]))[0]
    end = (now_server + pd.Timedelta(days=1)).normalize()
    wanted_start = (now_server - pd.DateOffset(months=history_months)).normalize()
    if existing is None or existing.empty:
        new = fetch_range(fetch, wanted_start, end, clock)
    else:
        first_server, last_server = clock.from_utc(
            pd.DatetimeIndex([existing["time_utc"].min(), existing["time_utc"].max()])
        )
        parts = [fetch_range(fetch, last_server - APPEND_OVERLAP, end, clock)]
        if first_server - wanted_start > BACKFILL_TOLERANCE:
            parts.insert(0, fetch_range(fetch, wanted_start, first_server, clock))
        new = pd.concat([p for p in parts if not p.empty] or [parts[-1]], ignore_index=True)
    before = 0 if existing is None else len(existing)
    merged = merge_bars(existing, new)
    return merged, len(merged) - before


def read_parquet(path: Path) -> pd.DataFrame | None:
    """Read a Parquet file, or None if it does not exist."""
    return pd.read_parquet(path) if path.exists() else None


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a frame to Parquet, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
