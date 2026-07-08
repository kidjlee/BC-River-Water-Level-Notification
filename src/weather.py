"""Rain for the watershed above each river (past + forecast).

Uses Open-Meteo (free, no API key). Upstream rain is the biggest driver of when
a coastal BC river rises, so this powers both the plain-language outlook and
the ML forecast's rain features.

We request `past_days` too, so we have recent *observed* rain (a feature the
model needs) alongside the forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class RainOutlook:
    next_24h_mm: float
    next_72h_mm: float
    daily_mm: list[float]                       # forecast precip per day, today first
    past_daily_mm: list[float] = field(default_factory=list)  # observed, oldest first
    daily_dates: list[str] = field(default_factory=list)      # ISO dates for daily_mm
    available: bool = True

    @property
    def past_24h_mm(self) -> float:
        return round(self.past_daily_mm[-1], 1) if self.past_daily_mm else 0.0

    @property
    def past_72h_mm(self) -> float:
        return round(sum(self.past_daily_mm[-3:]), 1) if self.past_daily_mm else 0.0


def fetch_rain(lat: float, lon: float, days: int = 4, past_days: int = 3, timeout: int = 30) -> RainOutlook:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation",
        "daily": "precipitation_sum",
        "forecast_days": days,
        "past_days": past_days,
        "timezone": "America/Vancouver",
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        j = resp.json()
    except Exception:
        return RainOutlook(0.0, 0.0, [], available=False)

    daily_all = [round(x or 0.0, 1) for x in j.get("daily", {}).get("precipitation_sum", [])]
    dates_all = j.get("daily", {}).get("time", []) or []
    # The first `past_days` entries are observed; the rest are forecast (today onward).
    past = daily_all[:past_days]
    fut = daily_all[past_days:]
    fut_dates = dates_all[past_days:]

    # Hourly array also spans past+forecast; forecast hours start at past_days*24.
    hourly = j.get("hourly", {}).get("precipitation", []) or []
    fut_start = past_days * 24
    fut_hourly = hourly[fut_start:]
    next_24h = round(sum(fut_hourly[:24]), 1)
    next_72h = round(sum(fut_hourly[:72]), 1)

    return RainOutlook(
        next_24h_mm=next_24h, next_72h_mm=next_72h,
        daily_mm=fut, past_daily_mm=past, daily_dates=fut_dates,
    )
