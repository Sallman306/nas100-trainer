"""Rule-based explanation of a round: the context at the freeze, what triggered the
setup, what price did afterwards (timeline) and why the main move happened.

Everything is derived from bars and levels; no AI, no guessing beyond simple rules.
Before-freeze facts use bars up to the freeze; after-freeze facts are only shown
once the round is committed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LEVEL_LABELS = {
    "asian_high": "Asian high", "asian_low": "Asian low",
    "london_high": "London high", "london_low": "London low",
    "pdh": "previous-day high (PDH)", "pdl": "previous-day low (PDL)",
    "or_high": "opening-range high", "or_low": "opening-range low",
}
SHORT_LEVELS = {
    "asian_high": "Asian H", "asian_low": "Asian L", "london_high": "London H", "london_low": "London L",
    "pdh": "PDH", "pdl": "PDL", "or_high": "OR H", "or_low": "OR L",
}
SETUP_NAMES = {
    "sweep": "liquidity sweep", "bos": "displacement / BOS", "orb": "opening-range break",
    "fvg_retest": "FVG retest", "no_trade": "no-trade",
}
SPECIAL_TIMES = {
    "08:30": "08:30 ET – a typical US data-release time (CPI, jobs, claims)",
    "09:30": "09:30 ET – the US cash open",
    "09:35": "09:35 ET – the first minutes after the cash open",
    "10:00": "10:00 ET – a typical US data-release time (ISM, sentiment)",
}


@dataclass
class Event:
    """One timeline item after the freeze."""

    time_utc: pd.Timestamp
    text: str
    kind: str  # level | extreme | candle | move
    price: float = float("nan")
    label: str = ""  # short chart-marker text


@dataclass
class Story:
    """Explanation pieces shown on the result card."""

    trigger: str
    context: list[str]
    events: list[Event]
    why: list[str]
    main_dir: str            # up | down
    main_atr: float          # size of the main move in ATR
    levels_hit: dict[str, str] = field(default_factory=dict)  # level key -> "broke" | "rejected"


def ny_hhmm(t: pd.Timestamp, tz: str) -> str:
    """Clock time in New York, e.g. 09:35."""
    return t.tz_convert(tz).strftime("%H:%M")


def scenario_levels(s: pd.Series) -> dict[str, float]:
    """Key levels known at the freeze (opening range only once complete)."""
    return {k: float(s[k]) for k in LEVEL_LABELS if k in s and pd.notna(s[k])}


def trigger_text(s: pd.Series) -> str:
    """What the detector saw at the freeze bar."""
    det, d = s["detector"], s["direction_hint"]
    lvl = LEVEL_LABELS.get(str(s["level_name"]), str(s["level_name"]))
    price = s["level_price"]
    if det == "sweep":
        side = "above" if d == "short" else "below"
        back = "below" if d == "short" else "above"
        pool = "buy-side" if d == "short" else "sell-side"
        return (f"Liquidity sweep: price wicked {side} the {lvl} ({price:.2f}) and closed back {back} it. "
                f"The stops resting {side} that level ({pool} liquidity) were taken, then price rejected – "
                f"a reversal signal pointing {d.upper()}.")
    if det == "bos":
        side = "high" if d == "long" else "low"
        return (f"Displacement / break of structure: one candle with a body over 1.5× ATR closed beyond the last "
                f"swing {side} ({price:.2f}). Strong one-sided order flow – a continuation signal pointing {d.upper()}.")
    if det == "orb":
        size = s["or_high"] - s["or_low"]
        side = "above the high" if d == "long" else "below the low"
        return (f"Opening-range break: price closed {side} of the 09:30–09:45 range "
                f"({s['or_low']:.2f}–{s['or_high']:.2f}, {size:.1f} pts) – a momentum signal pointing {d.upper()}.")
    if det == "fvg_retest":
        kind = "bullish" if d == "long" else "bearish"
        return (f"Fair-value-gap retest: price came back for the first time into a {kind} gap "
                f"({s['fvg_bottom']:.2f}–{s['fvg_top']:.2f}) left by a fast move earlier in the window. "
                f"Such gaps often act as support/resistance – a signal pointing {d.upper()}.")
    return ("No setup: none of the detectors (sweep, displacement, opening-range break, FVG retest) fired here. "
            "This is a control round – the disciplined answer is usually to wait.")


def context_points(s: pd.Series, before: pd.DataFrame, tz: str) -> list[str]:
    """Facts visible at the freeze: trend, volatility, session move, position vs levels."""
    close, atr = float(s["close"]), float(s["atr"])
    out = [f"H1 trend was {str(s['h1_trend']).upper()} (EMA 20 vs EMA 50 on H1). "
           f"M5 ATR(14) = {atr:.1f} pts, so 1 ATR ≈ one normal 5-minute range."]
    ny = before["time_utc"].dt.tz_convert(tz)
    today = before[ny.dt.date == s["freeze_time_utc"].tz_convert(tz).date()]
    from_8 = today[today["time_utc"].dt.tz_convert(tz).dt.strftime("%H:%M") >= "08:00"]
    if len(from_8):
        move = close - float(from_8["open"].iloc[0])
        out.append(f"Since 08:00 ET price had moved {move:+.1f} pts ({move / atr:+.1f} ATR) into the freeze.")
    levels = scenario_levels(s)
    above = sorted(((p - close, k) for k, p in levels.items() if p > close))
    below = sorted(((close - p, k) for k, p in levels.items() if p < close))
    if above:
        d, k = above[0]
        out.append(f"Nearest level above: {LEVEL_LABELS[k]} at {levels[k]:.2f} ({d:.1f} pts / {d / atr:.1f} ATR away) – "
                   f"buy stops cluster there.")
    else:
        out.append("Price was above every key level – no obvious overhead liquidity (open air).")
    if below:
        d, k = below[0]
        out.append(f"Nearest level below: {LEVEL_LABELS[k]} at {levels[k]:.2f} ({d:.1f} pts / {d / atr:.1f} ATR away) – "
                   f"sell stops cluster there.")
    else:
        out.append("Price was below every key level – no obvious liquidity underneath.")
    return out


def _level_events(s: pd.Series, after: pd.DataFrame, tz: str) -> tuple[list[Event], dict[str, str]]:
    """First touch of each level after the freeze, and whether it broke or held."""
    close = float(s["close"])
    h, l, c = (after[k].to_numpy(float) for k in ("high", "low", "close"))
    events, hit = [], {}
    for key, price in scenario_levels(s).items():
        up = price > close
        touch = np.flatnonzero(h >= price) if up else np.flatnonzero(l <= price)
        if not touch.size:
            continue
        i = int(touch[0])
        closes = c[i:i + 4]
        broke = bool((closes > price).any()) if up else bool((closes < price).any())
        t = after["time_utc"].iloc[i]
        verb = ("broke above" if up else "broke below") if broke else "tested and held"
        short = SHORT_LEVELS[key] + (" broken" if broke else " held")
        events.append(Event(t, f"{ny_hhmm(t, tz)} – price {verb} the {LEVEL_LABELS[key]} ({price:.2f}).", "level", price, short))
        hit[key] = "broke" if broke else "rejected"
    return events, hit


def after_events(s: pd.Series, after: pd.DataFrame, tz: str) -> tuple[list[Event], dict[str, str]]:
    """Timeline after the freeze: first 1-ATR move, level touches, biggest candle, extremes, close."""
    if after.empty:
        return [], {}
    close, atr = float(s["close"]), float(s["atr"])
    h, l, o, c = (after[k].to_numpy(float) for k in ("high", "low", "open", "close"))
    t = after["time_utc"]
    events, hit = _level_events(s, after, tz)
    up_i = np.flatnonzero(h >= close + atr)
    dn_i = np.flatnonzero(l <= close - atr)
    first_up = int(up_i[0]) if up_i.size else len(h)
    first_dn = int(dn_i[0]) if dn_i.size else len(h)
    if min(first_up, first_dn) < len(h):
        i = min(first_up, first_dn)
        which = "both ways in the same candle" if first_up == first_dn else ("UP" if first_up < first_dn else "DOWN")
        events.append(Event(t.iloc[i], f"{ny_hhmm(t.iloc[i], tz)} – first 1-ATR move from the freeze price went {which}.",
                            "move", label="1 ATR " + ("up" if first_up < first_dn else "down" if first_dn < first_up else "both")))
    body = np.abs(c - o)
    b = int(body.argmax())
    tag = SPECIAL_TIMES.get(ny_hhmm(t.iloc[b], tz))
    kind = "bullish" if c[b] > o[b] else "bearish"
    events.append(Event(t.iloc[b], f"{ny_hhmm(t.iloc[b], tz)} – biggest candle of the replay: {kind}, body "
                                   f"{body[b]:.1f} pts ({body[b] / atr:.1f} ATR)" + (f", at {tag}." if tag else "."), "candle",
                        label=f"big {body[b] / atr:.1f} ATR"))
    hi, lo = int(h.argmax()), int(l.argmin())
    events.append(Event(t.iloc[hi], f"{ny_hhmm(t.iloc[hi], tz)} – highest price after the freeze: {h[hi]:.2f} "
                                    f"({(h[hi] - close) / atr:+.1f} ATR).", "extreme", float(h[hi]), "high"))
    events.append(Event(t.iloc[lo], f"{ny_hhmm(t.iloc[lo], tz)} – lowest price after the freeze: {l[lo]:.2f} "
                                    f"({(l[lo] - close) / atr:+.1f} ATR).", "extreme", float(l[lo]), "low"))
    net = c[-1] - close
    events.append(Event(t.iloc[-1], f"{ny_hhmm(t.iloc[-1], tz)} – last candle before the time-out closed at {c[-1]:.2f} "
                                    f"({net:+.1f} pts, {net / atr:+.1f} ATR from the freeze).", "extreme"))
    return sorted(events, key=lambda e: e.time_utc), hit


def why_points(s: pd.Series, after: pd.DataFrame, hit: dict[str, str], tz: str) -> tuple[list[str], str, float]:
    """Reasons for the main move: trend, liquidity, volatility, two-sidedness, setup verdict."""
    close, atr = float(s["close"]), float(s["atr"])
    if after.empty:
        return ["No bars after the freeze (data gap)."], "up", 0.0
    up_ext = float(after["high"].max()) - close
    dn_ext = close - float(after["low"].min())
    main = "up" if up_ext >= dn_ext else "down"
    size = max(up_ext, dn_ext) / atr
    other = min(up_ext, dn_ext) / atr
    trend = str(s["h1_trend"])
    out = [f"Main move: {main.upper()} {size:.1f} ATR ({max(up_ext, dn_ext):.0f} pts) versus {other:.1f} ATR the other way."]
    if trend in ("up", "down"):
        with_trend = (main == "up") == (trend == "up")
        out.append("It went WITH the H1 trend – on trend days continuation usually wins and counter-trend setups fail."
                   if with_trend else
                   "It went AGAINST the H1 trend – a counter-trend move, typically a liquidity grab or a reversal "
                   "after an extended run.")
    else:
        out.append("The H1 trend was flat – no higher-timeframe push, so moves tend to stay inside the ranges.")
    levels = scenario_levels(s)
    broke = [k for k, v in hit.items() if v == "broke" and ((levels[k] > close) == (main == "up"))]
    held = [k for k, v in hit.items() if v == "rejected"]
    if broke:
        names = ", ".join(LEVEL_LABELS[k] for k in broke)
        out.append(f"It ran through the {names}: stop orders resting beyond those levels were triggered and fuelled the move "
                   f"(price is drawn to liquidity).")
    else:
        ahead = sorted(((abs(p - close), k) for k, p in levels.items() if (p > close) == (main == "up")))
        if ahead:
            out.append(f"It did not reach the next liquidity in its direction ({LEVEL_LABELS[ahead[0][1]]} at "
                       f"{levels[ahead[0][1]]:.2f}) – the move ran out of fuel before it.")
    for k in held:
        out.append(f"The {LEVEL_LABELS[k]} ({levels[k]:.2f}) held at first: price tested it and turned – that level was defended.")
    body = (after["close"] - after["open"]).abs()
    b = int(body.to_numpy().argmax())
    tag = SPECIAL_TIMES.get(ny_hhmm(after["time_utc"].iloc[b], tz))
    if tag and body.iloc[b] >= 1.5 * atr:
        out.append(f"Volatility came at {tag}: a {body.iloc[b] / atr:.1f}-ATR candle. Scheduled events move price more than "
                   f"pre-open structure – be careful holding tight stops into them.")
    if up_ext >= 1.5 * atr and dn_ext >= 1.5 * atr:
        out.append("Two-sided, choppy price action: both directions moved at least 1.5 ATR, so tight stops on either "
                   "side were likely to be hit.")
    det, d = s["detector"], s["direction_hint"]
    if det == "no_trade":
        missed = bool(s["long_hit_target"]) or bool(s["short_hit_target"])
        out.append("No setup was present. " + ("A 2R move still came – but without a signal it was not predictable from this bar."
                                              if missed else "Neither side made +2R before -1R – waiting was right."))
    else:
        worked = bool(s[f"{d}_hit_target"])
        out.append(f"The {SETUP_NAMES.get(det, det)} signal pointed {d.upper()}: it "
                   + ("WORKED – a 1-ATR-stop trade reached +2R first." if worked else
                      "FAILED – a 1-ATR stop was hit before +2R."))
    return out, main, size


def market_story(s: pd.Series, before: pd.DataFrame, after: pd.DataFrame, tz: str) -> Story:
    """Full explanation for one scenario (after = M5 bars from the freeze to the time-out)."""
    events, hit = after_events(s, after, tz)
    why, main, size = why_points(s, after, hit, tz)
    return Story(trigger_text(s), context_points(s, before, tz), events, why, main, size, hit)
