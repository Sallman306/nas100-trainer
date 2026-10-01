"""Causal indicators: every value at bar t uses only bars 0..t."""
from __future__ import annotations

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder ATR (EMA of true range, alpha = 1/period). Causal."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def swing_points(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Fractal swings: bar k is a swing high if its high is the max of bars k-n..k+n.

    A swing is only *known* at bar k+n (its confirmation bar). Returns columns
    pivot_pos, confirm_pos, kind ("high"/"low"), price.
    """
    win = 2 * n + 1
    rows = []
    for kind, col, roll in (("high", "high", "max"), ("low", "low", "min")):
        series = df[col].reset_index(drop=True)
        extreme = getattr(series.rolling(win), roll)()
        is_pivot = series.shift(n) == extreme  # pivot at t-n, confirmed at t
        confirm = np.flatnonzero(is_pivot.to_numpy())
        for t in confirm:
            rows.append((t - n, t, kind, float(series.iloc[t - n])))
    out = pd.DataFrame(rows, columns=["pivot_pos", "confirm_pos", "kind", "price"])
    return out.sort_values(["confirm_pos", "kind"]).reset_index(drop=True)


def last_swing_levels(df: pd.DataFrame, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Last confirmed swing high / low known at the close of each bar (NaN if none)."""
    size = len(df)
    sh = np.full(size, np.nan)
    sl = np.full(size, np.nan)
    pts = swing_points(df, n)
    for kind, arr in (("high", sh), ("low", sl)):
        sub = pts[pts["kind"] == kind]
        arr[sub["confirm_pos"].to_numpy()] = sub["price"].to_numpy()
    return pd.Series(sh).ffill().to_numpy(), pd.Series(sl).ffill().to_numpy()


def h1_trend_at(h1: pd.DataFrame, at_utc: pd.Timestamp, fast: int, slow: int, flat_atr: float,
                span: pd.Timedelta = pd.Timedelta(hours=1)) -> str:
    """Trend ("up"/"down"/"flat") from bars fully closed by `at_utc` (H1 by default; `span` = bar length).

    up: EMA(fast) > EMA(slow) by more than flat_atr * ATR(14); down: the reverse.
    """
    closed = h1[h1["time_utc"] + span <= at_utc]
    if len(closed) < slow:
        return "flat"
    close = closed["close"]
    diff = close.ewm(span=fast, adjust=False).mean().iloc[-1] - close.ewm(span=slow, adjust=False).mean().iloc[-1]
    band = flat_atr * float(atr(closed, 14).iloc[-1])
    if diff > band:
        return "up"
    if diff < -band:
        return "down"
    return "flat"
