"""Auto-add DFO Region 2 (Lower Mainland) salmon rivers that have a LIVE gauge.

For each river below we search Environment Canada's BC stations by name, then
keep the best candidate that actually returns real-time data right now. Rivers
with no active real-time gauge are skipped (logged), so the config only ever
contains rivers the app can actually report on. New rivers are appended to
config/rivers.yaml with `verified: false` and placeholder thresholds; run
`tools/calibrate_thresholds.py --write --unverified-only` afterwards to set
real thresholds from each station's history.

Run on a machine/CI with internet:  python tools/add_region2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402
from src.sources import fetch_station          # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
STATIONS_URL = "https://api.weather.gc.ca/collections/hydrometric-stations/items"
UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}

# name keyword -> metadata. metric/fed_by/season are editorial defaults;
# thresholds come from calibration. Keyword matches STATION_NAME (case-insensitive).
REGION2 = [
    dict(keyword="ALOUETTE RIVER", name="Alouette River", metric="level", fed_by="rain",
         region="Lower Mainland", season=[9, 10, 11, 12], species=["coho", "chum", "chinook"]),
    dict(keyword="CHEHALIS RIVER", name="Chehalis River", metric="level", fed_by="rain",
         region="Fraser Valley", season=[9, 10, 11, 12], species=["coho", "chum", "chinook", "steelhead"]),
    dict(keyword="HARRISON RIVER", name="Harrison River", metric="level", fed_by="rain",
         region="Fraser Valley", season=[9, 10, 11, 12], species=["chum", "coho", "chinook", "sockeye"]),
    dict(keyword="STAVE RIVER", name="Stave River", metric="level", fed_by="rain",
         region="Lower Mainland", season=[9, 10, 11, 12], species=["chum", "coho", "chinook"]),
    dict(keyword="CHEAKAMUS RIVER", name="Cheakamus River", metric="level", fed_by="glacier",
         region="Sea-to-Sky", season=[8, 9, 10, 11], species=["coho", "chum", "pink", "steelhead"]),
    dict(keyword="COQUIHALLA RIVER", name="Coquihalla River", metric="level", fed_by="snow",
         region="Fraser Valley", season=[9, 10, 11], species=["coho", "chinook", "steelhead"]),
    dict(keyword="NICOMEKL RIVER", name="Nicomekl River", metric="level", fed_by="rain",
         region="Lower Mainland", season=[10, 11, 12], species=["coho", "chum", "chinook"]),
    dict(keyword="SERPENTINE RIVER", name="Serpentine River", metric="level", fed_by="rain",
         region="Lower Mainland", season=[10, 11, 12], species=["coho", "chum", "chinook"]),
    dict(keyword="PITT RIVER", name="Pitt River", metric="level", fed_by="glacier",
         region="Lower Mainland", season=[8, 9, 10, 11], species=["coho", "chum", "chinook", "sockeye"]),
    dict(keyword="MAMQUAM RIVER", name="Mamquam River", metric="level", fed_by="glacier",
         region="Sea-to-Sky", season=[8, 9, 10, 11], species=["coho", "chum", "pink"]),
    dict(keyword="NORRISH CREEK", name="Norrish Creek", metric="level", fed_by="rain",
         region="Fraser Valley", season=[10, 11, 12], species=["coho", "chum", "steelhead"]),
    dict(keyword="KANAKA CREEK", name="Kanaka Creek", metric="level", fed_by="rain",
         region="Lower Mainland", season=[10, 11, 12], species=["coho", "chum"]),
    dict(keyword="SILVERHOPE CREEK", name="Silverhope Creek", metric="level", fed_by="rain",
         region="Fraser Valley", season=[9, 10, 11], species=["coho", "chum"]),
    dict(keyword="SUMAS RIVER", name="Sumas River", metric="level", fed_by="rain",
         region="Fraser Valley", season=[10, 11, 12], species=["coho", "chum", "chinook"]),
]

_PLACEHOLDER = {"level": (0.50, 1.20, 2.00), "flow": (50, 200, 500)}


def bc_stations() -> list[dict]:
    r = requests.get(STATIONS_URL, params={"PROV_TERR_STATE_LOC": "BC", "f": "json", "limit": 10000},
                     headers=UA, timeout=90)
    r.raise_for_status()
    return r.json().get("features", [])


def pick_station(feats: list[dict], keyword: str) -> dict | None:
    """Best real-time station whose name contains keyword and returns data now."""
    kw = keyword.lower()
    cands = [f for f in feats if kw in (f.get("properties", {}).get("STATION_NAME", "") or "").lower()]
    # prefer Active, then shortest name (usually the main-stem gauge)
    cands.sort(key=lambda f: (f["properties"].get("STATUS_EN") != "Active",
                              len(f["properties"].get("STATION_NAME", ""))))
    for f in cands:
        sid = f["properties"].get("STATION_NUMBER")
        try:
            data = fetch_station(sid)
        except Exception:
            continue
        if data.readings and (data.latest_metric("level") or data.latest_metric("flow")):
            return f
    return None


def block(entry: dict, feat: dict) -> str:
    p = feat["properties"]
    sid = p["STATION_NUMBER"]
    lon, lat = (feat.get("geometry", {}).get("coordinates", [None, None]) + [None, None])[:2]
    gl, gh, bl = _PLACEHOLDER[entry["metric"]]
    species = ", ".join(f'"{s}"' for s in entry["species"])
    season = ", ".join(str(m) for m in entry["season"])
    return f'''
  - name: "{entry['name']}"
    station: "{sid}"          # {p.get('STATION_NAME','')} (auto-added, calibrate)
    verified: false
    lat: {round(lat, 5) if lat is not None else 0}
    lon: {round(lon, 5) if lon is not None else 0}
    metric: {entry['metric']}
    region: "{entry['region']}"
    fed_by: {entry['fed_by']}
    season_months: [{season}]
    species: [{species}]
    good_low: {gl}
    good_high: {gh}
    blown_out: {bl}
    notes: "Auto-added from DFO Region 2; thresholds pending calibration."'''


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    existing = {r["station"] for r in cfg.get("rivers", [])}
    feats = bc_stations()

    added, skipped = [], []
    new_blocks = []
    for entry in REGION2:
        feat = pick_station(feats, entry["keyword"])
        if feat is None:
            skipped.append(f"{entry['name']} (no active real-time gauge)")
            continue
        sid = feat["properties"]["STATION_NUMBER"]
        if sid in existing:
            skipped.append(f"{entry['name']} ({sid} already present)")
            continue
        existing.add(sid)
        new_blocks.append(block(entry, feat))
        added.append(f"{entry['name']} -> {sid} ({feat['properties'].get('STATION_NAME','')})")

    if new_blocks:
        CONFIG.write_text(CONFIG.read_text().rstrip() + "\n" + "\n".join(new_blocks) + "\n")

    print(f"Added {len(added)} rivers:")
    for a in added:
        print("  +", a)
    print(f"Skipped {len(skipped)}:")
    for s in skipped:
        print("  -", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
