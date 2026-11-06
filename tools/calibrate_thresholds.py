"""Set data-driven thresholds from each station's own history.

For each river, pull decades of daily records, keep the salmon-season months,
and derive:
    good_low  = 25th percentile   good_high = 60th percentile   blown_out = 85th

    python tools/calibrate_thresholds.py                 # print suggestions
    python tools/calibrate_thresholds.py --write         # update config in place
    python tools/calibrate_thresholds.py --station 08MF005

Percentiles are tunable with --low/--high/--blown. `--write` edits only the
numeric threshold lines (and flips `verified: true`), preserving comments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eccc_history import fetch_daily  # noqa: E402
from datum import fit_rating, usable  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.wateroffice import fetch_daily_means  # noqa: E402

CONFIG = Path("config/rivers.yaml")
MONTHLY_OUT = Path("config/thresholds_monthly.json")
ACTUALS = Path("data/actuals_daily.json")
MIN_MONTH_SAMPLES = 25   # need this many days-in-month across history to trust it
# Only the most recent years count. Several rivers here are dam-regulated, and
# their release rules changed (Coquitlam and Alouette gained higher minimum
# flows under BC Hydro water-use plans in the 2000s), so 60 years of history
# mixes how the river used to be run with how it's run now. 15 years is still
# ~450 days per calendar month — plenty for percentiles.
CAL_YEARS = 15


def _recent_only(dates, values):
    cutoff = (dt.date.today() - dt.timedelta(days=365 * CAL_YEARS)).isoformat()
    keep = [(d, v) for d, v in zip(dates, values) if d >= cutoff]
    return [d for d, _ in keep], [v for _, v in keep]


def _from_actuals(station: str):
    """(dates, values) from the backfilled year, for when ECCC is unreachable."""
    try:
        series = json.loads(ACTUALS.read_text()).get(station, {}).get("series", [])
    except (OSError, json.JSONDecodeError):
        return [], []
    pairs = [(d, v) for d, v in series if v is not None]
    return [d for d, _ in pairs], [v for _, v in pairs]


def _recent_pairs(station: str):
    """Last year of daily-mean level and discharge, on today's datum."""
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=365)
    levels = fetch_daily_means(station, "level", start, end)
    try:
        flows = fetch_daily_means(station, "flow", start, end)
    except Exception:
        flows = {}
    return levels, flows


def history(river: dict):
    """Daily history to calibrate on, in the units AND datum shown today.

    Flow rivers: decades of archived discharge (no datum to drift).

    Level rivers: archived *level* can't be trusted across decades because
    gauge datums get re-surveyed — Harrison's archive mixes ~1 m and ~6-9 m
    readings, which put its "good" band 5 m below the real river. Instead we
    take archived *discharge* and map it through the rating learned from the
    last year of paired readings (see tools/datum.py). If the station has no
    discharge, or its level doesn't follow discharge (tidal, lake-backwatered),
    we use the last year of level alone: shorter, but datum-consistent by
    construction. If Water Office is unreachable, the stored chart history.
    """
    station, metric = river["station"], river.get("metric", "level")
    if metric == "flow":
        try:
            dates, values = _recent_only(*fetch_daily(station, "flow"))
            if values:
                return dates, values, "eccc discharge archive"
        except Exception as e:
            print(f"  [{station}] ECCC archive unavailable ({type(e).__name__})")
        dates, values = _from_actuals(station)
        return dates, values, "stored year"

    try:
        levels, flows = _recent_pairs(station)
    except Exception as e:
        print(f"  [{station}] Water Office unavailable ({type(e).__name__}); using stored year")
        dates, values = _from_actuals(station)
        return dates, values, "stored year"

    rating = fit_rating(levels, flows)
    if usable(rating):
        try:
            qd, qv = _recent_only(*fetch_daily(station, "flow"))
        except Exception as e:
            qd, qv = [], []
            print(f"  [{station}] ECCC discharge archive unavailable ({type(e).__name__})")
        if len(qv) >= 3 * 365:
            f, scatter = rating
            hv = [round(float(x), 3) for x in f(qv)]
            return list(qd), hv, f"{len(qv) // 365}y discharge via today's rating (scatter {scatter:.3f})"
    elif rating is not None:
        print(f"  [{station}] level doesn't follow discharge (scatter {rating[1]:.2f}); "
              f"recent year only")

    days = sorted(levels)
    return days, [levels[d] for d in days], "recent year of level"


