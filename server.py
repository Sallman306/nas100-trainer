"""FastAPI server: practice rounds API + the static web page.

Run: uvicorn server:app --reload, then open http://localhost:8000
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from data_io.settings import load_settings
from detect.config import load_detect_config
from engine.config import load_practice_config
from engine.market import MarketData
from engine.session import Practice, RoundError

WEB_DIR = Path(__file__).resolve().parent / "web"


def default_practice() -> Practice:
    """Load config and Parquet data from disk."""
    settings = load_settings()
    return Practice(MarketData.load(settings, load_detect_config()), load_practice_config())


def create_app(factory: Callable[[], Practice] = default_practice) -> FastAPI:
    """Build the app; data is loaded on the first API call (tests pass their own factory)."""
    app = FastAPI(title="NAS100 Trade Trainer")
    state: dict[str, Practice] = {}

    def practice() -> Practice:
        if "p" not in state:
            state["p"] = factory()
        return state["p"]

    def call(fn: Callable[[], dict]) -> dict:
        try:
            return fn()
        except RoundError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.get("/api/round/next")
    def next_round(session_id: str | None = None, drill: str | None = None, rounds: int | None = None) -> dict:
        """Next frozen round of a session; starts a new session when session_id is missing/unknown."""
        return call(lambda: practice().next_round(session_id, drill, rounds))

    @app.post("/api/round/{round_id}/submit")
    def submit(round_id: str, form: dict = Body(...)) -> dict:
        """Commit a decision; returns the graded result and the replay bars."""
        return call(lambda: practice().submit(round_id, form))

    @app.get("/api/session/{session_id}/report")
    def report(session_id: str) -> dict:
        """Logged rounds and basic stats of a session."""
        return call(lambda: practice().report(session_id))

    @app.get("/api/meta")
    def meta() -> dict:
        """Detector names (for the drill filter) and the default session length."""
        p = practice()
        return {"detectors": sorted(p.market.scenarios["detector"].unique().tolist()),
                "session_rounds": p.cfg.session_rounds}

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
