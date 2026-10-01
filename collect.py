"""Pull M1 bars from MT5 into Parquet, resample, validate.

Usage:
    python collect.py                     # first run: full history; later: append new bars
    python collect.py --validate-only     # re-run resample + checks on stored data, no MT5
    python collect.py --check 2026-09-15  # print the 09:30 NY candle to compare with MT5
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from data_io import mt5_source
from data_io.m1_store import read_parquet, update_m1, write_parquet
from data_io.resample import resample_ohlc
from data_io.settings import Settings, load_settings
from data_io.validate import count_duplicates, find_gaps, rows_per_month


def collect(settings: Settings) -> pd.DataFrame:
    """Download (or append) M1 bars and save them."""
    path = settings.parquet_path("M1")
    existing = read_parquet(path)
    mt5_source.connect()
    try:
        mt5_source.resolve_symbol(settings.symbol)
        mode = "append" if existing is not None else f"first run, {settings.history_months} months"
        print(f"Pulling {settings.symbol} M1 ({mode})")
        fetch = mt5_source.make_fetcher(settings.symbol)
        m1, added = update_m1(existing, fetch, settings.clock, settings.history_months, pd.Timestamp.now(tz="UTC"))
    finally:
        mt5_source.shutdown()
    if m1.empty:
        sys.exit("No M1 data received. Check the symbol, and set Tools > Options > Charts > Max bars to Unlimited.")
    write_parquet(m1, path)
    print(f"Saved {path} : {len(m1)} rows ({added:+d} new)")
    return m1


def resample_all(settings: Settings, m1: pd.DataFrame) -> None:
    """Write every configured higher timeframe from M1."""
    for tf in settings.timeframes:
        out = resample_ohlc(m1, tf, settings.clock)
        write_parquet(out, settings.parquet_path(tf))
        print(f"Saved {settings.parquet_path(tf)} : {len(out)} rows")


def report(settings: Settings, m1: pd.DataFrame) -> None:
    """Print duplicates, session gaps and rows per month."""
    tz = settings.session_tz
    first = m1["time_utc"].min().tz_convert(tz)
    last = m1["time_utc"].max().tz_convert(tz)
    print(f"\nRange (NY): {first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M}")
    print(f"Duplicate timestamps: {count_duplicates(m1['time_utc'])}")
    gaps = find_gaps(m1["time_utc"], settings.gap_alert_minutes, tz, settings.session_start, settings.session_timeout)
    window = f"{settings.session_start:%H:%M}-{settings.session_timeout:%H:%M}"
    print(f"Gaps > {settings.gap_alert_minutes} min inside {window} NY: {len(gaps)}")
    for g in gaps.itertuples():
        print(f"  {g.gap_start:%a %Y-%m-%d %H:%M} -> {g.gap_end:%a %Y-%m-%d %H:%M}  ({g.minutes} min)")
    print("\nRows per month (NY):")
    print(rows_per_month(m1["time_utc"], tz).to_string())


def check_candle(settings: Settings, day: str, at: str = "09:30") -> None:
    """Print the M5 and M1 bar opening at `at` NY on `day`, with server time for MT5."""
    target = pd.Timestamp(f"{day} {at}").tz_localize(settings.session_tz)
    server = settings.clock.from_utc(pd.DatetimeIndex([target.tz_convert("UTC")]))[0]
    print(f"Candle {target:%Y-%m-%d %H:%M} NY = {target.tz_convert('UTC'):%H:%M} UTC = {server:%H:%M} server time")
    print(f"In MT5, open {settings.symbol} and find the bar at {server:%Y.%m.%d %H:%M}.\n")
    for tf in ("M5", "M1"):
        df = read_parquet(settings.parquet_path(tf))
        if df is None:
            print(f"{tf}: no file, run collect.py first")
            continue
        row = df[df["time_utc"] == target.tz_convert("UTC")]
        if row.empty:
            print(f"{tf}: no bar at that time (weekend/holiday or not collected)")
            continue
        r = row.iloc[0]
        print(f"{tf}: O {r.open}  H {r.high}  L {r.low}  C {r.close}  ticks {r.tick_volume}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--validate-only", action="store_true", help="skip MT5, resample + validate stored M1")
    parser.add_argument("--check", metavar="YYYY-MM-DD", help="print the 09:30 NY candle for that date")
    parser.add_argument("--at", default="09:30", help="NY time used by --check (default 09:30)")
    args = parser.parse_args()
    settings = load_settings(args.config) if args.config else load_settings()

    if args.check:
        check_candle(settings, args.check, args.at)
        return
    if args.validate_only:
        m1 = read_parquet(settings.parquet_path("M1"))
        if m1 is None:
            sys.exit("No M1 file yet. Run: python collect.py")
    else:
        try:
            m1 = collect(settings)
        except mt5_source.MT5Error as exc:
            sys.exit(f"MT5 error: {exc}")
    resample_all(settings, m1)
    report(settings, m1)


if __name__ == "__main__":
    main()
