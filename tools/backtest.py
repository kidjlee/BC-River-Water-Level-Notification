"""Reconstruct a year of forecast history by hindcasting the model.

The live forecast log only grows from today, so it starts empty. But we have the
raw history (ECCC daily levels + Open-Meteo rain archive) and the trained model,
so we can replay it: for each past day, build the same features the live app
uses and record what the model WOULD have predicted 1-3 days out, then score it
against what actually happened. Writes data/backtest.json per station:

    {station: {unit, acc: {"1":{n,mae,hit}, ..., "overall":{...}},
               series: [[target_date, actual, pred_1d, hit_1d], ...]}}

Honest caveat: the ridge model was fit on this history and we feed it the ACTUAL
rain that fell (a perfect forecast), so these numbers are an optimistic
in-sample estimate — live accuracy will be a bit lower. It's a realistic sense
of the model's shape, and far better than an empty page. Runs in the heavy
bootstrap / train jobs.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eccc_history import fetch_daily          # noqa: E402
from train_forecast import fetch_precip        # noqa: E402
from src import forecast as fc                 # noqa: E402

CONFIG = ROOT / "config/rivers.yaml"
MONTHLY = ROOT / "config/thresholds_monthly.json"
OUT = ROOT / "data/backtest.json"
WINDOW = 400   # days to hindcast


def _verdict(value, zones) -> str:
    gl, gh, bl = zones
    if value < gl:
        return "TOO_LOW"
    if value <= gh:
        return "GO"
    if value <= bl:
        return "MARGINAL"
    return "BLOWN_OUT"


def backtest_river(river, monthly) -> dict | None:
    station, metric = river["station"], river.get("metric", "level")
    models = fc.load_models(station)
    if not models:
        return None
    dates, values = fetch_daily(station, metric)
    if len(values) < 200:
        return None
    dates, values = dates[-WINDOW:], values[-WINDOW:]
    precip = fetch_precip(river["lat"], river["lon"], dates[0], dates[-1])
    v = np.asarray(values, float)
    r = np.asarray([precip.get(d, 0.0) for d in dates], float)
    doy = [datetime.fromisoformat(d).timetuple().tm_yday for d in dates]
    zones_flat = (river["good_low"], river["good_high"], river["blown_out"])

    def zones_for(date_str):
        m = str(int(date_str[5:7]))
        z = monthly.get(station, {}).get(m)
        return tuple(z) if z and len(z) == 3 and z[0] < z[1] < z[2] else zones_flat

    n = len(v)
    acc = {k: {"n": 0, "abserr": 0.0, "hits": 0} for k in fc.HORIZONS}
    series = []
    for t in range(3, n - max(fc.HORIZONS)):
        value = v[t]
        d1, d3 = v[t] - v[t - 1], v[t] - v[t - 3]
        rp1, rp3 = r[t], r[t - 2:t + 1].sum()
        for k in fc.HORIZONS:
            feats = fc.build_feature_row(value, d1, d3, rp1, rp3, r[t + 1:t + 1 + k].sum(), doy[t])
            pred = value + models[k].predict_delta(feats)
            actual = v[t + k]
            zt = zones_for(dates[t + k])
            hit = _verdict(pred, zt) == _verdict(actual, zt)
            a = acc[k]
            a["n"] += 1
            a["abserr"] += abs(pred - actual)
            a["hits"] += 1 if hit else 0
            if k == 1:
                rnd = 3 if metric != "flow" else 0
                series.append([dates[t + 1], round(float(actual), rnd), round(float(pred), rnd), hit])

    out_acc = {}
    tot = {"n": 0, "abserr": 0.0, "hits": 0}
    for k, a in acc.items():
        if a["n"]:
            out_acc[str(k)] = {"n": a["n"], "mae": round(a["abserr"] / a["n"], 3),
                               "hit": round(a["hits"] / a["n"], 2)}
            for key in tot:
                tot[key] += a[key]
    if tot["n"]:
        out_acc["overall"] = {"n": tot["n"], "mae": round(tot["abserr"] / tot["n"], 3),
                              "hit": round(tot["hits"] / tot["n"], 2)}
    return {"unit": "cms" if metric == "flow" else "m", "acc": out_acc, "series": series}


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    monthly = json.loads(MONTHLY.read_text()) if MONTHLY.exists() else {}
    out = {}
    for river in cfg.get("rivers", []):
        try:
            bt = backtest_river(river, monthly)
        except Exception as e:
            print(f"{river['name']}: FAILED ({e})")
            continue
        if bt:
            out[river["station"]] = bt
            o = bt["acc"].get("overall", {})
            print(f"{river['name']}: n={o.get('n')} hit={o.get('hit')} mae={o.get('mae')} {bt['unit']}")
        else:
            print(f"{river['name']}: no model/history")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
    print(f"\nWrote {OUT} ({len(out)} rivers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
