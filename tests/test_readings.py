"""Stale gauges aren't judged; water temperature flows through to the card.

Run: python -m pytest tests/
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import analyze
from src.sources import Reading, StationData

RIVER = {"name": "Test", "station": "X", "metric": "level", "good_low": 1.0,
         "good_high": 2.0, "blown_out": 3.0, "fed_by": "rain", "season_months": [11]}
DEFAULTS = {"rising_rate_caution_frac_per_h": 0.03}
NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def _data(end, hours=48, level=1.5, temp=None):
    d = StationData(station="X")
    for i in range(hours * 12):
        ts = end - timedelta(minutes=5 * (hours * 12 - 1 - i))
        t = (temp + 0.5 * i / (hours * 12)) if (temp is not None and ts.minute == 0) else None
        d.readings.append(Reading(ts, level, 1.0, t))
    return d


def test_fresh_reading_is_judged():
    a = analyze.assess(RIVER, _data(NOW - timedelta(minutes=10)), None, DEFAULTS, now=NOW)
    assert a.verdict == "GO"


def test_stale_reading_shown_but_not_judged():
    a = analyze.assess(RIVER, _data(NOW - timedelta(hours=30)), None, DEFAULTS, now=NOW)
    assert a.verdict == "NO_DATA"
    assert a.value == 1.5
    assert "30 h" in a.headline
    assert not a.is_alertable


def test_water_temperature_and_24h_change():
    a = analyze.assess(RIVER, _data(NOW - timedelta(minutes=10), temp=9.0), None, DEFAULTS, now=NOW)
    assert a.water_temp_c is not None and 9.0 <= a.water_temp_c <= 9.6
    assert a.temp_change_24h is not None and 0.1 <= a.temp_change_24h <= 0.4


def test_no_thermometer_means_none():
    a = analyze.assess(RIVER, _data(NOW - timedelta(minutes=10)), None, DEFAULTS, now=NOW)
    assert a.water_temp_c is None and a.temp_change_24h is None
