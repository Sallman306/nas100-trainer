"""API end-to-end on synthetic data: rounds, commits, trade log, report."""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from data_io.resample import resample_ohlc
from data_io.timeconv import ServerClock
from detect.config import DetectConfig
from engine.config import PracticeConfig
from engine.market import MarketData
from engine.session import Practice
from engine.tradelog import COLUMNS
from scenarios import build_scenarios
from server import create_app
from tests.helpers import make_random_m1

CLOCK = ServerClock("ny_plus_7")
HIDDEN = {"detector", "direction_hint", "best_possible_r", "long_mfe_r", "scenario_id", "freeze_time_utc"}


@pytest.fixture(scope="module")
def market() -> MarketData:
    m1 = make_random_m1("2026-03-02 00:00", 12, seed=11)
    bars = {"M1": m1, **{tf: resample_ohlc(m1, tf, CLOCK) for tf in ("M5", "M15", "H1")}}
    return MarketData(bars, build_scenarios(m1, bars["M5"], bars["H1"], DetectConfig()))


@pytest.fixture()
def setup(market: MarketData, tmp_path: Path) -> tuple[TestClient, Practice]:
    cfg = replace(PracticeConfig(), session_rounds=4, log_file=tmp_path / "logs" / "trades.csv")
    practice = Practice(market, cfg, seed=1)
    return TestClient(create_app(lambda: practice)), practice


def test_round_payload_hides_answers_and_date(setup) -> None:
    client, practice = setup
    r = client.get("/api/round/next").json()
    assert not HIDDEN & set(r)
    assert r["round_no"] == 1 and r["total_rounds"] == 4
    freeze = pd.Timestamp(r["freeze_time"], unit="s")
    assert freeze.year == 2000  # fake date
    m5 = r["charts"]["M5"]
    assert m5[-1]["time"] == r["freeze_time"] and m5[-1]["close"] == r["price"]
    for tf in ("M15", "H1"):
        assert r["charts"][tf][-1]["time"] <= r["freeze_time"]
        assert max(b["high"] for b in r["charts"][tf][-3:]) <= max(b["high"] for b in m5) + 1e-9
    assert {lv["name"] for lv in r["levels"]} <= {"Asian H", "Asian L", "London H", "London L", "PDH", "PDL"}


def test_partial_higher_tf_bar_has_no_future(setup, market: MarketData) -> None:
    client, practice = setup
    r = client.get("/api/round/next").json()
    rnd = practice.rounds[r["round_id"]]
    freeze = rnd.scenario["freeze_time_utc"]
    end = freeze + pd.Timedelta(minutes=5)
    m5 = market.bars["M5"]
    for tf, mins in (("M15", 15), ("H1", 60)):
        last = r["charts"][tf][-1]
        bucket = end.floor(f"{mins}min")
        if bucket == end:
            continue
        seen = m5[(m5["time_utc"] >= bucket) & (m5["time_utc"] < end)]
        assert last["high"] == round(seen["high"].max(), 2) and last["close"] == round(seen["close"].iloc[-1], 2)


def test_full_session_logs_every_round(setup) -> None:
    client, practice = setup
    sid = None
    decisions = ["long", "short", "skip", "long"]
    for k, decision in enumerate(decisions):
        r = client.get("/api/round/next", params={"session_id": sid} if sid else {}).json()
        sid = r["session_id"]
        p, a = r["price"], r["atr"]
        sign = 1 if decision == "long" else -1
        form = {"decision": decision, "order_type": "market", "sl": p - sign * a, "tp": p + sign * 3 * a,
                "setup_tag": "sweep", "bias_tag": "with", "confidence": 4, "note": "test", "tf_used": ["M5", "H1"]}
        res = client.post(f"/api/round/{r['round_id']}/submit", json=form)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["detector"] and body["replay"] and body["round_no"] == k + 1
        if decision == "skip":
            assert body["exit_reason"] in ("correct_skip", "missed_opportunity")
        else:
            assert body["exit_reason"] in ("tp", "sl", "timeout")
            assert body["rr_ok"] is True
            assert pd.Timestamp(body["replay"][-1]["time"], unit="s").strftime("%H:%M") < "17:00"
        assert body["session_done"] == (k == len(decisions) - 1)
    assert client.get("/api/round/next", params={"session_id": sid}).json()["done"] is True

    with practice.cfg.log_file.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == COLUMNS
    assert [r["decision"] for r in rows] == decisions and [r["round"] for r in rows] == ["1", "2", "3", "4"]
    assert rows[0]["tf_used"] == "M5+H1" and rows[0]["filled"] == "True" and rows[2]["entry"] == ""

    rep = client.get(f"/api/session/{sid}/report").json()
    assert rep["stats"]["rounds"] == 4 and rep["stats"]["trades"] == 3 and rep["stats"]["skips"] == 1


def test_double_submit_and_bad_input(setup) -> None:
    client, _ = setup
    r = client.get("/api/round/next").json()
    url = f"/api/round/{r['round_id']}/submit"
    bad = {"decision": "long", "order_type": "market", "sl": r["price"] + 5, "tp": r["price"] + 50}
    assert client.post(url, json=bad).status_code == 422
    assert client.post(url, json={"decision": "maybe"}).status_code == 422
    assert client.post(url, json={"decision": "skip"}).status_code == 200
    assert client.post(url, json={"decision": "skip"}).status_code == 409
    assert client.post("/api/round/nope/submit", json={"decision": "skip"}).status_code == 404
    assert client.get("/api/session/nope/report").status_code == 404


def test_reload_reserves_pending_round_and_drill(setup) -> None:
    client, _ = setup
    first = client.get("/api/round/next", params={"drill": "sweep"}).json()
    again = client.get("/api/round/next", params={"session_id": first["session_id"]}).json()
    assert again["round_id"] == first["round_id"]
    assert client.get("/api/round/next", params={"drill": "nothing"}).status_code == 404


def test_pending_order_not_filled(setup) -> None:
    client, _ = setup
    r = client.get("/api/round/next").json()
    p = r["price"]
    form = {"decision": "long", "order_type": "pending", "entry": p - 5000, "sl": p - 5100, "tp": p - 4000}
    body = client.post(f"/api/round/{r['round_id']}/submit", json=form).json()
    assert body["filled"] is False and body["exit_reason"] == "not_filled" and body["result_r"] == 0.0


def test_static_page_served(setup) -> None:
    client, _ = setup
    assert "lightweight-charts" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    labels = client.get("/labels.json").json()
    assert set(labels["en"]) == set(labels["fr"])


def test_chart_clock_keeps_ny_time_and_weekday() -> None:
    from datetime import date

    from engine.market import ChartClock
    t = pd.Timestamp("2026-08-13 13:45", tz="UTC")  # Thu 09:45 NY (EDT)
    chart = pd.Timestamp(ChartClock(t, "America/New_York", date(2000, 1, 3)).to_chart(t), unit="s")
    assert chart.strftime("%a %H:%M") == "Thu 09:45" and chart.year == 2000
