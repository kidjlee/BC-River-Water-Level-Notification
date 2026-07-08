"""Fetch real-time water data from Environment and Climate Change Canada.

Uses the GeoMet OGC API `hydrometric-realtime` collection (free, no key) — the
same reliable endpoint used to verify stations. Each feature carries DATETIME,
LEVEL (m) and DISCHARGE (cms). We pull the last few days and keep the readings
that have a value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

REALTIME_URL = "https://api.weather.gc.ca/collections/hydrometric-realtime/items"
USER_AGENT = "bc-river-water-level-notifier/1.0 (personal fishing tool)"


@dataclass
class Reading:
    timestamp: datetime
    level_m: float | None
    discharge_cms: float | None


def _metric_value(reading: "Reading", metric: str) -> float | None:
    return reading.discharge_cms if metric == "flow" else reading.level_m


@dataclass
class StationData:
    station: str
    readings: list[Reading] = field(default_factory=list)

    @property
    def latest(self) -> Reading | None:
        levels = [r for r in self.readings if r.level_m is not None]
        return levels[-1] if levels else None

    def level_at_or_before(self, ts: datetime) -> Reading | None:
        """Most recent reading with a level at or before `ts` (for trend calc)."""
        candidates = [r for r in self.readings if r.level_m is not None and r.timestamp <= ts]
        return candidates[-1] if candidates else None

    # --- metric-agnostic accessors (level in m, or flow in cms) ------------
    def series(self, metric: str) -> list[tuple[datetime, float]]:
        out = []
        for r in self.readings:
            v = _metric_value(r, metric)
            if v is not None:
                out.append((r.timestamp, v))
        return out

    def latest_metric(self, metric: str) -> tuple[datetime, float] | None:
        s = self.series(metric)
        return s[-1] if s else None

    def metric_at_or_before(self, ts: datetime, metric: str) -> tuple[datetime, float] | None:
        s = [(t, v) for t, v in self.series(metric) if t <= ts]
        return s[-1] if s else None


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_station(station: str, prov: str = "BC", hours_back: int = 96, timeout: int = 60) -> StationData:
    """Fetch recent real-time readings for one station via the OGC API."""
    start = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "STATION_NUMBER": station,
        "datetime": f"{start}/..",
        "limit": 10000,
        "sortby": "DATETIME",
        "f": "json",
    }
    resp = requests.get(REALTIME_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    feats = resp.json().get("features", [])

    data = StationData(station=station)
    for f in feats:
        p = f.get("properties", {})
        ts = _parse_timestamp(p.get("DATETIME"))
        if ts is None:
            continue
        data.readings.append(Reading(timestamp=ts, level_m=_to_float(p.get("LEVEL")),
                                     discharge_cms=_to_float(p.get("DISCHARGE"))))
    data.readings.sort(key=lambda r: r.timestamp)
    return data


def _parse_timestamp(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    # ECCC uses ISO-8601, usually with a timezone offset (e.g. 2026-07-08T13:05:00-08:00).
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
