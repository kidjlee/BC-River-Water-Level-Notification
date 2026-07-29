"""Cache ~1 year of daily observed levels/flows per river for the history page.

The forecast log only grows from today forward, but we can show a full year of
*actual* conditions right away by pulling ECCC's daily history. Writes
data/actuals_daily.json = {station: {metric, unit, series: [[date, value], ...]}}.

Heavy (one ECCC fetch per river) — run in the bootstrap / weekly train jobs, not
every hourly check. Run: python tools/backfill_actuals.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
OUT = ROOT / "data/actuals_daily.json"
DAYS = 366


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    out = {}
    for river in cfg.get("rivers", []):
        metric = river.get("metric", "level")
        try:
            dates, values = fetch_daily(river["station"], metric)
        except Exception as e:
            print(f"{river['name']}: FAILED ({e})")
            continue
        series = list(zip(dates, values))[-DAYS:]
        rnd = 3 if metric != "flow" else 0
        out[river["station"]] = {
            "metric": metric, "unit": "cms" if metric == "flow" else "m",
            "series": [[d, round(float(v), rnd)] for d, v in series],
        }
        print(f"{river['name']}: {len(series)} days")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
    print(f"\nWrote {OUT} ({len(out)} rivers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
