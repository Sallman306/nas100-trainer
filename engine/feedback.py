"""Feedback engine: session / all-time stats, splits and rule-based coaching (docs/spec.md "Feedback engine").

Works on trade-log rows as read from logs/trades.csv (all values are strings).
Trades = rounds decided long or short; R figures use filled trades only (an
unfilled order is a 0R non-event). A row may carry an extra "bars_held" value
(M5 bars from fill to exit, added by the session manager) for the quick-stop rule.
"""
from __future__ import annotations

from dataclasses import dataclass

TRADES = ("long", "short")
PLAN_KEYS = ("sl_beyond_swing", "rr_ok", "with_bias")
NO_TRADE = "no_trade"


@dataclass(frozen=True)
class FeedbackConfig:
    """Thresholds for the coaching rules (config.yaml "feedback")."""

    min_trades: int = 20          # no verdict on a sample smaller than this
    top_items: int = 3
    quick_stop_bars: int = 3      # "SL hit within N M5 bars"
    quick_stop_share: float = 0.5
    giveback_mfe_r: float = 2.0   # MFE >= this ...
    giveback_close_r: float = 1.0  # ... but closed below this
    giveback_share: float = 0.2
    fixed_target_r: float = 2.0   # the target the give-back rule suggests testing
    missed_share: float = 0.5
    overtrade_share: float = 0.5
    high_confidence: tuple[int, ...] = (4, 5)
    low_confidence: tuple[int, ...] = (1, 2)
    target_r: float = 3.0         # a missed opportunity is worth this much


# ---------- helpers ----------
def num(value: object) -> float | None:
    """CSV cell to float (None when empty or not a number)."""
    try:
        x = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def is_true(value: object) -> bool:
    """CSV boolean cell ("True") to bool."""
    return str(value) == "True"


def trades_of(rows: list[dict]) -> list[dict]:
    """Rows where the decision was long or short."""
    return [r for r in rows if r.get("decision") in TRADES]


def filled_of(rows: list[dict]) -> list[dict]:
    """Trades that were filled (they carry an R result)."""
    return [r for r in trades_of(rows) if is_true(r.get("filled")) and num(r.get("result_r")) is not None]


def r_of(rows: list[dict]) -> list[float]:
    """R results of the filled trades among `rows`, in log order."""
    return [num(r["result_r"]) or 0.0 for r in filled_of(rows)]


def mean(xs: list[float]) -> float | None:
    """Average, None for an empty list."""
    return sum(xs) / len(xs) if xs else None


def _round(x: float | None, d: int = 3) -> float | None:
    return None if x is None else round(x, d)


def max_losing_streak(results: list[float]) -> int:
    """Longest run of consecutive losing trades."""
    best = run = 0
    for x in results:
        run = run + 1 if x < 0 else 0
        best = max(best, run)
    return best


# ---------- stats ----------
def stats(rows: list[dict]) -> dict:
    """All numbers of the report for a list of logged rounds.

    avg_r: mean R over every trade decision (unfilled orders count 0R);
    expectancy: mean R per filled trade.
    """
    trades = trades_of(rows)
    results = r_of(rows)
    skips = [r for r in rows if r.get("decision") == "skip"]
    correct = sum(r.get("exit_reason") == "correct_skip" for r in skips)
    plan_ok = sum(all(is_true(r.get(k)) for k in PLAN_KEYS) for r in trades)
    rr = [x for x in (num(r.get("rr_planned")) for r in trades) if x is not None]
    wins = [x for x in results if x > 0]
    losses = [x for x in results if x < 0]
    return {
        "rounds": len(rows),
        "trades": len(trades),
        "filled": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _round(len(wins) / len(results)) if results else None,
        "avg_r": _round(sum(results) / len(trades)) if trades else None,
        "expectancy": _round(mean(results)),
        "avg_win": _round(mean(wins)),
        "avg_loss": _round(mean(losses)),
        "total_r": round(sum(results), 3),
        "max_losing_streak": max_losing_streak(results),
        "skips": len(skips),
        "skip_accuracy": _round(correct / len(skips)) if skips else None,
        "avg_rr_planned": _round(mean(rr), 2),
        "plan_quality": _round(plan_ok / len(trades)) if trades else None,
    }


SPLITS = {
    "detector": lambda r: r.get("detector") or "?",
    "side": lambda r: r.get("decision") if r.get("decision") in TRADES else None,
    "confidence": lambda r: str(r.get("confidence") or "") or None,
}


