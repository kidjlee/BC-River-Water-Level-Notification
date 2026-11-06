"""Level thresholds must be expressed in today's gauge datum.

Regression for Harrison River, whose archive mixes an old datum (~1 m) with the
current one (~6-9 m): raw percentiles straddled both and put the "good" band
~5 m below the real river.

Run: python -m pytest tests/
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from datum import fit_rating, usable


def _rating(q):
    return 5.2 + 0.9 * np.log1p(q / 50)


def _history(rng):
    days = [dt.date(1995, 1, 1) + dt.timedelta(d) for d in range(30 * 365)]
    return np.array([120 + 90 * np.sin(2 * np.pi * (d.timetuple().tm_yday - 60) / 365)
                     + rng.gamma(2, 20) for d in days])


def _paired(h, q):
    return ({str(i): float(v) for i, v in enumerate(h)},
            {str(i): float(v) for i, v in enumerate(q)})


def test_datum_shift_recovered_through_discharge():
    rng = np.random.default_rng(0)
    q_hist = _history(rng)
    old_datum = np.where(np.arange(len(q_hist)) < 20 * 365, 5.0, 0.0)
    h_archive = _rating(q_hist) - old_datum
    rq = q_hist[-365:] * rng.uniform(0.9, 1.1, 365)
    levels, flows = _paired(_rating(rq) + rng.normal(0, 0.01, 365), rq)

    truth = np.percentile(_rating(q_hist), [25, 60, 85])
    naive = np.percentile(h_archive, [25, 60, 85])
    rating = fit_rating(levels, flows)
    fixed = np.percentile(rating[0](q_hist), [25, 60, 85])

    assert not np.allclose(naive, truth, atol=0.5)       # the bug, reproduced
    assert usable(rating)
    assert np.allclose(fixed, truth, atol=0.05)


def test_tidal_gauge_rating_refused():
    rng = np.random.default_rng(1)
    q = rng.uniform(100, 300, 365)
    h = 3.4 + 0.7 * np.sin(np.arange(365) * 1.3)
    assert not usable(fit_rating(*_paired(h, q)))


def test_too_few_pairs_refused():
    assert fit_rating({"a": 1.0}, {"a": 2.0}) is None
