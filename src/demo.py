"""Deterministic synthetic data so the whole pipeline can be tested offline.

`python -m src.main --demo` uses this instead of the network: it fabricates a
plausible history for each river (so the ML model has something real to learn),
a live 2-day hourly series (with a daily melt cycle for snow/glacier rivers),
and a rain past/forecast. The generating process is autoregressive with a
rain response and a seasonal term, so the ridge model can genuinely fit it —
this exercises train -> save -> load -> predict -> dashboard end to end.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from .sources import Reading, StationData
from .weather import RainOutlook

BC_TZ = ZoneInfo("America/Vancouver")

# Per-river "recent situation" so the demo shows a spread of verdicts.
#   base_frac : where the baseline sits in the good zone (0=good_low, 1=good_high)
#   storm     : mm on the last 3 observed days (magnitude of a recent bump)
#   peak_age_h: hours ago the bump peaked (large => already receding => falling)
#   forecast  : mm/day for the next 4 days
MODES = {
    # Vedder: recent freshet, now dropping back into shape -> GO/GET_READY
    "08MH001": dict(base_frac=0.85, storm=[26, 14, 5], peak_age_h=34, forecast=[2, 1, 0, 0]),
    # Fraser: sitting high in freshet, steady, more rain coming -> BLOWN
    "08MF005": dict(base_frac=1.02, storm=[10, 22, 26], peak_age_h=6, forecast=[30, 18, 8, 4]),
    # Cowichan: low and dry -> TOO_LOW
    "08HA011": dict(base_frac=-0.18, storm=[0, 1, 0], peak_age_h=6, forecast=[0, 2, 1, 0]),
    # Squamish: mid-zone, glacial daily cycle -> GO + best-time
    "08GA022": dict(base_frac=0.62, storm=[4, 5, 3], peak_age_h=6, forecast=[3, 2, 1, 0]),
    # Skeena: high edge, rising -> MARGINAL
    "08EF001": dict(base_frac=0.82, storm=[14, 18, 16], peak_age_h=4, forecast=[16, 10, 6, 2]),
    # Capilano: in the zone, dropping after rain -> GO
    "08GA010": dict(base_frac=0.55, storm=[20, 10, 3], peak_age_h=30, forecast=[1, 0, 2, 1]),
    # Coquitlam: low, rain coming -> GET_READY
    "08MH002": dict(base_frac=0.15, storm=[2, 1, 0], peak_age_h=6, forecast=[14, 20, 8, 3]),
}
_AMP = {"glacier": 0.07, "snow": 0.035, "mixed": 0.025, "rain": 0.0}


def _rng(station: str) -> np.random.Generator:
    return np.random.default_rng(abs(hash(station)) % (2**32))


def historical(river: dict, days: int = 1400):
    """Return (doy_list, values, rain_daily) — a learnable synthetic record."""
    rng = _rng(river["station"])
    lo, hi, blown = river["good_low"], river["good_high"], river["blown_out"]
    base = lo + 0.45 * (hi - lo)
    scale = (hi - lo)
    values, rain_daily, doys = [], [], []
    v = base
    start = datetime(2021, 1, 1, tzinfo=BC_TZ)
    for i in range(days):
        d = start + timedelta(days=i)
        doy = d.timetuple().tm_yday
        # seasonal: higher in spring freshet (~day 150), lower late summer
        seasonal = 0.18 * scale * math.sin(2 * math.pi * (doy - 60) / 365.0)
        # rain: mostly dry with occasional storms
        rain = float(max(0.0, rng.gamma(0.35, 12.0) - 3.0))
        rain_prev = rain_daily[-1] if rain_daily else 0.0
        # autoregressive recession + rain response (lagged) + seasonal
        v = base + 0.88 * (v - base) + 0.010 * scale * rain + 0.014 * scale * rain_prev \
            + seasonal * 0.05 + rng.normal(0, 0.02 * scale)
        v = max(v, lo * 0.4)
        values.append(v)
        rain_daily.append(rain)
        doys.append(doy)
    return doys, values, rain_daily


def live(river: dict, hours: int = 48) -> StationData:
    """2-day hourly series ending 'now', with a diurnal cycle for melt rivers."""
    rng = _rng(river["station"] + "live")
    lo, hi = river["good_low"], river["good_high"]
    width = hi - lo
    mode = MODES.get(river["station"], dict(base_frac=0.6, storm=[0, 0, 0], peak_age_h=6))
    daily = lo + mode["base_frac"] * width
    storm_total = sum(mode.get("storm", []))
    # bump magnitude scales with the good-zone width, capped, so flow & level behave alike
    bump_mag = width * min(0.9, 0.014 * storm_total)
    peak_age = mode.get("peak_age_h", 6)
    amp = _AMP.get(river.get("fed_by", "rain"), 0.0)
    now = datetime.now(timezone.utc)
    readings = []
    for h in range(hours):
        ts = now - timedelta(hours=hours - 1 - h)
        age = hours - 1 - h                          # hours before now (0 = latest)
        bump = bump_mag * math.exp(-abs(age - peak_age) / 18.0)  # storm peaked `peak_age` h ago
        local = ts.astimezone(BC_TZ).hour + ts.astimezone(BC_TZ).minute / 60.0
        diurnal = amp * daily * math.sin(2 * math.pi * (local - 9) / 24.0)  # peak ~15:00
        val = daily + bump + diurnal + rng.normal(0, 0.005 * width)
        if river.get("metric") == "flow":
            readings.append(Reading(ts, level_m=None, discharge_cms=round(max(val, 0.0), 1)))
        else:
            readings.append(Reading(ts, level_m=round(max(val, 0.0), 3), discharge_cms=None))
    return StationData(station=river["station"], readings=readings)


def rain_outlook(river: dict) -> RainOutlook:
    mode = MODES.get(river["station"], dict(storm=[0, 0, 0], forecast=[0, 0, 0, 0]))
    past = [float(x) for x in mode.get("storm", [0, 0, 0])]
    fut = [float(x) for x in mode.get("forecast", [0, 0, 0, 0])]
    # cheap hourly proxy for next_24/72 (spread each day's mm across 24h implicitly)
    next_24 = round(fut[0] if fut else 0.0, 1)
    next_72 = round(sum(fut[:3]), 1)
    now = datetime.now(BC_TZ)
    dates = [(now + timedelta(days=i)).date().isoformat() for i in range(len(fut))]
    return RainOutlook(next_24h_mm=next_24, next_72h_mm=next_72, daily_mm=fut,
                       past_daily_mm=past, daily_dates=dates)