def splits(rows: list[dict], min_trades: int) -> dict[str, list[dict]]:
    """Stats per detector, per side (long/short) and per confidence level.

    Each group says whether it has enough filled trades for a verdict and, if so,
    whether its expectancy is positive or negative.
    """
    out: dict[str, list[dict]] = {}
    for name, key in SPLITS.items():
        groups: dict[str, list[dict]] = {}
        for r in rows:
            k = key(r)
            if k is not None:
                groups.setdefault(k, []).append(r)
        items = []
        for k in sorted(groups):
            s = stats(groups[k])
            enough = s["filled"] >= min_trades
            verdict = "not_enough_data" if not enough else ("positive" if (s["expectancy"] or 0) > 0 else "negative")
            items.append({"key": k, **s, "verdict": verdict})
        out[name] = items
    return out


def by_session(rows: list[dict]) -> list[dict]:
    """One point per session (oldest first) for the all-time charts."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["session_id"], []).append(r)
    points = []
    for sid in sorted(groups):
        s = stats(groups[sid])
        day = sid[:8]
        date = f"{day[:4]}-{day[4:6]}-{day[6:]}" if day.isdigit() else ""
        points.append({"session_id": sid, "date": date, **{k: s[k] for k in (
            "rounds", "trades", "filled", "win_rate", "expectancy", "total_r", "plan_quality", "skip_accuracy")}})
    return points


# ---------- coaching rules ----------
def _rule(key: str, fire: bool | None, r_lost: float, sample: int, need: int, **values: object) -> dict:
    """One coaching rule result. fire=None means the sample is too small for a verdict."""
    if fire is None:
        status = "not_enough_data"
    else:
        status = "work_on" if fire else "ok"
    return {"key": key, "status": status, "r_lost": round(max(r_lost, 0.0), 2) if fire else 0.0,
            "sample": sample, "need": need, "values": values}


def rule_quick_stops(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Losses mostly hit the SL within N bars -> stops too tight."""
    filled = filled_of(rows)
    losses = [r for r in filled if r.get("exit_reason") == "sl" and num(r.get("bars_held")) is not None]
    quick = [r for r in losses if (num(r.get("bars_held")) or 0) <= cfg.quick_stop_bars]
    if len(filled) < cfg.min_trades:
        return _rule("quick_stops", None, 0, len(filled), cfg.min_trades)
    share = len(quick) / len(losses) if losses else 0.0
    lost = -sum(num(r["result_r"]) or 0.0 for r in quick)
    return _rule("quick_stops", bool(losses) and share >= cfg.quick_stop_share, lost, len(filled), cfg.min_trades,
                 quick=len(quick), losses=len(losses), bars=cfg.quick_stop_bars, share=round(share, 2))


