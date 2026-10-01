"""Rule-based explanation of a round: context at the freeze, what the setup was,
what price did afterwards (timeline) and why the big move happened.

Bullets are short and carry a tone (good / bad / warn / info) so the page can show
them as ✔ / ✖ / ⚠ / • lines. Everything comes from bars and levels; no AI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LEVEL_LABELS = {
    "asian_high": "Asian high", "asian_low": "Asian low",
    "london_high": "London high", "london_low": "London low",
    "pdh": "previous-day high", "pdl": "previous-day low",
    "or_high": "opening-range high", "or_low": "opening-range low",
}
SHORT_LEVELS = {
    "asian_high": "Asian H", "asian_low": "Asian L", "london_high": "London H", "london_low": "London L",
    "pdh": "PDH", "pdl": "PDL", "or_high": "OR H", "or_low": "OR L",
}
SETUP_NAMES = {
    "sweep": "Liquidity sweep", "bos": "Displacement / BOS", "orb": "Opening-range break",
    "fvg_retest": "FVG retest", "no_trade": "No setup",
}
SPECIAL_TIMES = {
    "08:30": "08:30 (US data release time)",
    "09:30": "09:30 (cash open)",
    "09:35": "09:35 (just after the cash open)",
    "10:00": "10:00 (US data release time)",
}
CHOP_ATR = 1.5


def bullet(tone: str, text: str) -> dict:
    """One display line; tone is good | bad | warn | info."""
    return {"tone": tone, "text": text}


@dataclass
class Event:
    """One timeline item after the freeze."""

    time_utc: pd.Timestamp
    text: str
    kind: str  # level | extreme | candle
    price: float = float("nan")
    label: str = ""  # short chart-marker text


@dataclass
class Story:
    """Explanation pieces shown on the result page."""

    trigger: str
    context: list[dict]
    events: list[Event]
    why: list[dict]
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
    """One sentence: what the detector saw at the freeze bar."""
    det, d = s["detector"], str(s["direction_hint"]).upper()
    lvl = LEVEL_LABELS.get(str(s["level_name"]), str(s["level_name"]))
    price = s["level_price"]
    if det == "sweep":
        side, back = ("above", "below") if d == "SHORT" else ("below", "above")
        return f"Price wicked {side} the {lvl} ({price:.2f}) and closed back {back} it: stops were taken → reversal {d}."
    if det == "bos":
        side = "high" if d == "LONG" else "low"
        return f"A big candle (body > 1.5 ATR) closed beyond the last swing {side} ({price:.2f}) → momentum {d}."
    if det == "orb":
        edge = f"above the high {s['or_high']:.2f}" if d == "LONG" else f"below the low {s['or_low']:.2f}"
        return f"Price closed {edge} of the 09:30–09:45 opening range → momentum {d}."
    if det == "fvg_retest":
        return f"Price came back into a fair value gap ({s['fvg_bottom']:.2f}–{s['fvg_top']:.2f}) for the first time → {d}."
    return "No setup fired here. This is a control round: waiting is usually right."


def context_points(s: pd.Series, before: pd.DataFrame, tz: str, target_r: float) -> list[dict]:
    """Facts visible at the freeze: trend, size of R, session move, nearest levels."""
    close, atr = float(s["close"]), float(s["atr"])
    out = [bullet("info", f"H1 trend: {str(s['h1_trend']).upper()}"),
           bullet("info", f"ATR (M5): {atr:.0f} pts → 1R ≈ {atr:.0f} pts, a big move ({target_r:.0f}R) ≈ {target_r * atr:.0f} pts")]
    ny = before["time_utc"].dt.tz_convert(tz)
    today = before[(ny.dt.date == s["freeze_time_utc"].tz_convert(tz).date()) & (ny.dt.strftime("%H:%M") >= "08:00")]
    if len(today):
        move = close - float(today["open"].iloc[0])
        out.append(bullet("info", f"Move since 08:00: {move:+.0f} pts ({move / atr:+.1f} ATR)"))
    levels = scenario_levels(s)
    above = sorted((p - close, k) for k, p in levels.items() if p > close)
    below = sorted((close - p, k) for k, p in levels.items() if p < close)
    out.append(bullet("info", f"Next level above: {LEVEL_LABELS[above[0][1]]} {levels[above[0][1]]:.2f} (+{above[0][0]:.0f} pts)"
                      if above else "Next level above: none (open air)"))
    out.append(bullet("info", f"Next level below: {LEVEL_LABELS[below[0][1]]} {levels[below[0][1]]:.2f} (−{below[0][0]:.0f} pts)"
                      if below else "Next level below: none (open air)"))
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
        verb = "broke" if broke else "held"
        events.append(Event(t, f"{ny_hhmm(t, tz)}  {LEVEL_LABELS[key]} {price:.2f} {verb}", "level", price,
                            f"{SHORT_LEVELS[key]} {verb}"))
        hit[key] = "broke" if broke else "rejected"
    return events, hit


def after_events(s: pd.Series, after: pd.DataFrame, tz: str) -> tuple[list[Event], dict[str, str]]:
    """Timeline after the freeze: level touches, biggest candle, high, low, last close."""
    if after.empty:
        return [], {}
    close, atr = float(s["close"]), float(s["atr"])
    h, l, o, c = (after[k].to_numpy(float) for k in ("high", "low", "open", "close"))
    t = after["time_utc"]
    events, hit = _level_events(s, after, tz)
    body = np.abs(c - o)
    b = int(body.argmax())
    tag = SPECIAL_TIMES.get(ny_hhmm(t.iloc[b], tz))
    kind = "up" if c[b] > o[b] else "down"
    events.append(Event(t.iloc[b], f"{ny_hhmm(t.iloc[b], tz)}  Biggest candle: {kind} {body[b]:.0f} pts ({body[b] / atr:.1f} ATR)"
                        + (f" – {tag}" if tag else ""), "candle", label=f"big {body[b] / atr:.1f} ATR"))
    hi, lo = int(h.argmax()), int(l.argmin())
    events.append(Event(t.iloc[hi], f"{ny_hhmm(t.iloc[hi], tz)}  High {h[hi]:.2f} ({(h[hi] - close) / atr:+.1f} ATR)",
                        "extreme", float(h[hi]), "high"))
    events.append(Event(t.iloc[lo], f"{ny_hhmm(t.iloc[lo], tz)}  Low {l[lo]:.2f} ({(l[lo] - close) / atr:+.1f} ATR)",
                        "extreme", float(l[lo]), "low"))
    net = c[-1] - close
    events.append(Event(t.iloc[-1], f"{ny_hhmm(t.iloc[-1], tz)}  Last close {c[-1]:.2f} ({net:+.0f} pts)", "extreme"))
    return sorted(events, key=lambda e: e.time_utc), hit


def why_points(s: pd.Series, after: pd.DataFrame, hit: dict[str, str], tz: str,
               target_r: float) -> tuple[list[dict], str, float]:
    """Reasons for the big move: size, trend, fuel (levels), spark (candle), chop, setup verdict."""
    close, atr = float(s["close"]), float(s["atr"])
    if after.empty:
        return [bullet("info", "No bars after the freeze (data gap).")], "up", 0.0
    up_ext = float(after["high"].max()) - close
    dn_ext = close - float(after["low"].min())
    main = "up" if up_ext >= dn_ext else "down"
    size, other = max(up_ext, dn_ext) / atr, min(up_ext, dn_ext) / atr
    out = [bullet("good", f"Big move: {main.upper()} {max(up_ext, dn_ext):.0f} pts ({size:.1f} ATR) · other side {other:.1f} ATR")
           if size >= target_r else
           bullet("warn", f"No big move: the largest swing was {main.upper()} {size:.1f} ATR (< {target_r:.0f}R)")]
    trend = str(s["h1_trend"])
    if trend in ("up", "down"):
        out.append(bullet("info", f"Went WITH the H1 trend ({trend.upper()}) – trend days reward continuation"
                          if (main == "up") == (trend == "up") else
                          f"Went AGAINST the H1 trend ({trend.upper()}) – a counter-trend move"))
    else:
        out.append(bullet("info", "H1 trend flat – no higher-timeframe push"))
    levels = scenario_levels(s)
    broke = [k for k, v in hit.items() if v == "broke" and ((levels[k] > close) == (main == "up"))]
    if broke:
        out.append(bullet("info", "Fuel: broke the " + ", ".join(LEVEL_LABELS[k] for k in broke)
                          + " → stops beyond it pushed price further"))
    else:
        ahead = sorted((abs(p - close), k) for k, p in levels.items() if (p > close) == (main == "up"))
        if ahead:
            out.append(bullet("info", f"Ran out of fuel before the {LEVEL_LABELS[ahead[0][1]]} ({levels[ahead[0][1]]:.2f})"))
    for k in (k for k, v in hit.items() if v == "rejected"):
        out.append(bullet("info", f"The {LEVEL_LABELS[k]} ({levels[k]:.2f}) held – price turned there"))
    body = (after["close"] - after["open"]).abs()
    b = int(body.to_numpy().argmax())
    tag = SPECIAL_TIMES.get(ny_hhmm(after["time_utc"].iloc[b], tz))
    if tag and body.iloc[b] >= 1.5 * atr:
        out.append(bullet("warn", f"Spark: a {body.iloc[b] / atr:.1f}-ATR candle at {tag}"))
    if up_ext >= CHOP_ATR * atr and dn_ext >= CHOP_ATR * atr:
        out.append(bullet("warn", f"Choppy: both sides moved {CHOP_ATR}+ ATR – tight stops on either side got hit"))
    det, d = s["detector"], s["direction_hint"]
    if det == "no_trade":
        missed = bool(s["long_hit_target"]) or bool(s["short_hit_target"])
        out.append(bullet("warn" if missed else "good",
                          f"No setup here – a {target_r:.0f}R move still came, but nothing signalled it" if missed
                          else f"No setup and no {target_r:.0f}R move – waiting was right"))
    else:
        worked = bool(s[f"{d}_hit_target"])
        out.append(bullet("good" if worked else "bad",
                          f"{SETUP_NAMES.get(det, det)} → {str(d).upper()}: "
                          + (f"worked (+{target_r:.0f}R before −1R)" if worked else f"failed (−1R before +{target_r:.0f}R)")))
    return out, main, size


def market_story(s: pd.Series, before: pd.DataFrame, after: pd.DataFrame, tz: str, target_r: float = 3.0) -> Story:
    """Full explanation for one scenario (after = M5 bars from the freeze to the time-out)."""
    events, hit = after_events(s, after, tz)
    why, main, size = why_points(s, after, hit, tz, target_r)
    return Story(trigger_text(s), context_points(s, before, tz, target_r), events, why, main, size, hit)
