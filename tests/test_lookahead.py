"""No lookahead: changing bars after a cut time must not change anything detected up to it."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_io.resample import resample_ohlc
from data_io.settings import load_settings
from data_io.timeconv import ServerClock
from detect.config import DetectConfig, load_detect_config
from scenarios import detect
from tests.helpers import make_random_m1

CLOCK = ServerClock("ny_plus_7")
CFG = DetectConfig()


def _snapshot(m5: pd.DataFrame, cfg: DetectConfig, cut: pd.Timestamp) -> tuple[list, list]:
    """Detections and control candidates with freeze time <= cut, as comparable tuples."""
    m5 = m5.sort_values("time_utc").reset_index(drop=True)
    det = detect(m5, cfg)
    times = m5["time_utc"]
    sigs = sorted(
        (times.iloc[s.pos], s.detector, s.direction, s.level_name, round(s.level_price, 6))
        for group in det.signals.values() for s in group if times.iloc[s.pos] <= cut
    )
    cands = sorted(times.iloc[p] for p in det.candidates if times.iloc[p] <= cut)
    return sigs, cands


def _perturb(m5: pd.DataFrame, cut: pd.Timestamp, seed: int, scale: float) -> pd.DataFrame:
    """Replace every bar after `cut` with wild random bars (big spikes both ways)."""
    rng = np.random.default_rng(seed)
    out = m5.copy()
    after = out["time_utc"] > cut
    n = int(after.sum())
    base = float(out.loc[~after, "close"].iloc[-1])
    close = base + np.cumsum(rng.normal(0, scale, n))
    opens = close + rng.normal(0, scale, n)
    out.loc[after, "open"] = opens
    out.loc[after, "close"] = close
    out.loc[after, "high"] = np.maximum(opens, close) + np.abs(rng.normal(0, 3 * scale, n))
    out.loc[after, "low"] = np.minimum(opens, close) - np.abs(rng.normal(0, 3 * scale, n))
    return out


@pytest.fixture(scope="module")
def m5() -> pd.DataFrame:
    return resample_ohlc(make_random_m1("2026-03-02 00:00", 12, seed=3), "M5", CLOCK)


def _window_cuts(m5: pd.DataFrame, cfg: DetectConfig) -> list[pd.Timestamp]:
    """Cut times spread through several practice windows (and their edges)."""
    ny = m5["time_utc"].dt.tz_convert(cfg.tz)
    clock = ny.dt.time
    inside = m5.loc[(clock >= cfg.window_start) & (clock < cfg.window_end), "time_utc"]
    picks = np.linspace(0, len(inside) - 1, 9).astype(int)
    return [inside.iloc[i] for i in picks]


def test_synthetic_data_has_detections(m5: pd.DataFrame) -> None:
    det = detect(m5, CFG)
    found = {s.detector for group in det.signals.values() for s in group}
    assert found == {"sweep", "bos", "orb", "fvg_retest"}
    assert det.candidates


@pytest.mark.parametrize("scale", [5.0, 60.0])
def test_future_bars_do_not_change_detections(m5: pd.DataFrame, scale: float) -> None:
    for k, cut in enumerate(_window_cuts(m5, CFG)):
        before = _snapshot(m5, CFG, cut)
        changed = _perturb(m5, cut, seed=k, scale=scale)
        assert _snapshot(changed, CFG, cut) == before, f"lookahead at cut {cut}"


def test_truncating_future_does_not_change_detections(m5: pd.DataFrame) -> None:
    for cut in _window_cuts(m5, CFG):
        assert _snapshot(m5[m5["time_utc"] <= cut], CFG, cut) == _snapshot(m5, CFG, cut)


def test_perturbation_changes_later_detections(m5: pd.DataFrame) -> None:
    """Guard against a vacuous test: wild future bars do change what is found later."""
    cut = _window_cuts(m5, CFG)[0]
    end = m5["time_utc"].max()
    assert _snapshot(_perturb(m5, cut, 0, 60.0), CFG, end) != _snapshot(m5, CFG, end)


def test_real_data_lookahead() -> None:
    """Same check on the stored NAS100 data, if it has been collected."""
    settings = load_settings()
    path = settings.parquet_path("M5")
    if not path.exists():
        pytest.skip("no collected M5 data")
    cfg = load_detect_config()
    m5 = pd.read_parquet(path)
    m5 = m5[m5["time_utc"] >= m5["time_utc"].max() - pd.Timedelta(days=21)].reset_index(drop=True)
    for k, cut in enumerate(_window_cuts(m5, cfg)[::2]):
        before = _snapshot(m5, cfg, cut)
        assert _snapshot(_perturb(m5, cut, k, 40.0), cfg, cut) == before, f"lookahead at cut {cut}"
