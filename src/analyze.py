"""Turn raw numbers into a simple fishing verdict + short outlook.

This is deliberately transparent (rules, not a black box) so you can reason
about and tune every decision. The pieces:

  * ZONE   - where the current level sits vs your good_low/good_high/blown_out.
  * TREND  - rising / falling / steady over the last ~24h, and how fast.
  * VERDICT- one of: GO, GET_READY, MARGINAL, BLOWN_OUT, TOO_LOW, NO_DATA.
             Combines zone + trend the way an angler would read a gauge:
             in the zone and steady/dropping after a bump == prime.
  * OUTLOOK- a plain-language "next few days" line driven by the rain forecast.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .sources import StationData
from .weather import RainOutlook

# Verdicts, ordered best -> worst for sorting the dashboard/alerts.
VERDICT_ORDER = ["GO", "GET_READY", "MARGINAL", "TOO_LOW", "BLOWN_OUT", "NO_DATA"]

EMOJI = {
    "GO": "🟢",
    "GET_READY": "🟡",
    "MARGINAL": "🟠",
    "TOO_LOW": "🔵",
    "BLOWN_OUT": "🔴",
    "NO_DATA": "⚪",
}


@dataclass
class Assessment:
    river: str
    station: str
    verdict: str
    level_m: float | None
    trend: str                 # "rising" | "falling" | "steady" | "unknown"
    rate_m_per_h: float | None
    headline: str              # one-line summary for a human
    outlook: str               # next-few-days sentence
    zone: str                  # "low" | "good" | "high" | "blown"
    updated: str | None        # ISO timestamp of latest reading

    @property
    def emoji(self) -> str:
        return EMOJI.get(self.verdict, "⚪")

    @property
    def is_alertable(self) -> bool:
        """Worth pinging the user about right now."""
        return self.verdict in ("GO", "GET_READY")


def _zone(level: float, river: dict) -> str:
    if level < river["good_low"]:
        return "low"
    if level <= river["good_high"]:
        return "good"
    if level <= river["blown_out"]:
        return "high"
    return "blown"


def _trend(data: StationData) -> tuple[str, float | None]:
    latest = data.latest
    if latest is None:
        return "unknown", None
    past = data.level_at_or_before(latest.timestamp - timedelta(hours=24))
    if past is None or past.timestamp == latest.timestamp:
        return "unknown", None
    hours = (latest.timestamp - past.timestamp).total_seconds() / 3600.0
    if hours <= 0:
        return "unknown", None
    rate = (latest.level_m - past.level_m) / hours
    if rate > 0.01:
        return "rising", rate
    if rate < -0.01:
        return "falling", rate
    return "steady", rate


def assess(river: dict, data: StationData, rain: RainOutlook | None, defaults: dict) -> Assessment:
    name = river["name"]
    station = river["station"]
    latest = data.latest

    if latest is None or latest.level_m is None:
        return Assessment(
            river=name, station=station, verdict="NO_DATA", level_m=None,
            trend="unknown", rate_m_per_h=None,
            headline="No recent data from the station.",
            outlook="", zone="low", updated=None,
        )

    level = latest.level_m
    zone = _zone(level, river)
    trend, rate = _trend(data)
    caution_rate = defaults.get("rising_rate_caution_m_per_h", 0.05)

    # --- verdict logic -----------------------------------------------------
    if zone == "blown":
        verdict = "BLOWN_OUT"
        headline = f"{level:.2f} m — too high / likely dirty. Sit this one out."
    elif zone == "high":
        if trend == "falling":
            verdict = "GET_READY"
            headline = f"{level:.2f} m and dropping — clearing into shape soon."
        else:
            verdict = "MARGINAL"
            headline = f"{level:.2f} m — high; fishable spots but use caution."
    elif zone == "good":
        if trend == "rising" and rate is not None and rate > caution_rate:
            verdict = "MARGINAL"
            headline = f"{level:.2f} m and rising fast — may blow out; go now or wait."
        else:
            verdict = "GO"
            drop = " and dropping (prime)" if trend == "falling" else ""
            headline = f"{level:.2f} m — in the zone{drop}. Good to fish. 🎣"
    else:  # low
        if trend == "rising":
            verdict = "GET_READY"
            headline = f"{level:.2f} m — low but rising toward the zone."
        else:
            verdict = "TOO_LOW"
            headline = f"{level:.2f} m — too low. Needs water."

    outlook = _outlook(zone, trend, rain, river)
    return Assessment(
        river=name, station=station, verdict=verdict, level_m=round(level, 2),
        trend=trend, rate_m_per_h=(round(rate, 3) if rate is not None else None),
        headline=headline, outlook=outlook, zone=zone,
        updated=latest.timestamp.isoformat(),
    )


def _outlook(zone: str, trend: str, rain: RainOutlook | None, river: dict) -> str:
    if rain is None or not rain.available:
        return "Rain forecast unavailable."
    r72 = rain.next_72h_mm
    if r72 >= 40:
        band = "heavy rain"
    elif r72 >= 15:
        band = "moderate rain"
    elif r72 >= 3:
        band = "light rain"
    else:
        band = "little/no rain"

    parts = [f"Next 3 days: {band} forecast ({r72:.0f} mm)."]
    if zone in ("low",) and r72 >= 15:
        parts.append("Expect the river to rise — could push into the zone.")
    elif zone in ("good",) and r72 >= 40:
        parts.append("Watch for a blow-out; fish before it spikes.")
    elif zone in ("high", "blown") and r72 < 3:
        parts.append("Dry spell should let it drop back into shape.")
    elif zone == "good" and r72 < 3:
        parts.append("Stable conditions — should stay fishable.")

    # Point out the best-looking upcoming day by rain (dry day after wet = good).
    if rain.daily_mm:
        best_day = min(range(len(rain.daily_mm)), key=lambda i: rain.daily_mm[i])
        labels = ["today", "tomorrow", "in 2 days", "in 3 days", "in 4 days"]
        if best_day < len(labels) and rain.daily_mm[best_day] < 5:
            parts.append(f"Driest day: {labels[best_day]}.")
    return " ".join(parts)
