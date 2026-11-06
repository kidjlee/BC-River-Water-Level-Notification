"""The glitch filter must drop sentinels but never a real river movement.

Regression for a bug where a genuine rain rise past ~25% of the 5-day median
was discarded, so a blown-out creek was published at its pre-flood level.

Run: python -m pytest tests/
"""
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sources import Reading, _reject_outliers

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _levels(vals):
    return [Reading(T0 + timedelta(minutes=5 * i), v, None) for i, v in enumerate(vals)]


def _filtered(vals):
    rs = _levels(vals)
    _reject_outliers(rs, "level_m")
    return [r.level_m for r in rs]


def _quiet(n=1100, centre=0.80, noise=0.003, seed=1):
    rnd = random.Random(seed)
    return [centre + rnd.uniform(-noise, noise) for _ in range(n)]


def test_real_flood_is_kept_and_latest_is_true():
    flood = _quiet() + [0.80 + 0.0125 * i for i in range(1, 73)]   # +0.9 m over 6 h
    out = _filtered(flood)
    assert all(v is not None for v in out)
    assert out[-1] == flood[-1]


def test_sentinel_mid_series_and_newest_are_removed():
    vals = _quiet()
    vals[500] = 16666.0
    out = _filtered(vals + [16666.0])
    assert out[500] is None and out[501] is not None
    assert out[-1] is None


def test_flow_river_sentinels_removed():
    rnd = random.Random(2)
    q = [3000 + rnd.uniform(-20, 20) for _ in range(600)]
    q[300] = 16666.0
    q.append(16666.0)
    rs = [Reading(T0 + timedelta(minutes=5 * i), None, v) for i, v in enumerate(q)]
    _reject_outliers(rs, "discharge_cms")
    assert rs[300].discharge_cms is None
    assert rs[-1].discharge_cms is None
    assert sum(r.discharge_cms is None for r in rs) == 2


def test_negative_removed():
    vals = _quiet()
    vals[10] = -1.0
    assert _filtered(vals)[10] is None


def test_quiet_dam_gauge_untouched():
    out = _filtered(_quiet(n=1400, centre=0.54, noise=0.01, seed=3))
    assert all(v is not None for v in out)


def test_tidal_gauge_untouched():
    tide = [3.4 + 0.7 * math.sin(2 * math.pi * i / (12.4 * 12)) for i in range(1440)]
    assert all(v is not None for v in _filtered(tide))
