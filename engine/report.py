"""Basic session statistics from trade-log rows (Phase 4 adds the full feedback engine)."""
from __future__ import annotations

TRADES = ("long", "short")


def _num(value: str) -> float | None:
    """CSV cell to float (None when empty)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def session_stats(rows: list[dict]) -> dict:
    """Win rate, R totals, skip accuracy and plan quality for a list of logged rounds."""
    trades = [r for r in rows if r["decision"] in TRADES]
    filled = [r for r in trades if r["filled"] == "True"]
    results = [_num(r["result_r"]) or 0.0 for r in filled]
    skips = [r for r in rows if r["decision"] == "skip"]
    correct = sum(r["exit_reason"] == "correct_skip" for r in skips)
    plan_ok = sum(all(r[k] == "True" for k in ("sl_beyond_swing", "rr_ok", "with_bias")) for r in trades)
    rr = [_num(r["rr_planned"]) for r in trades if _num(r["rr_planned"]) is not None]
    return {
        "rounds": len(rows),
        "trades": len(trades),
        "filled": len(filled),
        "wins": sum(x > 0 for x in results),
        "win_rate": sum(x > 0 for x in results) / len(results) if results else None,
        "total_r": round(sum(results), 3),
        "avg_r": round(sum(results) / len(results), 3) if results else None,
        "skips": len(skips),
        "skip_accuracy": correct / len(skips) if skips else None,
        "avg_rr_planned": round(sum(rr) / len(rr), 2) if rr else None,
        "plan_quality": plan_ok / len(trades) if trades else None,
    }
