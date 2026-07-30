"""Compare our two feeds against each other, and UTC vs Pacific day boundaries.

The dashboard's live number comes from ECCC's OGC `hydrometric-realtime`, while
the history now comes from Water Office. If those disagree — in value, in
timestamp, or in where a "day" starts — the chart and the Water Office station
page tell different stories for the same river.

Water Office serves UTC stamps but its report page renders Pacific, so a day
bucketed in UTC is a 17:00-17:00 Pacific window: the same date label covering
different water. This quantifies both effects.

Run: python tools/probe_conflict.py [station ...]
"""
from __future__ import annotations

import datetime as dt
import statistics
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.sources import fetch_station              # noqa: E402
from src.wateroffice import PARAM, URL, UA          # noqa: E402

import requests                                      # noqa: E402

BC = ZoneInfo("America/Vancouver")
DEFAULT = ["08MH002", "08MH001", "08GA031"]


def wateroffice_readings(station: str, metric: str, days: int):
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days)
    r = requests.get(
        URL,
        params={
            "stations[]": station,
            "parameters[]": PARAM.get(metric, 46),
            "start_date": f"{start.isoformat()} 00:00:00",
            "end_date": f"{end.isoformat()} 23:59:59",
        },
        headers=UA,
        timeout=180,
    )
    r.raise_for_status()
    out = {}
    for line in r.text.splitlines():
        p = line.split(",")
        if len(p) < 4 or not p[1][:4].strip().isdigit():
            continue
        try:
            out[p[1].strip().replace("Z", "+00:00")] = float(p[3])
        except ValueError:
            continue
    return out


def daily(pairs, tz) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for ts, v in pairs:
        buckets.setdefault(ts.astimezone(tz).date().isoformat(), []).append(v)
    return {d: statistics.fmean(vs) for d, vs in buckets.items()}


def main() -> int:
    stations = sys.argv[1:] or DEFAULT
    for station in stations:
        metric = "level"
        print(f"\n================ {station} ================")

        try:
            wo = wateroffice_readings(station, metric, 5)
        except Exception as e:
            print(f"  wateroffice FAILED ({e})")
            continue
        try:
            data = fetch_station(station, hours_back=120)
            ogc = data.series(metric)
        except Exception as e:
            print(f"  OGC realtime FAILED ({e})")
            ogc = []

        print(f"  wateroffice readings: {len(wo)}   OGC readings: {len(ogc)}")
        if wo:
            k = sorted(wo)[-1]
            print(f"  wateroffice latest: {k} = {wo[k]}")
        if ogc:
            print(f"  OGC         latest: {ogc[-1][0].isoformat()} = {ogc[-1][1]}")

        # value agreement on shared timestamps
        diffs, missing = [], 0
        for ts, v in ogc:
            key = ts.astimezone(dt.timezone.utc).isoformat()
            if key in wo:
                diffs.append(abs(wo[key] - v))
            else:
                missing += 1
        if diffs:
            print(
                f"  shared stamps: {len(diffs)}  max|diff|={max(diffs):.4f}  "
                f"mean|diff|={statistics.fmean(diffs):.4f}   OGC-only stamps: {missing}"
            )
        else:
            print(f"  no shared timestamps (OGC-only stamps: {missing})")

        # day-boundary effect, using the richer wateroffice feed
        pairs = [(dt.datetime.fromisoformat(k), v) for k, v in wo.items()]
        du, db = daily(pairs, dt.timezone.utc), daily(pairs, BC)
        print("  daily mean by day boundary:")
        for day in sorted(set(du) | set(db))[-6:]:
            a, b = du.get(day), db.get(day)
            delta = f"{abs(a - b):.4f}" if a is not None and b is not None else "-"
            print(
                f"    {day}  UTC={a if a is None else round(a, 4)!s:>9}  "
                f"Pacific={b if b is None else round(b, 4)!s:>9}  diff={delta}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
