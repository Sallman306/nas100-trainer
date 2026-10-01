"""Thin wrapper around the MetaTrader5 package (Windows only)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from data_io.m1_store import ChunkFetcher

RAW_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread"]


class MT5Error(RuntimeError):
    """Raised when the MT5 terminal or symbol is not usable."""


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - depends on platform
        raise MT5Error("MetaTrader5 package not installed (Windows only): pip install MetaTrader5") from exc
    return mt5


def connect() -> None:
    """Attach to the running, logged-in MT5 terminal."""
    mt5 = _mt5()
    if not mt5.initialize():
        raise MT5Error(f"mt5.initialize() failed: {mt5.last_error()}. Is the MT5 terminal open and logged in?")


def shutdown() -> None:
    """Detach from the terminal."""
    _mt5().shutdown()


def resolve_symbol(name: str) -> None:
    """Make sure `name` exists and is in Market Watch; otherwise list close matches."""
    mt5 = _mt5()
    if mt5.symbol_info(name) is None:
        symbols = mt5.symbols_get() or []
        hints = [s.name for s in symbols if "100" in s.name or "NAS" in s.name.upper() or "USTEC" in s.name.upper()]
        raise MT5Error(f"symbol {name!r} not found. Candidates: {hints or 'none'}. Set 'symbol' in config.yaml.")
    if not mt5.symbol_select(name, True):
        raise MT5Error(f"could not add {name!r} to Market Watch: {mt5.last_error()}")


def make_fetcher(symbol: str, log=print) -> ChunkFetcher:
    """Return a fetcher that pulls M1 bars for [start, end) given in naive server time.

    MT5 treats the request bounds and the returned 'time' field as server wall-clock
    seconds, so bounds are passed as UTC-tagged datetimes holding server clock values.
    """
    mt5 = _mt5()

    def fetch(start: datetime, end: datetime) -> pd.DataFrame:
        rates = mt5.copy_rates_range(
            symbol,
            mt5.TIMEFRAME_M1,
            start.replace(tzinfo=timezone.utc),
            end.replace(tzinfo=timezone.utc),
        )
        if rates is None:
            log(f"  {start:%Y-%m} : no data ({mt5.last_error()})")
            return pd.DataFrame(columns=RAW_COLUMNS)
        df = pd.DataFrame(rates)
        if df.empty:
            log(f"  {start:%Y-%m} : 0 bars")
            return pd.DataFrame(columns=RAW_COLUMNS)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        log(f"  {start:%Y-%m-%d} -> {end:%Y-%m-%d} : {len(df):>7} bars")
        return df[RAW_COLUMNS]

    return fetch
