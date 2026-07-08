"""Shared helper: pull long daily history from ECCC's GeoMet OGC API.

Collection `hydrometric-daily-mean` holds decades of daily mean level (m) and
discharge (cms) per station — the right source for calibrating thresholds and
training the forecast model. Free, no API key.
"""
from __future__ import annotations

import requests

DAILY_URL = "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}


def fetch_daily(station: str, metric: str, timeout: int = 90):
    """Return (dates, values) for the station's daily-mean history.

    metric: "level" -> LEVEL (m); "flow" -> DISCHARGE (cms).
    """
    field = "DISCHARGE" if metric == "flow" else "LEVEL"
    dates, values = [], []
    offset = 0
    page = 10000
    while True:
        params = {
            "STATION_NUMBER": station,
            "f": "json",
            "limit": page,
            "offset": offset,
            "sortby": "DATE",
        }
        resp = requests.get(DAILY_URL, params=params, headers=UA, timeout=timeout)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
        if not feats:
            break
        for f in feats:
            p = f.get("properties", {})
            val = p.get(field)
            date = p.get("DATE")
            if val is not None and date:
                dates.append(date[:10])
                values.append(float(val))
        if len(feats) < page:
            break
        offset += page
    return dates, values
