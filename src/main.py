"""Entry point: check every river, update the dashboard, send alerts.

Run:
    python -m src.main                 # normal run
    python -m src.main --no-notify     # skip sending (dashboard only)
    python -m src.main --force-notify  # notify all alertable, ignore state

Config lives in config/rivers.yaml. Notification channels are configured via
environment variables (see src/notify.py). Designed to be run on a schedule
(cron / GitHub Actions).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import analyze, dashboard, notify, state
from .sources import StationData, fetch_station
from .weather import RainOutlook, fetch_rain

CONFIG = Path("config/rivers.yaml")
DASHBOARD_OUT = Path("docs/index.html")


def load_config() -> dict:
    with CONFIG.open() as f:
        return yaml.safe_load(f)


def check_river(river: dict, defaults: dict):
    """Fetch + assess one river. Returns (Assessment, StationData, RainOutlook)."""
    try:
        data = fetch_station(river["station"], prov=river.get("prov", "BC"))
    except Exception as e:
        print(f"[warn] {river['name']}: level fetch failed: {e}")
        data = StationData(station=river["station"])

    rain: RainOutlook | None = None
    if river.get("lat") is not None and river.get("lon") is not None:
        rain = fetch_rain(river["lat"], river["lon"])

    assessment = analyze.assess(river, data, rain, defaults)
    return assessment, data, rain


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check BC salmon river levels.")
    parser.add_argument("--no-notify", action="store_true", help="don't send alerts")
    parser.add_argument("--force-notify", action="store_true", help="alert all alertable, ignore state")
    args = parser.parse_args(argv)

    cfg = load_config()
    defaults = cfg.get("defaults", {})
    rivers = cfg.get("rivers", [])
    if not rivers:
        print("No rivers configured in config/rivers.yaml")
        return 1

    results = []
    for river in rivers:
        a, data, rain = check_river(river, defaults)
        print(f"{a.emoji} {a.river}: {a.verdict} — {a.headline}")
        results.append((a, data, rain))

    assessments = [a for a, _, _ in results]

    # Dashboard
    generated = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    DASHBOARD_OUT.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_OUT.write_text(dashboard.render(results, generated))
    print(f"[dashboard] wrote {DASHBOARD_OUT}")

    # Alerts (only on change, unless forced)
    if not args.no_notify:
        previous = {} if args.force_notify else state.load()
        to_alert = (
            [a for a in assessments if a.is_alertable]
            if args.force_notify
            else state.newly_alertable(assessments, previous)
        )
        if to_alert:
            notify.send(to_alert)
        else:
            print("[notify] nothing new to alert on")
    state.save(assessments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
