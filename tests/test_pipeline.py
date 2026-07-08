"""Offline tests for the analysis + forecast pipeline (no network).

Run: python -m pytest tests/  (or: python tests/test_pipeline.py)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import analyze, forecast, demo
from src.sources import Reading, StationData
from src.weather import RainOutlook

DEFAULTS = {"rising_rate_caution_frac_per_h": 0.03}


def _make(levels, metric="level"):
    now = datetime.now(timezone.utc)
    n = len(levels)
    rs = []
    for i, v in enumerate(levels):
        ts = now - timedelta(hours=n - 1 - i)
        rs.append(Reading(ts, level_m=(v if metric == "level" else None),
                          discharge_cms=(v if metric == "flow" else None)))
    return StationData("T", rs)


def test_verdicts_across_zones():
    river = dict(name="R", station="T", metric="level", good_low=1.2, good_high=2.1, blown_out=2.6)
    cases = {
        "GO": [1.5] * 48,
        "BLOWN_OUT": [3.0] * 48,
        "TOO_LOW": [0.8] * 48,
    }
    for expect, series in cases.items():
        a = analyze.assess(river, _make(series), None, DEFAULTS)
        assert a.verdict == expect, f"{expect}: got {a.verdict}"
    # rising from low -> GET_READY
    a = analyze.assess(river, _make([0.4 + 0.01 * i for i in range(48)]), None, DEFAULTS)
    assert a.verdict == "GET_READY", a.verdict
    print("verdicts across zones: OK")


def test_flow_metric():
    river = dict(name="F", station="T", metric="flow", good_low=2000, good_high=5000, blown_out=7000)
    a = analyze.assess(river, _make([4000] * 48, metric="flow"), None, DEFAULTS)
    assert a.verdict == "GO" and a.unit == "cms" and a.value == 4000
    print("flow metric: OK")


def test_forecast_beats_baseline():
    """Model trained on synthetic rain-driven history should beat persistence."""
    river = dict(station="TESTF", metric="level", good_low=1.0, good_high=2.0, blown_out=2.8)
    doys, values, rain = demo.historical(river, days=1200)
    models = forecast.train_from_daily(doys, values, rain)
    assert models, "no models trained"
    for k, m in models.items():
        assert m.skill > 0, f"horizon {k} skill={m.skill} not > 0"
    print(f"forecast skill (beats baseline): {[ (k, m.skill) for k,m in sorted(models.items()) ]}")


def test_best_time_snow_only():
    glac = dict(name="G", station="T", metric="level", fed_by="glacier",
                good_low=1.0, good_high=2.0, blown_out=2.8)
    rain = dict(glac, fed_by="rain")
    d = demo.live(dict(glac, good_low=1.0, good_high=2.0))
    ag = analyze.assess(glac, d, None, DEFAULTS)
    ar = analyze.assess(rain, d, None, DEFAULTS)
    assert ag.best_time is not None, "glacier river should have best_time"
    assert ar.best_time is None, "rain river should not have best_time"
    print(f"best time (glacier): {ag.best_time}")


def test_dedupe():
    from src.state import newly_alertable
    river = dict(name="R", station="T", metric="level", good_low=1.2, good_high=2.1, blown_out=2.6)
    a = analyze.assess(river, _make([1.5] * 48), None, DEFAULTS)
    assert newly_alertable([a], {}) == [a]              # new -> alert
    assert newly_alertable([a], {"T": "GO"}) == []      # unchanged -> suppressed
    print("dedupe: OK")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nALL TESTS PASSED")
