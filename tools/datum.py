"""Express decades of history in TODAY's gauge datum.

Water level is measured against a gauge datum, and ECCC re-surveys datums
from time to time. Harrison River is the clear case in this project: its
archive mixes readings around 1 m with current readings around 6-9 m, so
percentile thresholds straddled both populations and put the "good" band ~5 m
below where the river actually runs. Coquihalla shows a smaller ~0.15 m step.

Discharge (m^3/s) is physical flow — it doesn't move when a datum does. So:

  1. take decades of archived DISCHARGE for the station,
  2. learn the current level <-> discharge relationship (the rating) from the
     last year of paired daily means, which are on today's datum by definition,
  3. map the historic discharge through that rating to get a history of what
     the level *would read today* for those flows.

Percentiles of that series are long-history thresholds that line up with the
number on the Water Office page today. Where a station has no discharge, or its
level doesn't follow discharge (tidal or lake-backwatered reaches), the rating
is rejected and the caller should fall back to the recent year alone.
"""
from __future__ import annotations

import numpy as np

MIN_PAIRS = 120          # paired days needed to trust a rating
MAX_SCATTER = 0.10       # residual MAD / level spread above which we refuse


def fit_rating(levels: dict[str, float], flows: dict[str, float]):
    """Fit level = f(discharge) from paired daily means.

    Returns (f, scatter) where scatter is residual MAD over the level's 10-90%
    spread, or None if there aren't enough pairs. The curve is the binned
    median, forced non-decreasing (more water never reads lower), with linear
    ends fitted to the outer 15% of points so rare flows extrapolate instead of
    flattening into the last bin.
    """
    days = sorted(set(levels) & set(flows))
    if len(days) < MIN_PAIRS:
        return None
    q = np.array([flows[d] for d in days], float)
    h = np.array([levels[d] for d in days], float)
    order = np.argsort(q)
    q, h = q[order], h[order]

    edges = np.unique(np.quantile(q, np.linspace(0, 1, 31)))
    bq, bh = [], []
    for a, b in zip(edges, edges[1:]):
        m = (q >= a) & (q <= b)
        if m.sum() >= 2:
            bq.append(float(np.median(q[m])))
            bh.append(float(np.median(h[m])))
    if len(bq) < 4:
        return None
    bq = np.array(bq)
    bh = np.maximum.accumulate(np.array(bh))
    keep = np.concatenate([[True], np.diff(bq) > 0])
    bq, bh = bq[keep], bh[keep]
    if len(bq) < 4:
        return None

    k = max(5, len(q) * 15 // 100)
    lo_slope = np.polyfit(q[:k], h[:k], 1)[0] if np.ptp(q[:k]) > 0 else 0.0
    hi_slope = np.polyfit(q[-k:], h[-k:], 1)[0] if np.ptp(q[-k:]) > 0 else 0.0
    lo_slope, hi_slope = max(lo_slope, 0.0), max(hi_slope, 0.0)

    def f(x):
        x = np.asarray(x, float)
        y = np.interp(x, bq, bh)
        y = np.where(x < bq[0], bh[0] + lo_slope * (x - bq[0]), y)
        return np.where(x > bq[-1], bh[-1] + hi_slope * (x - bq[-1]), y)

    resid = h - f(q)
    spread = float(np.subtract(*np.percentile(h, [90, 10]))) or 1e-9
    scatter = float(np.median(np.abs(resid))) / spread
    return f, scatter


def usable(rating) -> bool:
    return rating is not None and rating[1] <= MAX_SCATTER
