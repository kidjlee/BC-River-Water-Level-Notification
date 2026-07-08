"""Train the per-station forecast models from real historical data.

For each river: pull daily level/flow history (ECCC) + daily precip history
(Open-Meteo archive) for the same dates, align them, and fit the ridge models
in src/forecast.py. Saves models/<station>.json and reports skill vs a
no-change baseline.

    python tools/train_forecast.py
    python tools/train_forecast.py --station 08MF005

Re-run periodically (e.g. monthly) to keep models current. Commit models/ so
CI runs can load them.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402
from src import forecast                       # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_precip(lat, lon, start, end, timeout=90):
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "daily": "precipitation_sum", "timezone": "America/Vancouver",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    d = r.json().get("daily", {})
    return dict(zip(d.get("time", []), [x or 0.0 for x in d.get("precipitation_sum", [])]))


def train_river(river) -> str:
    dates, values = fetch_daily(river["station"], river.get("metric", "level"))
    if len(values) < 200:
        return f"{river['name']}: too little history (n={len(values)})"
    # cap to a recent window to keep the archive request reasonable (~15y)
    if len(dates) > 5500:
        dates, values = dates[-5500:], values[-5500:]
    precip = fetch_precip(river["lat"], river["lon"], dates[0], dates[-1])

    doys, vals, rain = [], [], []
    for d, v in zip(dates, values):
        doys.append(datetime.fromisoformat(d).timetuple().tm_yday)
        vals.append(v)
        rain.append(precip.get(d, 0.0))

    models = forecast.train_from_daily(doys, vals, rain)
    if not models:
        return f"{river['name']}: not enough aligned samples"
    forecast.save_models(river["station"], models)
    skills = ", ".join(f"{k}d {m.skill:+.0%}" for k, m in sorted(models.items()))
    return f"{river['name']}: trained n={len(vals)} | skill vs baseline: {skills}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", help="only this station number")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text())
    for river in cfg.get("rivers", []):
        if args.station and river["station"] != args.station:
            continue
        try:
            print(train_river(river))
        except Exception as e:
            print(f"{river['name']}: FAILED ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
