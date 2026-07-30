"""Build ~1 year of daily observed levels/flows per river for the history charts.

Three sources, spliced worst-to-best so the best one wins each day:

  1. Water Office provisional (5-min -> daily mean), ~18 months back. Fills the
     long hole ECCC's own feeds leave.
  2. ECCC approved daily-mean. Authoritative, but its last non-null day lags
     weeks to ~19 months depending on the station.
  3. Whatever the hourly job already accumulated in the existing file.

The result is MERGED into data/actuals_daily.json rather than overwriting it —
the hourly runs accumulate live days into that same file, and a clobbering
backfill would throw them away every time it ran.

Writes {station: {metric, unit, series: [[date, value], ...]}}, trimmed to the
last 366 *days* (not the last 366 records, which let stale years masquerade as
coverage).

Heavy — one ECCC fetch plus one ~7 MB Water Office fetch per river. Run from
the bootstrap / weekly train jobs, not the hourly check.

Run: python tools/backfill_actuals.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402
from src.wateroffice import fetch_daily_means  # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
OUT = ROOT / "data/actuals_daily.json"
DAYS = 366


def _trim(series: dict[str, float], today: dt.date) -> list[list]:
    """Sorted [[date, value]] limited to the last DAYS calendar days."""
    cutoff = (today - dt.timedelta(days=DAYS - 1)).isoformat()
    return [[d, series[d]] for d in sorted(series) if d >= cutoff]


def _agreement(a: dict[str, float], b: dict[str, float]) -> tuple[int, float]:
    """Overlap count and mean absolute difference between two daily series.

    A big disagreement would mean the two sources aren't on the same datum and
    splicing them would draw a fake step in the chart.
    """
    shared = set(a) & set(b)
    if not shared:
        return 0, 0.0
    return len(shared), sum(abs(a[d] - b[d]) for d in shared) / len(shared)


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=DAYS - 1)

    out = json.loads(OUT.read_text()) if OUT.exists() else {}

    for river in cfg.get("rivers", []):
        station, name = river["station"], river["name"]
        metric = river.get("metric", "level")
        rnd = 3 if metric != "flow" else 0

        # 3. whatever we already have (hourly accumulation)
        merged: dict[str, float] = {
            d: v for d, v in (out.get(station, {}).get("series") or []) if v is not None
        }
        kept = len(merged)

        # 1. provisional first, so approved can overwrite it
        prov: dict[str, float] = {}
        try:
            prov = fetch_daily_means(station, metric, start, today)
            merged.update(prov)
        except Exception as e:
            print(f"{name}: wateroffice FAILED ({e})")

        # 2. approved daily-mean wins wherever it exists
        appr: dict[str, float] = {}
        try:
            dates, values = fetch_daily(station, metric)
            appr = {
                d: float(v)
                for d, v in zip(dates, values)
                if v is not None and d >= start.isoformat()
            }
            merged.update(appr)
        except Exception as e:
            print(f"{name}: daily-mean FAILED ({e})")

        if not merged:
            print(f"{name}: no data from any source — leaving as-is")
            continue

        series = [[d, round(v, rnd)] for d, v in _trim(merged, today)]
        out[station] = {
            "metric": metric,
            "unit": "cms" if metric == "flow" else "m",
            "series": series,
        }

        n_shared, mad = _agreement(appr, prov)
        note = f" agree={n_shared}d/±{mad:.3f}" if n_shared else ""
        print(
            f"{name}: {len(series)}/{DAYS} days "
            f"(kept {kept}, prov {len(prov)}, approved {len(appr)}){note}"
        )
        time.sleep(1)   # be polite to Water Office

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
    print(f"\nWrote {OUT} ({len(out)} rivers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