def suggest(river, low_q, high_q, blown_q):
    dates, values, source = history(river)
    if not values:
        return None
    months = set(river.get("season_months", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]))
    seasonal = [v for d, v in zip(dates, values) if int(d[5:7]) in months]
    sample = seasonal if len(seasonal) >= 30 else values
    arr = np.asarray(sample)
    gl, gh, bl = np.percentile(arr, [low_q, high_q, blown_q])
    rnd = (lambda x: round(float(x), 2)) if river.get("metric") != "flow" else (lambda x: round(float(x), -1))
    return dict(good_low=rnd(gl), good_high=rnd(gh), blown_out=rnd(bl), n=len(sample),
                n_season=len(seasonal), source=source)


def monthly_table(river, low_q, high_q, blown_q) -> dict[str, list[float]]:
    """Percentile thresholds per calendar month, from that month's own history."""
    dates, values, source = history(river)
    print(f"  [{river['station']}] calibrating on: {source}, {len(values)} days")
    rnd = (lambda x: round(float(x), 2)) if river.get("metric") != "flow" else (lambda x: round(float(x), -1))
    by_month: dict[int, list[float]] = {}
    for d, v in zip(dates, values):
        by_month.setdefault(int(d[5:7]), []).append(v)
    table = {}
    for m, vals in by_month.items():
        if len(vals) < MIN_MONTH_SAMPLES:
            continue
        gl, gh, bl = (rnd(x) for x in np.percentile(vals, [low_q, high_q, blown_q]))
        if gl < gh < bl:   # keep only sane, monotonic bands
            table[str(m)] = [gl, gh, bl]
    return table


def _rewrite(text: str, station: str, s: dict) -> str:
    """Replace threshold values within the river block that has this station."""
    blocks = re.split(r"(?m)^(?=  - name:)", text)
    for i, b in enumerate(blocks):
        if f'station: "{station}"' in b or f"station: {station}" in b:
            for key in ("good_low", "good_high", "blown_out"):
                b = re.sub(rf"(?m)^(\s*{key}:\s*).*$", rf"\g<1>{s[key]}", b)
            b = re.sub(r"(?m)^(\s*verified:\s*).*$", r"\g<1>true", b)
            blocks[i] = b
    return "".join(blocks)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="update config/rivers.yaml in place")
    ap.add_argument("--station", help="only this station number")
    ap.add_argument("--unverified-only", action="store_true",
                    help="only calibrate rivers with verified: false (keeps curated thresholds)")
    ap.add_argument("--monthly", action="store_true",
                    help="write per-month thresholds for every river to thresholds_monthly.json")
    ap.add_argument("--low", type=float, default=25)
    ap.add_argument("--high", type=float, default=60)
    ap.add_argument("--blown", type=float, default=85)
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(CONFIG.read_text())
    text = CONFIG.read_text()

    if args.monthly:
        table = {}
        for river in cfg.get("rivers", []):
            if args.station and river["station"] != args.station:
                continue
            if river.get("manual"):   # hand-set thresholds — never auto-calibrate
                print(f"{river['name']}: manual — skipped")
                continue
            try:
                mt = monthly_table(river, args.low, args.high, args.blown)
            except Exception as e:
                print(f"{river['name']}: FAILED ({e})")
                continue
            if mt:
                table[river["station"]] = mt
                print(f"{river['name']} ({river['station']}): {len(mt)} months calibrated")
            else:
                print(f"{river['name']}: not enough monthly data")
        MONTHLY_OUT.write_text(json.dumps(table, indent=2, sort_keys=True))
        print(f"\nWrote per-month thresholds for {len(table)} rivers to {MONTHLY_OUT}")
        return 0
    for river in cfg.get("rivers", []):
        if args.station and river["station"] != args.station:
            continue
        if args.unverified_only and river.get("verified"):
            continue
        if river.get("manual"):   # hand-set thresholds — never auto-calibrate
            print(f"{river['name']}: manual — skipped")
            continue
        try:
            s = suggest(river, args.low, args.high, args.blown)
        except Exception as e:
            print(f"{river['name']}: FAILED ({e})")
            continue
        if not s:
            print(f"{river['name']}: no data")
            continue
        unit = "cms" if river.get("metric") == "flow" else "m"
        print(f"\n{river['name']} ({river['station']}, {river.get('metric','level')}):")
        print(f"  season sample n={s['n_season']} (fallback n={s['n']})")
        print(f"  good_low={s['good_low']} {unit}  good_high={s['good_high']} {unit}  blown_out={s['blown_out']} {unit}")
        if args.write:
            text = _rewrite(text, river["station"], s)

    if args.write:
        CONFIG.write_text(text)
        print(f"\nWrote calibrated thresholds to {CONFIG}")
    else:
        print("\n(dry run — re-run with --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
