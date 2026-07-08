# 🎣 BC River Water Level Notifier (for salmon fishing)

Get a notification when BC salmon rivers hit a good water level to fish — plus
a simple "next few days" outlook driven by the rain forecast. Complex data
(hydrometric gauges + weather), boiled down to one word per river: **GO**,
**GET READY**, **MARGINAL**, **TOO LOW**, or **BLOWN OUT**.

## How it works

```
ECCC level/flow ──┐
Open-Meteo rain ──┼─► analyze (zone + trend + ML forecast + melt cycle) ─► verdict ─┬─► notify (email/phone/Discord)
per-station model ┘                                                                 └─► dashboard (docs/index.html)
```

1. **Data** — real-time water **level (m)** or **flow (cms)** per river from
   Environment and Climate Change Canada (free, no key). Rain (past + forecast)
   from Open-Meteo (free, no key).
2. **Analyze** — where the value sits vs *your* thresholds, the 24h trend, a
   **1-3 day ML forecast**, and for snow/glacier rivers the **best time of day**.
   Plain rules + a transparent model — no black box.
3. **Notify** — pings you only when a river *newly* becomes fishable (no spam).
4. **Dashboard** — a web page with a forecast chart, good-zone band, and outlook.

## Quick start

```bash
pip install -r requirements.txt

# 0. See it work immediately, offline (synthetic data, trains demo models):
python -m src.main --demo --no-notify
open docs/index.html

# 1. Confirm/adjust station IDs for your rivers (needs internet):
python tools/discover_stations.py --search chilliwack
python tools/discover_stations.py --verify 08MH001 08MF005

# 2. Set real, data-driven thresholds from each station's history:
python tools/calibrate_thresholds.py            # preview
python tools/calibrate_thresholds.py --write     # apply to config/rivers.yaml

# 3. Train the forecast models (per station, from real history):
python tools/train_forecast.py                   # writes models/<station>.json

# 4. Live run (builds the dashboard; add a channel from .env.example to alert):
python -m src.main --no-notify
python -m src.main --force-notify                # test an alert now
```

## The four analysis features

- **Real thresholds** — `tools/calibrate_thresholds.py` sets `good_low`/`good_high`/
  `blown_out` from percentiles of each station's own salmon-season history
  (P25/P60/P85 by default). Thresholds live in the metric that fits the river:
  **level (m)** for small rivers, **flow (cms)** for big ones like the Fraser.
- **Best time of day** — for `fed_by: snow`/`glacier` rivers, finds the daily
  low-water (clearest) window from the diurnal melt cycle, after detrending so a
  multi-day rise can't fake a cycle. Suppressed for rain-fed rivers (no cycle).
- **ML forecast** — `src/forecast.py` is a numpy ridge regression per station,
  predicting the level/flow **change 1-3 days out** from recent trend, observed
  rain, forecast rain, and season. `tools/train_forecast.py` trains it on decades
  of history; each model reports **skill vs a no-change baseline** (shown on the
  dashboard). Falls back to the rain heuristic if untrained.
- **Richer dashboard** — summary tiles, and per river a chart of recent values
  flowing into the forecast with the good-zone shaded, forecast chips, the
  best-time window, and a plain-language outlook. Light + dark.

## Testing

```bash
python tests/test_pipeline.py     # offline: verdicts, flow metric, forecast skill, best-time, dedupe
python -m src.main --demo         # full offline run with a realistic spread of conditions
```
`--demo` needs no network and is the fastest way to see everything working.
For a true live test, run steps 1-4 above from a machine with internet, or push
and let the GitHub Actions workflows run.

## Configure your rivers — `config/rivers.yaml`

Each river needs an ECCC `station` ID, `lat`/`lon` (for rain), and your
fishing thresholds in metres:

- `good_low` .. `good_high` — the "go fishing" zone
- `blown_out` — above this it's too high / dirty / unsafe

The starter list is a best guess (`verified: false`). **Run
`tools/discover_stations.py` to confirm the real IDs**, then set `verified: true`.
Tune the thresholds to the levels *you* find fishable — they're personal.

## Notifications — pick any (set env vars, see `.env.example`)

| Channel | How | Cost |
|---|---|---|
| 📱 **Phone push** | [ntfy.sh](https://ntfy.sh) app + a topic name → `NTFY_TOPIC` | free |
| ✉️ **Email** | SMTP (`SMTP_*`, `ALERT_EMAIL_TO`); Gmail needs an App Password | free |
| 💬 **Discord** | channel webhook → `DISCORD_WEBHOOK_URL` | free |

Leave the rest blank. With none set, runs just print to the console.

## Run it on a schedule (free)

`.github/workflows/check.yml` runs every 3 hours on GitHub Actions, updates the
dashboard, and sends alerts. Setup:

1. Push this repo to GitHub.
2. Repo **Settings → Secrets and variables → Actions** → add the env vars you
   use (e.g. `NTFY_TOPIC`).
3. Optional: **Settings → Pages** → deploy from `main` `/docs` to get a public
   live dashboard URL.

There's also `.github/workflows/train.yml` (weekly + manual) that retrains the
models and can recalibrate thresholds, committing the results.

Prefer your own machine? Add cron entries instead:
`0 */3 * * * cd /path/to/repo && python -m src.main`

## What this does and doesn't do

- ✅ Live status, 24h trend, a **1-3 day ML forecast** (with measured skill), and
  a rain-driven outlook.
- ✅ **Best time of day** on snow/glacier-fed rivers (afternoon melt); suppressed
  for rain-fed rivers, which have no daily cycle.
- ⚠️ The forecast is a per-station regression, not a physical hydrological model.
  It's honest about uncertainty (reports skill vs baseline) and only as good as
  the history it's trained on. Retrain periodically.
- ❗ **Not a safety tool.** Always judge conditions yourself on the bank.

## Project layout

```
config/rivers.yaml           your rivers, metric, thresholds, fed_by, season
src/sources.py               fetch ECCC level/flow
src/weather.py               fetch rain (past + forecast, Open-Meteo)
src/analyze.py               rules → verdict, best-time, forecast, outlook
src/forecast.py              ridge-regression forecast model (train/predict)
src/notify.py                email / ntfy / Discord
src/dashboard.py             generate docs/index.html (charts, tiles)
src/state.py                 only-alert-on-change
src/demo.py                  synthetic data for offline testing
src/main.py                  orchestrator (run this)
tools/discover_stations.py   find/verify station IDs
tools/calibrate_thresholds.py  data-driven thresholds from history
tools/train_forecast.py      train the forecast models
tests/test_pipeline.py       offline tests
.github/workflows/           check.yml (every 3h) + train.yml (weekly)
```

## Data sources

- Water level & flow: [Environment and Climate Change Canada — Water Office](https://wateroffice.ec.gc.ca) via the [MSC Datamart](https://eccc-msc.github.io/open-data/msc-data/obs_hydrometric/readme_hydrometric-datamart_en/) and [GeoMet OGC API](https://api.weather.gc.ca/collections/hydrometric-realtime).
- Rain forecast: [Open-Meteo](https://open-meteo.com).
