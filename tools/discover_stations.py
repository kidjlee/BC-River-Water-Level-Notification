"""Find & verify BC hydrometric station IDs from the ECCC GeoMet OGC API.

Run this from a machine or CI with internet (the API is free, no key):

    python tools/discover_stations.py --search chilliwack
    python tools/discover_stations.py --search "cowichan"
    python tools/discover_stations.py --verify 08MH001 08MF005
    python tools/discover_stations.py --list-bc > all_bc_stations.txt

Use it to confirm the `station`, `lat`, `lon` for each river in
config/rivers.yaml, then flip that river's `verified:` to true.
"""
from __future__ import annotations

import argparse
import sys

import requests

STATIONS_URL = "https://api.weather.gc.ca/collections/hydrometric-stations/items"
UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}


def _get(params: dict) -> list[dict]:
    params = {"f": "json", "lang": "en", "limit": 10000, **params}
    resp = requests.get(STATIONS_URL, params=params, headers=UA, timeout=60)
    resp.raise_for_status()
    return resp.json().get("features", [])


def _row(feat: dict) -> str:
    p = feat.get("properties", {})
    coords = feat.get("geometry", {}).get("coordinates", [None, None])
    lon, lat = (coords + [None, None])[:2]
    return (
        f"{p.get('STATION_NUMBER',''):<10}  "
        f"{(p.get('STATION_NAME','') or '')[:48]:<48}  "
        f"lat={lat}  lon={lon}  "
        f"status={p.get('STATUS_EN','')}"
    )


def search(term: str) -> None:
    feats = _get({"PROV_TERR_STATE_LOC": "BC"})
    term_low = term.lower()
    hits = [f for f in feats if term_low in (f.get("properties", {}).get("STATION_NAME", "") or "").lower()]
    if not hits:
        print(f"No BC stations matching '{term}'.")
        return
    print(f"{len(hits)} BC station(s) matching '{term}':\n")
    for f in sorted(hits, key=lambda f: f["properties"].get("STATION_NAME", "")):
        print("  " + _row(f))


def verify(ids: list[str]) -> None:
    for sid in ids:
        feats = _get({"STATION_NUMBER": sid})
        if feats:
            print("OK  " + _row(feats[0]))
        else:
            print(f"MISSING  {sid}  (not found — check the ID)")


def list_bc() -> None:
    feats = _get({"PROV_TERR_STATE_LOC": "BC"})
    for f in sorted(feats, key=lambda f: f["properties"].get("STATION_NUMBER", "")):
        print(_row(f))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--search", metavar="NAME", help="find BC stations by river/name substring")
    g.add_argument("--verify", nargs="+", metavar="ID", help="check that station ID(s) exist")
    g.add_argument("--list-bc", action="store_true", help="dump all BC stations")
    args = ap.parse_args(argv)

    try:
        if args.search:
            search(args.search)
        elif args.verify:
            verify(args.verify)
        elif args.list_bc:
            list_bc()
    except requests.HTTPError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