def rule_giveback(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """MFE >= 2R but closed at a loss or < 1R -> TP too far / no management plan."""
    filled = filled_of(rows)
    if len(filled) < cfg.min_trades:
        return _rule("giveback", None, 0, len(filled), cfg.min_trades)
    hits = [r for r in filled if (num(r.get("mfe_r")) or 0) >= cfg.giveback_mfe_r
            and (num(r["result_r"]) or 0) < cfg.giveback_close_r]
    share = len(hits) / len(filled)
    lost = sum(cfg.fixed_target_r - (num(r["result_r"]) or 0) for r in hits)
    return _rule("giveback", share >= cfg.giveback_share, lost, len(filled), cfg.min_trades,
                 hits=len(hits), trades=len(filled), mfe=cfg.giveback_mfe_r, close=cfg.giveback_close_r,
                 target=cfg.fixed_target_r)


def rule_weak_setup(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Expectancy positive on one detector, negative on another -> drop the weak one."""
    groups: dict[str, list[float]] = {}
    for r in filled_of(rows):
        groups.setdefault(r.get("detector") or "?", []).append(num(r["result_r"]) or 0.0)
    ready = {k: v for k, v in groups.items() if len(v) >= cfg.min_trades}
    biggest = max((len(v) for v in groups.values()), default=0)
    if len(ready) < 2:
        return _rule("weak_setup", None, 0, biggest, cfg.min_trades)
    exp = {k: sum(v) / len(v) for k, v in ready.items()}
    strong, weak = max(exp, key=exp.get), min(exp, key=exp.get)  # type: ignore[arg-type]
    fire = exp[strong] > 0 > exp[weak]
    return _rule("weak_setup", fire, -sum(ready[weak]), len(ready[weak]), cfg.min_trades,
                 strong=strong, weak=weak, strong_exp=round(exp[strong], 2), weak_exp=round(exp[weak], 2))


def rule_confidence(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """High-confidence trades no better than low ones -> confidence not calibrated."""
    def group(levels: tuple[int, ...]) -> list[float]:
        return [num(r["result_r"]) or 0.0 for r in filled_of(rows) if num(r.get("confidence")) in levels]
    high, low = group(cfg.high_confidence), group(cfg.low_confidence)
    smallest = min(len(high), len(low))
    if smallest < cfg.min_trades:
        return _rule("confidence", None, 0, smallest, cfg.min_trades)
    eh, el = sum(high) / len(high), sum(low) / len(low)
    return _rule("confidence", eh <= el, (el - eh) * len(high), smallest, cfg.min_trades,
                 high_exp=round(eh, 2), low_exp=round(el, 2), n_high=len(high), n_low=len(low))


def rule_missed(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Many missed opportunities on skips -> too passive."""
    skips = [r for r in rows if r.get("decision") == "skip"]
    if len(skips) < cfg.min_trades:
        return _rule("missed", None, 0, len(skips), cfg.min_trades)
    missed = sum(r.get("exit_reason") == "missed_opportunity" for r in skips)
    share = missed / len(skips)
    return _rule("missed", share >= cfg.missed_share, missed * cfg.target_r, len(skips), cfg.min_trades,
                 missed=missed, skips=len(skips), target=cfg.target_r, share=round(share, 2))


def rule_overtrade(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Many trades on no-trade rounds -> overtrading."""
    controls = [r for r in rows if r.get("detector") == NO_TRADE]
    if len(controls) < cfg.min_trades:
        return _rule("overtrade", None, 0, len(controls), cfg.min_trades)
    traded = trades_of(controls)
    share = len(traded) / len(controls)
    return _rule("overtrade", share >= cfg.overtrade_share, -sum(r_of(controls)), len(controls), cfg.min_trades,
                 traded=len(traded), controls=len(controls), r=round(sum(r_of(controls)), 2), share=round(share, 2))


def rule_against_bias(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Against-bias trades lose more than with-bias trades -> trade with the H1 bias only."""
    filled = filled_of(rows)
    with_ = [num(r["result_r"]) or 0.0 for r in filled if is_true(r.get("with_bias"))]
    against = [num(r["result_r"]) or 0.0 for r in filled if not is_true(r.get("with_bias"))]
    smallest = min(len(with_), len(against))
    if smallest < cfg.min_trades:
        return _rule("against_bias", None, 0, smallest, cfg.min_trades)
    ew, ea = sum(with_) / len(with_), sum(against) / len(against)
    return _rule("against_bias", ea < ew, (ew - ea) * len(against), smallest, cfg.min_trades,
                 with_exp=round(ew, 2), against_exp=round(ea, 2), n_with=len(with_), n_against=len(against))


RULES = (rule_quick_stops, rule_giveback, rule_weak_setup, rule_confidence, rule_missed, rule_overtrade,
         rule_against_bias)


def coaching(rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Evaluate every rule; the top N firing rules (by R lost) are the "work on this" list."""
    rules = [rule(rows, cfg) for rule in RULES]
    fired = sorted((r for r in rules if r["status"] == "work_on"), key=lambda r: -r["r_lost"])
    return {"work_on": fired[:cfg.top_items], "rules": rules,
            "based_on": {"rounds": len(rows), "filled": len(filled_of(rows))}, "min_trades": cfg.min_trades}


def session_report(session_rows: list[dict], all_rows: list[dict], cfg: FeedbackConfig) -> dict:
    """Session numbers and splits; coaching uses all-time rows (a session alone is below the minimum)."""
    return {"stats": stats(session_rows), "splits": splits(session_rows, cfg.min_trades),
            "coaching": coaching(all_rows, cfg)}


def progress_report(all_rows: list[dict], cfg: FeedbackConfig) -> dict:
    """All-time tab: per-session series, overall stats, splits and coaching."""
    return {"sessions": by_session(all_rows), "stats": stats(all_rows),
            "splits": splits(all_rows, cfg.min_trades), "coaching": coaching(all_rows, cfg)}
