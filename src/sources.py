"""Fetch real-time water level data from Environment and Climate Change Canada.

Two free, no-API-key sources are supported:

  * MSC Datamart CSV  (default) - one file per station, last ~2 days of readings.
        https://dd.weather.gc.ca/hydrometric/csv/BC/hourly/BC_<ID>_hourly_hydrometric.csv
  * GeoMet OGC API    - GeoJSON, used by tools/discover_stations.py for lookups.
        https://api.weather.gc.ca/collections/hydrometric-realtime

We parse the CSV defensively: column order/labels vary slightly (bilingual
headers), so we locate columns by matching on substrings rather than index.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

DATAMART_CSV = (
    "https://dd.weather.gc.ca/hydrometric/csv/{prov}/hourly/"
    "{prov}_{station}_hourly_hydrometric.csv"
)
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


def _find_col(header: list[str], *needles: str) -> int | None:
    for i, col in enumerate(header):
        low = col.lower()
        if all(n.lower() in low for n in needles):
            return i
    return None


def _parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fetch_station(station: str, prov: str = "BC", timeout: int = 30) -> StationData:
    """Download and parse the hourly hydrometric CSV for one station."""
    url = DATAMART_CSV.format(prov=prov, station=station)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()

    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        return StationData(station=station)

    header = rows[0]
    date_idx = _find_col(header, "date")
    level_idx = _find_col(header, "water", "level")
    if level_idx is None:  # French-only header fallback
        level_idx = _find_col(header, "niveau")
    disch_idx = _find_col(header, "discharge")
    if disch_idx is None:
        disch_idx = _find_col(header, "débit")

    data = StationData(station=station)
    for row in rows[1:]:
        if date_idx is None or date_idx >= len(row):
            continue
        ts = _parse_timestamp(row[date_idx])
        if ts is None:
            continue
        level = _parse_float(row[level_idx]) if level_idx is not None and level_idx < len(row) else None
        disch = _parse_float(row[disch_idx]) if disch_idx is not None and disch_idx < len(row) else None
        data.readings.append(Reading(timestamp=ts, level_m=level, discharge_cms=disch))

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
