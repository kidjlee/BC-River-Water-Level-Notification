"""A small, honest ML forecast of river level/flow 1-3 days ahead.

Design goals: transparent, dependency-light (numpy only), and retrainable from
free historical data. It is NOT a hydrological model — it's a ridge regression
that learns how a river responds to recent conditions + rain, per station.

Method
------
Daily resolution. For each horizon k in {1,2,3} days we train a separate ridge
regression predicting the *change* in the metric (level or flow):

    delta_k = value(t+k) - value(t)

from features known at time t:

    [ value(t),
      value(t) - value(t-1),          # 1-day trend
      value(t) - value(t-3),          # 3-day trend
      rain over the past 1 day,
      rain over the past 3 days,
      cumulative rain forecast over the next k days,
      sin(2*pi*doy/365), cos(2*pi*doy/365) ]   # season

Features are standardized; y is centered. Closed-form ridge:
    w = (XᵀX + λI)⁻¹ Xᵀy_centered

Models are stored per station in models/<station>.json. At inference the same
features are built from live data (recent readings + Open-Meteo past/forecast
rain). If no model exists, callers fall back to the heuristic outlook.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HORIZONS = [1, 2, 3]           # days ahead
N_FEATURES = 8
MODELS_DIR = Path("models")


def _season_terms(doy: int) -> tuple[float, float]:
    a = 2 * math.pi * (doy / 365.0)
    return math.sin(a), math.cos(a)


def build_feature_row(value, d1, d3, rain_past1, rain_past3, rain_next_cumulative, doy) -> list[float]:
    s, c = _season_terms(doy)
    return [value, d1, d3, rain_past1, rain_past3, rain_next_cumulative, s, c]


@dataclass
class RidgeModel:
    """Standardized ridge regression for one horizon."""
    mean: list[float]
    std: list[float]
    weights: list[float]
    y_mean: float
    n_train: int
    cv_mae: float          # cross-val mean-abs-error of delta (model quality)
    persist_mae: float     # baseline: predicting "no change"

    def predict_delta(self, features: list[float]) -> float:
        x = (np.array(features) - np.array(self.mean)) / np.array(self.std)
        return float(x @ np.array(self.weights) + self.y_mean)

    @property
    def skill(self) -> float:
        """1 - model_error/baseline_error. >0 means it beats persistence."""
        if self.persist_mae <= 0:
            return 0.0
        return round(1.0 - self.cv_mae / self.persist_mae, 3)


def _fit_ridge(X: np.ndarray, y: np.ndarray, lam: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    Xs = (X - mean) / std
    y_mean = y.mean()
    yc = y - y_mean
    n_feat = Xs.shape[1]
    w = np.linalg.solve(Xs.T @ Xs + lam * np.eye(n_feat), Xs.T @ yc)
    return w, mean, std, y_mean


def _kfold_mae(X: np.ndarray, y: np.ndarray, lam: float, k: int = 5) -> float:
    n = len(y)
    if n < k * 2:
        return float(np.mean(np.abs(y - y.mean())))
    idx = np.arange(n)
    folds = np.array_split(idx, k)
    errs = []
    for i in range(k):
        test = folds[i]
        train = np.concatenate([folds[j] for j in range(k) if j != i])
        w, mean, std, y_mean = _fit_ridge(X[train], y[train], lam)
        Xs = (X[test] - mean) / std
        pred = Xs @ w + y_mean
        errs.append(np.mean(np.abs(pred - y[test])))
    return float(np.mean(errs))


def train_from_daily(dates_doy: list[int], values: list[float], rain_daily: list[float],
                     lam: float = 1.0) -> dict[int, RidgeModel]:
    """Train one RidgeModel per horizon from aligned daily arrays.

    dates_doy[i], values[i], rain_daily[i] describe the same day i (chronological).
    """
    v = np.asarray(values, dtype=float)
    r = np.asarray(rain_daily, dtype=float)
    doy = np.asarray(dates_doy, dtype=float)
    n = len(v)
    models: dict[int, RidgeModel] = {}

    for k in HORIZONS:
        rows, targets = [], []
        # need history back to t-3 and future to t+k
        for t in range(3, n - k):
            value = v[t]
            d1 = v[t] - v[t - 1]
            d3 = v[t] - v[t - 3]
            rain_past1 = r[t]
            rain_past3 = r[t - 2:t + 1].sum()
            rain_next = r[t + 1:t + 1 + k].sum()
            s, c = _season_terms(int(doy[t]))
            rows.append([value, d1, d3, rain_past1, rain_past3, rain_next, s, c])
            targets.append(v[t + k] - v[t])
        if len(rows) < 20:
            continue
        X = np.asarray(rows)
        y = np.asarray(targets)
        w, mean, std, y_mean = _fit_ridge(X, y, lam)
        cv_mae = _kfold_mae(X, y, lam)
        persist_mae = float(np.mean(np.abs(y)))  # baseline predicts delta=0
        models[k] = RidgeModel(
            mean=mean.tolist(), std=std.tolist(), weights=w.tolist(),
            y_mean=float(y_mean), n_train=len(y), cv_mae=round(cv_mae, 4),
            persist_mae=round(persist_mae, 4),
        )
    return models


def save_models(station: str, models: dict[int, RidgeModel]) -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / f"{station}.json"
    payload = {str(k): m.__dict__ for k, m in models.items()}
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_models(station: str) -> dict[int, RidgeModel] | None:
    path = MODELS_DIR / f"{station}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return {int(k): RidgeModel(**v) for k, v in raw.items()}


@dataclass
class Forecast:
    horizon_days: int
    value: float
    skill: float


def predict(models: dict[int, RidgeModel], current_value: float, d1: float, d3: float,
            rain_past1: float, rain_past3: float, rain_next_cumulative: dict[int, float],
            doy: int) -> list[Forecast]:
    """Return projected metric value for each trained horizon."""
    out = []
    for k in sorted(models):
        feats = build_feature_row(
            current_value, d1, d3, rain_past1, rain_past3,
            rain_next_cumulative.get(k, 0.0), doy,
        )
        delta = models[k].predict_delta(feats)
        out.append(Forecast(horizon_days=k, value=round(current_value + delta, 2), skill=models[k].skill))
    return out
