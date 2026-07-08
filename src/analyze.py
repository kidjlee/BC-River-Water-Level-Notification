"""Turn raw numbers into a simple fishing verdict, forecast, and outlook.

Transparent rules (not a black box) so you can tune every decision:

  * ZONE     - where the current value sits vs your good_low/good_high/blown_out
               (in metres of level, or cms of flow, per the river's `metric`).
  * TREND    - rising / falling / steady over ~24h.
  * VERDICT  - GO / GET_READY / MARGINAL / TOO_LOW / BLOWN_OUT / NO_DATA.
  * FORECAST - projected value + verdict for the next 1-3 days, from the ML
               model if trained (src/forecast.py), else a rain heuristic.
  * BEST TIME- for snow/glacier-fed rivers only: the daily low-water window
               (clearest, most fishable) from the diurnal cycle.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import forecast as fc
from .sources import StationData
from .weather import RainOutlook

VERDICT_ORDER = ["GO", "GET_READY", "MARGINAL", "TOO_LOW", "BLOWN_OUT", "NO_DATA"]
EMOJI = {"GO": "🟢", "GET_READY": "🟡", "MARGINAL": "🟠", "TOO_LOW": "🔵", "BLOWN_OUT": "🔴", "NO_DATA": "⚪"}
BC_TZ = ZoneInfo("America/Vancouver")
MELT_FED = {"snow", "glacier"}   # rivers with a real daily melt cycle; rain/mixed don't
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _load_monthly() -> dict:
    """Per-month thresholds by station (from calibrate_thresholds.py --monthly)."""
    p = Path("config/thresholds_monthly.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


_MONTHLY = _load_monthly()


def _load_diag() -> dict:
    """Gauge-quality flags from tools/diagnose.py (OK / TIDAL / FLAT / SPARSE)."""
    p = Path("config/diagnostics.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


_DIAG = _load_diag()


def effective_thresholds(river: dict, month: int) -> tuple[float, float, float, str]:
    """Zones to use now: the station's calibrated thresholds for THIS month if
    available (so a 'normal' September level isn't judged by November's water),
    else the flat config values. Returns (good_low, good_high, blown_out, basis)."""
    mt = _MONTHLY.get(river["station"], {}).get(str(month))
    if mt and len(mt) == 3 and mt[0] < mt[1] < mt[2]:
        return mt[0], mt[1], mt[2], f"{_MONTH_ABBR[month]} normal"
    return river["good_low"], river["good_high"], river["blown_out"], ""


@dataclass
class DayForecast:
    day: int            # 1..3
    value: float
    verdict: str
    label: str          # "tomorrow", "in 2 days", ...


@dataclass
class Assessment:
    river: str
    station: str
    metric: str                 # "level" | "flow"
    unit: str                   # "m" | "cms"
    verdict: str
    value: float | None
    trend: str
    rate_per_h: float | None
    headline: str
    outlook: str
    zone: str
    updated: str | None
    best_time: str | None = None
    forecast: list[DayForecast] = field(default_factory=list)
    forecast_skill: float | None = None
    good_low: float | None = None
    good_high: float | None = None
    blown_out: float | None = None
    region: str = ""
    species: list = field(default_factory=list)
    in_season: bool = True
    threshold_basis: str = ""   # e.g. "Jul normal" when month-calibrated zones are used
    gauge_quality: str = "OK"   # OK / TIDAL / FLAT / SPARSE (from diagnose.py)
    gauge_note: str = ""

    @property
    def emoji(self) -> str:
        return EMOJI.get(self.verdict, "⚪")

    @property
    def is_alertable(self) -> bool:
        return self.verdict in ("GO", "GET_READY")


def _zone(value: float, gl: float, gh: float, bl: float) -> str:
    if value < gl:
        return "low"
    if value <= gh:
        return "good"
    if value <= bl:
        return "high"
    return "blown"


def _verdict_for_zone(zone: str, trend: str, rate: float | None, caution_rate: float) -> str:
    if zone == "blown":
        return "BLOWN_OUT"
    if zone == "high":
        return "GET_READY" if trend == "falling" else "MARGINAL"
    if zone == "good":
        if trend == "rising" and rate is not None and rate > caution_rate:
            return "MARGINAL"
        return "GO"
    return "GET_READY" if trend == "rising" else "TOO_LOW"


def _trend(data: StationData, metric: str) -> tuple[str, float | None]:
    latest = data.latest_metric(metric)
    if latest is None:
        return "unknown", None
    past = data.metric_at_or_before(latest[0] - timedelta(hours=24), metric)
    if past is None or past[0] == latest[0]:
        return "unknown", None
    hours = (latest[0] - past[0]).total_seconds() / 3600.0
    if hours <= 0:
        return "unknown", None
    rate = (latest[1] - past[1]) / hours
    zone_ref = abs(latest[1]) or 1.0
    if rate > 0.001 * zone_ref:
        return "rising", rate
    if rate < -0.001 * zone_ref:
        return "falling", rate
    return "steady", rate


def _delta_over_days(data: StationData, metric: str, days: int) -> float:
    latest = data.latest_metric(metric)
    if latest is None:
        return 0.0
    past = data.metric_at_or_before(latest[0] - timedelta(days=days), metric)
    return 0.0 if past is None else latest[1] - past[1]


def _best_time_of_day(data: StationData, metric: str, fed_by: str) -> str | None:
    """Find the daily low-water (clearest) window for melt-fed rivers.

    Detrends the series first (subtracts a centered ~24h rolling mean) so a
    multi-day rise/fall can't masquerade as a daily cycle, then averages the
    residual by local hour-of-day.
    """
    if fed_by not in MELT_FED:
        return None
    series = data.series(metric)
    if len(series) < 24:
        return None
    vals = [v for _, v in series]
    n = len(vals)
    half = 12
    residual_by_hour: dict[int, list[float]] = {}
    for i, (ts, v) in enumerate(series):
        window_vals = vals[max(0, i - half):min(n, i + half + 1)]
        trend = sum(window_vals) / len(window_vals)
        h = ts.astimezone(BC_TZ).hour
        residual_by_hour.setdefault(h, []).append(v - trend)
    if len(residual_by_hour) < 8:
        return None
    avg = {h: sum(vs) / len(vs) for h, vs in residual_by_hour.items()}
    lo_h = min(avg, key=avg.get)
    hi_h = max(avg, key=avg.get)
    mean_level = abs(sum(vals) / n) or 1.0
    amp = (avg[hi_h] - avg[lo_h]) / mean_level
    if amp < 0.03:   # <3% daily swing -> too weak/noisy to trust (rain/mixed rivers)
        return None

    start, end = (lo_h - 1) % 24, (lo_h + 2) % 24
    return (f"Daily low ~{start:02d}:00–{end:02d}:00 (clearest); peak ~{hi_h:02d}:00. "
            f"Fish the low window.")


def _rain_features(rain: RainOutlook | None) -> tuple[float, float, dict[int, float]]:
    if rain is None or not rain.available:
        return 0.0, 0.0, {}
    cum = {}
    running = 0.0
    for i, mm in enumerate(rain.daily_mm[:3], start=1):
        running += mm
        cum[i] = running
    return rain.past_24h_mm, rain.past_72h_mm, cum


def _labels(day: int) -> str:
    return {1: "tomorrow", 2: "in 2 days", 3: "in 3 days"}.get(day, f"in {day} days")


def assess(river: dict, data: StationData, rain: RainOutlook | None, defaults: dict,
           now: datetime | None = None) -> Assessment:
    now = now or datetime.now(timezone.utc)
    name, station = river["name"], river["station"]
    metric = river.get("metric", "level")
    unit = "cms" if metric == "flow" else "m"
    latest = data.latest_metric(metric)

    month = now.astimezone(BC_TZ).month
    season = river.get("season_months") or list(range(1, 13))
    gl, gh, bl, basis = effective_thresholds(river, month)
    base = dict(river=name, station=station, metric=metric, unit=unit,
                good_low=gl, good_high=gh, blown_out=bl,
                region=river.get("region", ""), species=river.get("species", []),
                in_season=(month in season), threshold_basis=basis,
                gauge_quality=_DIAG.get(station, {}).get("quality", "OK"),
                gauge_note=_DIAG.get(station, {}).get("note", ""))

    if latest is None:
        return Assessment(**base, verdict="NO_DATA", value=None, trend="unknown", rate_per_h=None,
                          headline="No recent data from the station.", outlook="", zone="low", updated=None)

    ts, value = latest
    zone = _zone(value, gl, gh, bl)
    trend, rate = _trend(data, metric)
    width = max(gh - gl, 1e-6)
    caution_rate = defaults.get("rising_rate_caution_frac_per_h", 0.03) * width
    verdict = _verdict_for_zone(zone, trend, rate, caution_rate)

    headline = _headline(verdict, value, unit, trend)
    best_time = _best_time_of_day(data, metric, river.get("fed_by", "rain"))

    # --- ML forecast (fall back to heuristic outlook) ----------------------
    day_forecasts: list[DayForecast] = []
    skill = None
    models = fc.load_models(station)
    if models:
        rp1, rp3, rcum = _rain_features(rain)
        d1 = _delta_over_days(data, metric, 1)
        d3 = _delta_over_days(data, metric, 3)
        doy = int(ts.astimezone(BC_TZ).timetuple().tm_yday)
        preds = fc.predict(models, value, d1, d3, rp1, rp3, rcum, doy)
        skill = round(sum(p.skill for p in preds) / len(preds), 2) if preds else None
        for p in preds:
            z = _zone(p.value, gl, gh, bl)
            v = _verdict_for_zone(z, "steady", None, caution_rate)
            day_forecasts.append(DayForecast(day=p.horizon_days, value=p.value, verdict=v, label=_labels(p.horizon_days)))

    outlook = _outlook(zone, trend, rain, day_forecasts, unit)
    return Assessment(**base, verdict=verdict, value=round(value, 3), trend=trend,
                      rate_per_h=(round(rate, 3) if rate is not None else None),
                      headline=headline, outlook=outlook, zone=zone, updated=ts.isoformat(),
                      best_time=best_time, forecast=day_forecasts, forecast_skill=skill)


def _headline(verdict: str, value: float, unit: str, trend: str) -> str:
    v = f"{value:.3f} m" if unit == "m" else f"{value:,.0f} cms"
    return {
        "BLOWN_OUT": f"{v} — too high / likely dirty. Sit this one out.",
        "GET_READY": (f"{v} and dropping — clearing into shape soon." if trend == "falling"
                      else f"{v} — rising toward the zone."),
        "MARGINAL": f"{v} — marginal; fishable spots but use caution.",
        "GO": (f"{v} — in the zone and dropping (prime). Good to fish. 🎣" if trend == "falling"
               else f"{v} — in the zone. Good to fish. 🎣"),
        "TOO_LOW": f"{v} — too low. Needs water.",
    }.get(verdict, v)


def _outlook(zone: str, trend: str, rain: RainOutlook | None,
             forecasts: list[DayForecast], unit: str) -> str:
    parts = []
    # ML forecast leads if present.
    if forecasts:
        go_days = [f.label for f in forecasts if f.verdict in ("GO", "GET_READY")]
        if go_days:
            parts.append("Model: fishable " + ", ".join(go_days) + ".")
        else:
            nxt = forecasts[0]
            v = f"{nxt.value:.2f} m" if unit == "m" else f"{nxt.value:,.0f} cms"
            parts.append(f"Model: ~{v} {nxt.label} ({nxt.verdict.replace('_', ' ').lower()}).")

    if rain is not None and rain.available:
        r72 = rain.next_72h_mm
        band = ("heavy rain" if r72 >= 40 else "moderate rain" if r72 >= 15
                else "light rain" if r72 >= 3 else "little/no rain")
        parts.append(f"Next 3 days: {band} ({r72:.0f} mm).")
        if zone == "low" and r72 >= 15:
            parts.append("Rain should push it up toward the zone.")
        elif zone == "good" and r72 >= 40:
            parts.append("Watch for a blow-out — fish before it spikes.")
        elif zone in ("high", "blown") and r72 < 3:
            parts.append("Dry spell should drop it back into shape.")
    elif not forecasts:
        parts.append("Forecast unavailable.")
    return " ".join(parts)
