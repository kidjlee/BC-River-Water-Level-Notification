# 🎣 BC River Water Level Notifier (for salmon fishing)

Get a notification when BC salmon rivers hit a good water level to fish — plus
a simple "next few days" outlook driven by the rain forecast. Complex data
(hydrometric gauges + weather), boiled down to one word per river: **GO**,
**GET READY**, **MARGINAL**, **TOO LOW**, or **BLOWN OUT**.

## How it works

```
ECCC water levels ──┐
                    ├─► analyze (zone + trend + rain) ─► verdict per river ─┬─► notification (email / phone / Discord)
Open-Meteo rain  ───┘                                                       └─► dashboard (docs/index.html)
```

1. **Data** — real-time water level for each river from Environment and Climate
   Change Canada (free, no key). Rain forecast from Open-Meteo (free, no key).
2. **Analyze** — where the level sits vs *your* thresholds, whether it's
   rising/falling, and how upcoming rain will move it. All plain rules you can
   read and tune in `src/analyze.py` — no black box.
3. **Notify** — pings you only when a river *newly* becomes fishable (no spam).
4. **Dashboard** — a web page showing every river at a glance.

## Quick start

```bash
pip install -r requirements.txt

# 1. Confirm/adjust the station IDs for your rivers (needs internet):
python tools/discover_stations.py --search chilliwack
python tools/discover_stations.py --verify 08MH001 08MF005
#    Edit config/rivers.yaml with the right IDs, coords, and your thresholds.

# 2. Try a run (no alerts, just prints + builds the dashboard):
python -m src.main --no-notify
open docs/index.html

# 3. Turn on a notification channel (see .env.example), then:
python -m src.main --force-notify   # test an alert
```

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

Prefer your own machine? Add a cron entry instead:
`0 */3 * * * cd /path/to/repo && python -m src.main`

## What this does and doesn't do

- ✅ Live status, 24h trend, and a rain-driven 2–3 day outlook.
- ✅ "Best days ahead" from the precipitation forecast.
- ⚠️ **Time-of-day** patterns are only meaningful on snow/glacier-fed rivers
  (afternoon melt); rain-driven coastal rivers don't have a daily cycle, so the
  outlook focuses on *days*, not hours.
- ❌ Not a machine-learning level forecast (that's a possible future upgrade —
  train on historical level + weather). The current outlook is a transparent
  heuristic.
- ❗ **Not a safety tool.** Always judge conditions yourself on the bank.

## Project layout

```
config/rivers.yaml       your rivers + thresholds
src/sources.py           fetch ECCC water levels
src/weather.py           fetch rain forecast (Open-Meteo)
src/analyze.py           the rules → verdict + outlook
src/notify.py            email / ntfy / Discord
src/dashboard.py         generate docs/index.html
src/state.py             only-alert-on-change
src/main.py              orchestrator (run this)
tools/discover_stations.py   find/verify station IDs
.github/workflows/check.yml  free scheduled runs
```

## Data sources

- Water level & flow: [Environment and Climate Change Canada — Water Office](https://wateroffice.ec.gc.ca) via the [MSC Datamart](https://eccc-msc.github.io/open-data/msc-data/obs_hydrometric/readme_hydrometric-datamart_en/) and [GeoMet OGC API](https://api.weather.gc.ca/collections/hydrometric-realtime).
- Rain forecast: [Open-Meteo](https://open-meteo.com).
