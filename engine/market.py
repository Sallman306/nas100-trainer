"""Market data for the app: Parquet loading, chart slices at the freeze bar, hidden dates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

import pandas as pd

from data_io.settings import Settings
from detect.config import DetectConfig

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}
CHART_TFS = ("M5", "M15", "H1")
TRADING_MINUTES_PER_DAY = 23 * 60
OHLC = ["open", "high", "low", "close"]


@dataclass
class MarketData:
    """All bars the app needs, sorted by time, plus the scenario table."""

    bars: dict[str, pd.DataFrame]  # keys M1, M5, M15, H1
    scenarios: pd.DataFrame

    @classmethod
    def load(cls, settings: Settings, detect_cfg: DetectConfig) -> "MarketData":
        """Read Parquet files written by collect.py and scenarios.py."""
        bars = {tf: pd.read_parquet(settings.parquet_path(tf)).sort_values("time_utc").reset_index(drop=True)
                for tf in TF_MINUTES}
        scen = pd.read_parquet(settings.data_dir / detect_cfg.scenarios_file)
        return cls(bars, scen)

    def freeze_end(self, freeze_utc: pd.Timestamp) -> pd.Timestamp:
        """Close time of the freeze M5 bar (= start of the replay)."""
        return freeze_utc + pd.Timedelta(minutes=TF_MINUTES["M5"])

    def history(self, tf: str, freeze_utc: pd.Timestamp, days: int) -> pd.DataFrame:
        """Bars of `tf` visible at the close of the freeze M5 bar, about `days` trading days back.

        History is counted in bars (23 trading hours per day) so weekends do not shorten it.
        A higher-timeframe bar still forming at the freeze is rebuilt from the M5 bars
        up to the freeze, so nothing after the freeze leaks into the chart.
        """
        end = self.freeze_end(freeze_utc)
        df = self.bars[tf]
        span = pd.Timedelta(minutes=TF_MINUTES[tf])
        n_bars = days * TRADING_MINUTES_PER_DAY // TF_MINUTES[tf]
        done = df[df["time_utc"] + span <= end][["time_utc", *OHLC]].tail(n_bars)
        bucket = end.floor(f"{TF_MINUTES[tf]}min")
        if tf == "M5" or bucket == end:
            return done.reset_index(drop=True)
        m5 = self.bars["M5"]
        part = m5[(m5["time_utc"] >= bucket) & (m5["time_utc"] < end)]
        if part.empty:
            return done.reset_index(drop=True)
        partial = pd.DataFrame([{
            "time_utc": bucket, "open": part["open"].iloc[0], "high": part["high"].max(),
            "low": part["low"].min(), "close": part["close"].iloc[-1],
        }])
        return pd.concat([done, partial], ignore_index=True)

    def after(self, tf: str, freeze_utc: pd.Timestamp, until_utc: pd.Timestamp) -> pd.DataFrame:
        """Bars opening after the freeze bar closes, up to `until_utc` (exclusive)."""
        end = self.freeze_end(freeze_utc)
        df = self.bars[tf]
        return df[(df["time_utc"] >= end) & (df["time_utc"] < until_utc)][["time_utc", *OHLC]].reset_index(drop=True)


def timeout_utc(freeze_utc: pd.Timestamp, timeout: time, tz: str) -> pd.Timestamp:
    """Time-out (e.g. 17:00 NY) on the freeze bar's New York date, in UTC."""
    ny_day = freeze_utc.tz_convert(tz).date()
    return pd.Timestamp(datetime.combine(ny_day, timeout), tz=tz).tz_convert("UTC")


class ChartClock:
    """Maps real UTC times to chart seconds: NY wall clock shifted to a fake date.

    The chart shows the right New York time of day and weekday, but the date is moved
    by whole weeks to the week of `fake_date`, so the real day cannot be read from the
    page (or its data).
    """

    def __init__(self, freeze_utc: pd.Timestamp, tz: str, fake_date: date) -> None:
        real_day = pd.Timestamp(freeze_utc.tz_convert(tz).date())
        self.tz = tz
        days = (pd.Timestamp(fake_date) - real_day).days
        self.shift = pd.Timedelta(days=-(-days // 7) * 7)  # whole weeks: the weekday stays real

    def to_chart(self, t: pd.Timestamp) -> int:
        """Chart timestamp (seconds) for a UTC time."""
        wall = t.tz_convert(self.tz).tz_localize(None) + self.shift
        return int(wall.timestamp())

    def bars_json(self, df: pd.DataFrame) -> list[dict]:
        """Bars as Lightweight Charts candlestick data."""
        return [
            {"time": self.to_chart(t), "open": round(o, 2), "high": round(h, 2), "low": round(lo, 2), "close": round(c, 2)}
            for t, o, h, lo, c in zip(df["time_utc"], df["open"], df["high"], df["low"], df["close"])
        ]
