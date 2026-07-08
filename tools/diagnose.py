"""Judge whether each river's calibration can be trusted.

Percentile calibration is only as good as the gauge. This reports, per river:
  * the month's historical spread (min / p10 / p50 / p90 / max),
  * the calibrated good/blown band and how wide it is vs that spread,
  * the typical INTRA-DAY swing from live data (exposes tidal gauges),
and assigns a quality label:

  OK      - band sits sensibly inside a gauge that moves like a river
  TIDAL   - intra-day swing rivals/exceeds the whole band (tide, not fishability)
  FLAT    - almost no variation (dam-regulated / stale) -> verdicts meaningless
  SPARSE  - too little history this month to trust

Writes config/diagnostics.json so the app can flag untrustworthy gauges, and
prints a table. Run on a machine/CI with internet: python tools/diagnose.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402
from src.sources import fetch_station          # noqa: E402
from src.analyze import BC_TZ                   # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
MONTHLY = ROOT / "config/thresholds_monthly.json"
OUT = ROOT / "config/diagnostics.json"


def intra_day_swing(station: str, metric: str) -> float | None:
    """Mean daily (max-min) over the last few days of live data."""
    try:
        data = fetch_station(station, hours_back=120)
    except Exception:
        return None
    by_day: dict[str, list[float]] = defaultdict(list)
    for ts, v in data.series(metric):
        by_day[ts.astimezone(BC_TZ).date().isoformat()].append(v)
    swings = [max(vs) - min(vs) for vs in by_day.values() if len(vs) >= 4]
    return float(np.mean(swings)) if swings else None


def diagnose(river: dict, month: int, monthly: dict) -> dict:
    station, metric = river["station"], river.get("metric", "level")
    dates, values = fetch_daily(station, metric)
    mvals = [v for d, v in zip(dates, values) if int(d[5:7]) == month]
    if len(mvals) < 60:
        return {"quality": "SPARSE", "note": f"only {len(mvals)} days of history for this month"}

    arr = np.asarray(mvals)
    lo, p10, p50, p90, hi = (float(x) for x in np.percentile(arr, [0, 10, 50, 90, 100]))
    rng = (hi - lo) or 1e-9
    band = monthly.get(station, {}).get(str(month))
    band_w = (band[2] - band[0]) if band else None
    swing = intra_day_swing(station, metric)

    quality, note = "OK", "band sits inside a normally-varying gauge"
    if band_w is not None and rng > 0 and band_w / rng < 0.03:
        quality, note = "FLAT", "almost no seasonal variation (regulated/stale?)"
    if swing is not None and band_w and band_w > 0 and swing / band_w > 0.8:
        quality = "TIDAL"
        note = f"intra-day swing {swing:.2f} rivals the whole {band_w:.2f} band (tidal)"
    return {
        "quality": quality, "note": note,
        "month_min": round(lo, 3), "p10": round(p10, 3), "median": round(p50, 3),
        "p90": round(p90, 3), "month_max": round(hi, 3),
        "band": band, "band_width": round(band_w, 3) if band_w else None,
        "intra_day_swing": round(swing, 3) if swing is not None else None,
    }


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    monthly = json.loads(MONTHLY.read_text()) if MONTHLY.exists() else {}
    month = datetime.now(timezone.utc).astimezone(BC_TZ).month
    out = {}
    print(f"Calibration diagnostics for month {month}:\n")
    print(f"{'river':26} {'qual':7} {'median':>8} {'band':>18} {'swing':>7}  note")
    for river in cfg.get("rivers", []):
        try:
            d = diagnose(river, month, monthly)
        except Exception as e:
            print(f"{river['name'][:26]:26} ERROR   {e}")
            continue
        out[river["station"]] = d
        band = d.get("band")
        bstr = f"{band[0]}-{band[1]}/{band[2]}" if band else "-"
        print(f"{river['name'][:26]:26} {d['quality']:7} {str(d.get('median','-')):>8} "
              f"{bstr:>18} {str(d.get('intra_day_swing','-')):>7}  {d['note']}")
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    flagged = [s for s, d in out.items() if d["quality"] != "OK"]
    print(f"\nWrote {OUT}. Flagged (not OK): {len(flagged)} -> {flagged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
