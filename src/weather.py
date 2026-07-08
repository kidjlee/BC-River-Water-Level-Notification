"""Rain forecast for the watershed above each river.

Uses Open-Meteo (free, no API key). We pull hourly precipitation for the
river's lat/lon and summarise the next few days. Upstream rain is the single
biggest driver of when a coastal BC river rises, so this is what powers the
"good days ahead" outlook in src/analyze.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class RainOutlook:
    next_24h_mm: float
    next_72h_mm: float
    # precip total (mm) per local calendar day, starting today
    daily_mm: list[float]
    available: bool = True


def fetch_rain(lat: float, lon: float, days: int = 4, timeout: int = 30) -> RainOutlook:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation",
        "daily": "precipitation_sum",
        "forecast_days": days,
        "timezone": "America/Vancouver",
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        j = resp.json()
    except Exception:
        return RainOutlook(0.0, 0.0, [], available=False)

    hourly = j.get("hourly", {}).get("precipitation", []) or []
    next_24h = round(sum(hourly[:24]), 1)
    next_72h = round(sum(hourly[:72]), 1)
    daily = [round(x or 0.0, 1) for x in j.get("daily", {}).get("precipitation_sum", [])]
    return RainOutlook(next_24h_mm=next_24h, next_72h_mm=next_72h, daily_mm=daily)
