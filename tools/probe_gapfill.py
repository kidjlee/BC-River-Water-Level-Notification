"""Probe candidate sources for the hole between the archive and the live window.

Probe 1 established the two ECCC OGC collections don't meet:
  * hydrometric-daily-mean = approved archive; its last *non-null* day lags by
    weeks (Vedder) to ~19 months (Alouette, Skeena).
  * hydrometric-realtime   = a rolling 30-day window, no more.

So every station has an unfillable hole unless a third source covers it. This
checks two things:

  A) Are the daily-mean rows in Vedder's hole actually present-but-null (a
     publication lag) or missing entirely (a fetch bug)?
  B) Does Water Office's real_time_data CSV service serve provisional data far
     enough back to bridge the hole?

Run: python tools/probe_gapfill.py
"""
from __future__ import annotations

import sys

import requests

UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}
DAILY = "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
WO = "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"


def probe_nulls(station: str, start: str, end: str) -> None:
    """A) Show every daily-mean row in a range, nulls included."""
    print(f"\n--- A) daily-mean rows for {station} {start}..{end} ---")
    params = {
        "STATION_NUMBER": station,
        "datetime": f"{start}/{end}",
        "f": "json",
        "limit": 100,
        "sortby": "DATE",
    }
    try:
        r = requests.get(DAILY, params=params, headers=UA, timeout=90)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as e:
        print(f"  FAILED ({e})")
        return
    print(f"  rows returned: {len(feats)}")
    nulls = 0
    for f in feats:
        p = f.get("properties", {})
        lvl = p.get("LEVEL")
        if lvl is None:
            nulls += 1
        print(f"    {p.get('DATE')}  LEVEL={lvl!r}")
    print(f"  -> {nulls}/{len(feats)} rows have a null LEVEL")


def probe_wateroffice(station: str, param: int, start: str, end: str) -> None:
    """B) Can Water Office serve provisional data older than 30 days?"""
    print(f"\n--- B) wateroffice real_time_data {station} param={param} {start}..{end} ---")
    params = {
        "stations[]": station,
        "parameters[]": param,
        "start_date": f"{start} 00:00:00",
        "end_date": f"{end} 23:59:59",
    }
    try:
        r = requests.get(WO, params=params, headers=UA, timeout=120)
    except Exception as e:
        print(f"  FAILED ({e})")
        return
    print(f"  HTTP {r.status_code}  content-type={r.headers.get('content-type')!r}")
    body = r.text
    print(f"  bytes={len(body)}")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    print(f"  lines={len(lines)}")
    for ln in lines[:3]:
        print(f"    HEAD | {ln[:120]}")
    for ln in lines[-3:]:
        print(f"    TAIL | {ln[:120]}")


def main() -> int:
    # A) Vedder's hole was 2026-06-09..2026-06-28.
    probe_nulls("08MH001", "2026-06-01", "2026-07-05")
    # A2) Alouette, whose archive supposedly stops at 2024-12-31.
    probe_nulls("08MH005", "2025-06-01", "2025-06-10")

    # B) Ask for a span that starts well before the 30-day realtime window.
    #    46 = water level, 47 = discharge.
    probe_wateroffice("08MH005", 46, "2025-08-01", "2026-07-30")
    probe_wateroffice("08EF001", 47, "2025-08-01", "2026-07-30")
    return 0


if __name__ == "__main__":
    sys.exit(main())
