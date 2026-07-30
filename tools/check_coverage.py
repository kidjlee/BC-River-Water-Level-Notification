"""Audit data/actuals_daily.json: is the last year actually complete?

The charts slice one stored series into the 7d / 30d / 1yr windows, so a hole in
the series is a hole in all three views. This reports, per station and per
window, how many days are present out of how many expected, plus the largest
run of consecutive missing days.

Exit code is 1 if any *notify* river fails the thresholds below, so CI can gate
on the rivers that actually page us.

Run: python tools/check_coverage.py [--strict]
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTUALS = ROOT / "data/actuals_daily.json"
CONFIG = ROOT / "config/rivers.yaml"

WINDOWS = (("7d", 7), ("30d", 30), ("1yr", 366))
# A station passes if each window is at least this complete.
MIN_FRAC = {"7d": 0.85, "30d": 0.85, "1yr": 0.90}


def audit(series: list, today: dt.date) -> dict:
    """Per-window coverage stats for one station's [[date, value], ...]."""
    have = {dt.date.fromisoformat(d) for d, v in series if v is not None}
    out = {}
    for label, days in WINDOWS:
        start = today - dt.timedelta(days=days - 1)
        want = [start + dt.timedelta(days=i) for i in range(days)]
        present = [d for d in want if d in have]
        missing = [d for d in want if d not in have]
        # longest consecutive missing run
        longest, run, prev = 0, 0, None
        for d in missing:
            run = run + 1 if prev and (d - prev).days == 1 else 1
            longest, prev = max(longest, run), d
        out[label] = {
            "present": len(present),
            "expected": days,
            "frac": len(present) / days,
            "missing": len(missing),
            "longest_gap": longest,
            "first_missing": missing[0].isoformat() if missing else None,
        }
    return out


def main() -> int:
    strict = "--strict" in sys.argv
    if not ACTUALS.exists():
        print(f"{ACTUALS} missing — run tools/backfill_actuals.py first")
        return 1
    data = json.loads(ACTUALS.read_text())
    cfg = yaml.safe_load(CONFIG.read_text())
    rivers = {r["station"]: r for r in cfg.get("rivers", [])}
    today = dt.datetime.now(dt.timezone.utc).date()

    failures = []
    print(f"coverage as of {today} ({len(data)} stations)\n")
    for station in sorted(data):
        river = rivers.get(station, {})
        name = river.get("name", station)
        star = "*" if river.get("notify") else " "
        stats = audit(data[station].get("series", []), today)
        bits = " ".join(
            f"{lbl}={s['present']}/{s['expected']}"
            + (f"(gap{s['longest_gap']})" if s["longest_gap"] else "")
            for lbl, s in ((l, stats[l]) for l, _ in WINDOWS)
        )
        bad = [l for l, _ in WINDOWS if stats[l]["frac"] < MIN_FRAC[l]]
        flag = "FAIL" if bad else "ok"
        print(f"{star}{flag:>4}  {station}  {name[:28]:28s}  {bits}")
        if bad and river.get("notify"):
            failures.append((name, station, bad))

    print()
    if failures:
        print("notify rivers below threshold:")
        for name, station, bad in failures:
            print(f"  {name} ({station}): {', '.join(bad)}")
        return 1 if strict else 0
    print("all notify rivers meet coverage thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
