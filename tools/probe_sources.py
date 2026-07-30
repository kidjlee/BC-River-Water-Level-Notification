"""Diagnose ECCC coverage: where does each source's data actually end?

The 1-year charts had holes. This answers *why* by asking the API directly,
per station:

  * hydrometric-daily-mean  -> oldest/newest DATE, record count (the archive)
  * hydrometric-realtime    -> oldest/newest DATETIME (the retention window)

The gap between "archive newest" and "realtime oldest" is what we cannot
backfill from ECCC and must accumulate forward instead.

Run: python tools/probe_sources.py [station ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/rivers.yaml"
BASE = "https://api.weather.gc.ca/collections"
UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}


def _edge(collection: str, station: str, sort_field: str, newest: bool):
    """Return the single oldest/newest record for a station, or None."""
    params = {
        "STATION_NUMBER": station,
        "f": "json",
        "limit": 1,
        "sortby": ("-" if newest else "") + sort_field,
    }
    r = requests.get(f"{BASE}/{collection}/items", params=params, headers=UA, timeout=90)
    r.raise_for_status()
    body = r.json()
    feats = body.get("features", [])
    return (feats[0].get("properties", {}) if feats else None), body.get(
        "numberMatched"
    )


def probe(station: str, metric: str) -> None:
    field = "DISCHARGE" if metric == "flow" else "LEVEL"
    print(f"\n=== {station} ({metric} -> {field}) ===")

    for coll, sort_field, stamp in (
        ("hydrometric-daily-mean", "DATE", "DATE"),
        ("hydrometric-realtime", "DATETIME", "DATETIME"),
    ):
        try:
            oldest, n = _edge(coll, station, sort_field, newest=False)
            newest, _ = _edge(coll, station, sort_field, newest=True)
        except Exception as e:
            print(f"  {coll}: FAILED ({e})")
            continue
        if not oldest or not newest:
            print(f"  {coll}: no records")
            continue
        print(
            f"  {coll}: matched={n} "
            f"oldest={oldest.get(stamp)} newest={newest.get(stamp)}"
        )
        print(
            f"      newest {field}={newest.get(field)!r} "
            f"(oldest {field}={oldest.get(field)!r})"
        )


def main() -> int:
    wanted = sys.argv[1:]
    cfg = yaml.safe_load(CONFIG.read_text())
    rivers = cfg.get("rivers", [])
    if wanted:
        rivers = [r for r in rivers if r["station"] in wanted]

    # Which hydrometric collections exist at all?
    try:
        r = requests.get(f"{BASE}?f=json", headers=UA, timeout=90)
        r.raise_for_status()
        ids = [c.get("id") for c in r.json().get("collections", [])]
        print("hydrometric collections available:")
        for i in sorted(x for x in ids if x and "hydro" in x):
            print(f"  - {i}")
    except Exception as e:
        print(f"collection list FAILED ({e})")

    for river in rivers:
        probe(river["station"], river.get("metric", "level"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
