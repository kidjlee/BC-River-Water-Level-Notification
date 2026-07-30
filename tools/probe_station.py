"""Print a station's recent readings in the raw, so a gauge call can be checked.

tools/diagnose.py reduces a gauge to one word (OK / TIDAL / FLAT / SPARSE).
That's the right thing on the dashboard and the wrong thing when the call is
disputed — this prints the daily shape it was derived from: min, max, mean,
intra-day swing, and how many separate rises per day. Roughly two rises a day
is the tide's semi-diurnal signature; one or none is weather.

Run: python tools/probe_station.py 08MH002 [level|flow] [days]
"""
from __future__ import annotations

import datetime as dt
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.wateroffice import PARAM, URL, UA          # noqa: E402

import requests                                      # noqa: E402


def readings(station: str, metric: str, start: dt.date, end: dt.date):
    """[(datetime, value)] of provisional 5-minute readings."""
    resp = requests.get(
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
    resp.raise_for_status()
    out = []
    for line in resp.text.splitlines():
        parts = line.split(",")
        if len(parts) < 4 or not parts[1][:4].strip().isdigit():
            continue
        try:
            out.append((parts[1].strip(), float(parts[3])))
        except ValueError:
            continue
    return out


def rises(vals: list[float], min_amp: float) -> int:
    """Count sustained rise->fall turning points (tide gives ~2/day)."""
    peaks, direction = 0, 0
    last_turn = vals[0] if vals else 0.0
    for prev, cur in zip(vals, vals[1:]):
        if cur > prev and direction <= 0:
            if direction < 0 and abs(last_turn - prev) >= min_amp:
                pass
            direction, last_turn = 1, prev
        elif cur < prev and direction >= 0:
            if direction > 0 and abs(prev - last_turn) >= min_amp:
                peaks += 1
            direction, last_turn = -1, prev
    return peaks


def main() -> int:
    station = sys.argv[1] if len(sys.argv) > 1 else "08MH002"
    metric = sys.argv[2] if len(sys.argv) > 2 else "level"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days)

    data = readings(station, metric, start, end)
    print(f"{station} ({metric}) {start}..{end}: {len(data)} readings\n")
    if not data:
        print("no data")
        return 1

    by_day: dict[str, list[float]] = {}
    for stamp, v in data:
        by_day.setdefault(stamp[:10], []).append(v)

    all_vals = [v for _, v in data]
    swing_scale = (max(all_vals) - min(all_vals)) or 1.0
    print(f"{'date':12s} {'n':>4s} {'min':>9s} {'max':>9s} {'mean':>9s} {'swing':>8s} {'rises':>6s}")
    swings = []
    for day in sorted(by_day):
        vs = by_day[day]
        swing = max(vs) - min(vs)
        swings.append(swing)
        print(
            f"{day:12s} {len(vs):4d} {min(vs):9.3f} {max(vs):9.3f} "
            f"{statistics.fmean(vs):9.3f} {swing:8.3f} "
            f"{rises(vs, swing_scale * 0.08):6d}"
        )

    print(
        f"\noverall range {min(all_vals):.3f}..{max(all_vals):.3f}  "
        f"median intra-day swing {statistics.median(swings):.3f}"
    )
    print(f"last reading: {data[-1][0]} = {data[-1][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
