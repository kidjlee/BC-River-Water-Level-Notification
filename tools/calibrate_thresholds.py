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
import re
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eccc_history import fetch_daily  # noqa: E402

CONFIG = Path("config/rivers.yaml")


def suggest(river, low_q, high_q, blown_q):
    dates, values = fetch_daily(river["station"], river.get("metric", "level"))
    if not values:
        return None
    months = set(river.get("season_months", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]))
    seasonal = [v for d, v in zip(dates, values) if int(d[5:7]) in months]
    sample = seasonal if len(seasonal) >= 30 else values
    arr = np.asarray(sample)
    gl, gh, bl = np.percentile(arr, [low_q, high_q, blown_q])
    rnd = (lambda x: round(float(x), 2)) if river.get("metric") != "flow" else (lambda x: round(float(x), -1))
    return dict(good_low=rnd(gl), good_high=rnd(gh), blown_out=rnd(bl), n=len(sample), n_season=len(seasonal))


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
    ap.add_argument("--low", type=float, default=25)
    ap.add_argument("--high", type=float, default=60)
    ap.add_argument("--blown", type=float, default=85)
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(CONFIG.read_text())
    text = CONFIG.read_text()
    for river in cfg.get("rivers", []):
        if args.station and river["station"] != args.station:
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
