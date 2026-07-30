"""Entry point: check every river, update the dashboard, send alerts.

Run:
    python -m src.main                 # live run (needs internet)
    python -m src.main --demo          # offline: synthetic data
    python -m src.main --no-notify     # skip sending (dashboard only)
    python -m src.main --force-notify  # notify all alertable, ignore state

Config: config/rivers.yaml. Channels: env vars (see src/notify.py). Meant to
run on a schedule (cron / GitHub Actions).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import analyze, dashboard, notify, state
from .sources import StationData, fetch_station
from .weather import RainOutlook, fetch_rain

CONFIG = Path("config/rivers.yaml")
DASHBOARD_OUT = Path("docs/index.html")
ACTUALS_FILE = Path("data/actuals_daily.json")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


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
        print(f"{a.emoji} {a.river}: {a.verdict} — {a.headline}")
        results.append((a, data, rain))

    assessments = [a for a, _, _ in results]
    generated = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    if args.demo:
        generated += " (DEMO — synthetic data)"

    # 1-year daily actuals power each river's interactive history chart.
    # We MERGE each run's live readings (daily-averaged) into the stored record,
    # so the recent stretch stays continuous and permanent — no longer at the
    # mercy of ECCC's ~weeks-late daily-mean finalization or the 30-day
    # real-time retention. The seasonal backfill seeds the older year.
    actuals = _load_json(ACTUALS_FILE)
    for a, data, _ in results:
        buckets: dict[str, list] = {}
        for ts, v in data.series(a.metric):
            buckets.setdefault(ts.date().isoformat(), []).append(v)
        if not buckets and not (actuals.get(a.station, {}).get("series")):
            continue
        entry = actuals.get(a.station) or {"metric": a.metric, "unit": a.unit, "series": []}
        merged = {d: v for d, v in entry.get("series", [])}
        for d, vs in buckets.items():
            merged[d] = round(sum(vs) / len(vs), 3)   # live daily mean wins for recent days
        # Trim by calendar date, not record count: counting records lets a
        # stale run of 2023 days pad the series to 366 and read as full
        # coverage while the last year is mostly hole.
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=365)).isoformat()
        entry["series"] = sorted(
            ([d, v] for d, v in merged.items() if d >= cutoff), key=lambda x: x[0]
        )
        entry["metric"], entry["unit"] = a.metric, a.unit
        actuals[a.station] = entry
    if not args.demo:
        ACTUALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTUALS_FILE.write_text(json.dumps(actuals, separators=(",", ":"), sort_keys=True))

    DASHBOARD_OUT.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_OUT.write_text(dashboard.render(results, generated, actuals))
    print(f"[dashboard] wrote {DASHBOARD_OUT}")

    if not args.no_notify:
        previous = {} if args.force_notify else state.load()
        to_alert = ([a for a in assessments if a.is_alertable] if args.force_notify
                    else state.newly_alertable(assessments, previous))
        # If any river opts in with `notify: true`, only push about those rivers.
        notify_stations = {r["station"] for r in rivers if r.get("notify")}
        if notify_stations:
            to_alert = [a for a in to_alert if a.station in notify_stations]
        notify.send(to_alert) if to_alert else print("[notify] nothing new to alert on")
    state.save(assessments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
