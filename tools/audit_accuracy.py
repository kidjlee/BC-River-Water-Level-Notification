"""Audit the live numbers against raw Water Office data, and probe extras.

For every configured river this reports:
  * the raw newest level/discharge from Water Office and how old it is,
  * how many genuine readings our outlier filter throws away, and whether it
    changed the value we'd publish as "current",
  * whether the gauge reports water temperature.

It also scans one station's parameter codes so we know which code is water
temperature rather than guessing, and lists alternative gauges for rivers
whose configured gauge sits on a different reach than the fishery.

Runs from CI (this sandbox can't reach *.gc.ca).
Run: python tools/audit_accuracy.py
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.sources import Reading, _reject_outliers   # noqa: E402
from src.wateroffice import UA, URL                  # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
STATIONS = "https://api.weather.gc.ca/collections/hydrometric-stations/items"


def raw(station: str, param: int, days: int) -> list[tuple[dt.datetime, float]]:
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days)
    r = requests.get(URL, params={
        "stations[]": station, "parameters[]": param,
        "start_date": f"{start} 00:00:00", "end_date": f"{end} 23:59:59",
    }, headers=UA, timeout=120)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        p = line.split(",")
        if len(p) < 4 or not p[1].strip()[:4].isdigit():
            continue
        try:
            out.append((dt.datetime.fromisoformat(p[1].strip().replace("Z", "+00:00")),
                        float(p[3])))
        except ValueError:
            continue
    out.sort()
    return out


def filter_effect(series) -> tuple[int, float | None, float | None]:
    """(readings nulled, raw latest, latest after filter)."""
    rs = [Reading(t, v, None) for t, v in series]
    before = copy.deepcopy(rs)
    _reject_outliers(rs, "level_m")
    dropped = sum(1 for a, b in zip(before, rs) if a.level_m is not None and b.level_m is None)
    kept = [r.level_m for r in rs if r.level_m is not None]
    return dropped, (series[-1][1] if series else None), (kept[-1] if kept else None)


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    cfg = yaml.safe_load(CONFIG.read_text())

    print("=== parameter scan, 08MH001 (which code is water temperature?) ===")
    for code in range(1, 60):
        try:
            s = raw("08MH001", code, 2)
        except Exception:
            continue
        if s:
            print(f"  param {code:2d}: {len(s):4d} readings, latest {s[-1][1]} at {s[-1][0]:%m-%d %H:%M}Z")

    print("\n=== per river: freshness, outlier-filter effect, temperature ===")
    print(f"{'river':28s} {'stn':8s} {'age':>6s} {'raw':>9s} {'pub':>9s} {'drop':>5s}  temp")
    for river in cfg["rivers"]:
        stn, metric = river["station"], river.get("metric", "level")
        param = 47 if metric == "flow" else 46
        try:
            s = raw(stn, param, 5)
        except Exception as e:
            print(f"{river['name'][:28]:28s} {stn:8s} FAILED {e}")
            continue
        age = f"{(now - s[-1][0]).total_seconds() / 3600:.1f}h" if s else "-"
        dropped, rlast, plast = filter_effect(s)
        temps = {}
        for code in (5,):
            try:
                t = raw(stn, code, 2)
                if t:
                    temps[code] = (t[-1][1], f"{(now - t[-1][0]).total_seconds() / 3600:.1f}h")
            except Exception:
                pass
        flag = "  <-- PUBLISHED VALUE WRONG" if rlast != plast else ""
        print(f"{river['name'][:28]:28s} {stn:8s} {age:>6s} {str(rlast):>9s} {str(plast):>9s} "
              f"{dropped:5d}  {temps or '-'}{flag}")

    print("\n=== alternative gauges for reach mismatches ===")
    for term in ("STAVE", "MAMQUAM", "ALOUETTE", "KANAKA"):
        try:
            r = requests.get(STATIONS, params={"PROV_TERR_STATE_LOC": "BC", "f": "json",
                                               "limit": 10000}, headers=UA, timeout=120)
            r.raise_for_status()
            for f in r.json().get("features", []):
                p = f["properties"]
                if term in (p.get("STATION_NAME") or ""):
                    print(f"  {p['STATION_NUMBER']}  {p.get('STATUS_EN', ''):12s} "
                          f"rt={p.get('REAL_TIME')}  {p['STATION_NAME']}")
        except Exception as e:
            print(f"  {term}: station search FAILED ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
