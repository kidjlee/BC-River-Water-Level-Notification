"""Entry point: check every river, update the dashboard, send alerts.

Run:
    python -m src.main                 # live run (needs internet)
    python -m src.main --demo          # offline: synthetic data, trains models
    python -m src.main --no-notify     # skip sending (dashboard only)
    python -m src.main --force-notify  # notify all alertable, ignore state

Config: config/rivers.yaml. Channels: env vars (see src/notify.py). Meant to
run on a schedule (cron / GitHub Actions).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import analyze, dashboard, forecast, notify, state
from .sources import StationData, fetch_station
from .weather import RainOutlook, fetch_rain

CONFIG = Path("config/rivers.yaml")
DASHBOARD_OUT = Path("docs/index.html")


def load_config() -> dict:
    with CONFIG.open() as f:
        return yaml.safe_load(f)


def check_river_live(river: dict, defaults: dict):
    try:
        data = fetch_station(river["station"], prov=river.get("prov", "BC"))
    except Exception as e:
        print(f"[warn] {river['name']}: level fetch failed: {e}")
        data = StationData(station=river["station"])
    rain: RainOutlook | None = None
    if river.get("lat") is not None and river.get("lon") is not None:
        rain = fetch_rain(river["lat"], river["lon"])
    return analyze.assess(river, data, rain, defaults), data, rain


def check_river_demo(river: dict, defaults: dict):
    from . import demo
    # Train a model on synthetic history so the forecast path is exercised.
    doys, values, rain_daily = demo.historical(river)
    models = forecast.train_from_daily(doys, values, rain_daily)
    if models:
        forecast.save_models(river["station"], models)
    data = demo.live(river)
    rain = demo.rain_outlook(river)
    return analyze.assess(river, data, rain, defaults), data, rain


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check BC salmon river levels.")
    parser.add_argument("--demo", action="store_true", help="use synthetic data (offline)")
    parser.add_argument("--no-notify", action="store_true", help="don't send alerts")
    parser.add_argument("--force-notify", action="store_true", help="alert all alertable, ignore state")
    args = parser.parse_args(argv)

    cfg = load_config()
    defaults = cfg.get("defaults", {})
    rivers = cfg.get("rivers", [])
    if not rivers:
        print("No rivers configured in config/rivers.yaml")
        return 1

    check = check_river_demo if args.demo else check_river_live
    results = []
    for river in rivers:
        a, data, rain = check(river, defaults)
        skill = f" [model {a.forecast_skill:+.0%}]" if a.forecast_skill is not None else ""
        print(f"{a.emoji} {a.river}: {a.verdict} — {a.headline}{skill}")
        if a.best_time:
            print(f"     best time: {a.best_time}")
        results.append((a, data, rain))

    assessments = [a for a, _, _ in results]
    generated = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    if args.demo:
        generated += " (DEMO — synthetic data)"
    DASHBOARD_OUT.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_OUT.write_text(dashboard.render(results, generated))
    print(f"[dashboard] wrote {DASHBOARD_OUT}")

    if not args.no_notify:
        previous = {} if args.force_notify else state.load()
        to_alert = ([a for a in assessments if a.is_alertable] if args.force_notify
                    else state.newly_alertable(assessments, previous))
        notify.send(to_alert) if to_alert else print("[notify] nothing new to alert on")
    state.save(assessments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
