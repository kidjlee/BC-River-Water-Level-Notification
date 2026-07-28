"""Log every run's forecasts and score them against what actually happened.

Each run appends one compact line per river to data/history.jsonl:
    {"t": ISO_time, "s": station, "v": current_value, "vd": verdict,
     "fc": [[day, predicted_value, predicted_verdict], ...]}

`evaluate()` then walks that history: for each past forecast, it finds the
actual observed value recorded near the forecast's target day and measures the
error + whether the predicted verdict matched. That gives every river a real,
accumulating forecast track record (accuracy), shown on the dashboard.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HIST = Path(os.getenv("HISTORY_FILE", "data/history.jsonl"))
MATCH_WINDOW_H = 18   # how close a later observation must be to a forecast's target day


def record(assessments, now: datetime | None = None) -> None:
    now = (now or datetime.now(timezone.utc)).isoformat()
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a") as f:
        for a in assessments:
            if a.value is None:
                continue
            f.write(json.dumps({
                "t": now, "s": a.station, "v": a.value, "vd": a.verdict,
                "fc": [[d.day, d.value, d.verdict] for d in a.forecast],
            }) + "\n")


def _load(max_lines: int = 40000) -> list[dict]:
    if not HIST.exists():
        return []
    lines = HIST.read_text().splitlines()[-max_lines:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def evaluate() -> dict:
    """Return {station: {n, mae, hit_rate}} scoring past forecasts vs actuals."""
    recs = _load()
    obs: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    for r in recs:
        try:
            obs[r["s"]].append((datetime.fromisoformat(r["t"]), r["v"], r["vd"]))
        except (KeyError, ValueError):
            continue
    for s in obs:
        obs[s].sort()

    out: dict[str, dict] = {}
    for r in recs:
        s = r.get("s")
        try:
            t = datetime.fromisoformat(r["t"])
        except (KeyError, ValueError):
            continue
        for item in r.get("fc", []):
            day, pred_val, pred_vd = item
            target = t + timedelta(days=day)
            best = None
            best_dt = None
            for ot, ov, ovd in obs.get(s, []):
                gap = abs((ot - target).total_seconds())
                if gap <= MATCH_WINDOW_H * 3600 and (best_dt is None or gap < best_dt):
                    best_dt, best = gap, (ov, ovd)
            if best is None:
                continue
            ov, ovd = best
            st = out.setdefault(s, {"n": 0, "abserr": 0.0, "hits": 0})
            st["n"] += 1
            st["abserr"] += abs(pred_val - ov)
            st["hits"] += 1 if pred_vd == ovd else 0

    for st in out.values():
        st["mae"] = round(st["abserr"] / st["n"], 3) if st["n"] else None
        st["hit_rate"] = round(st["hits"] / st["n"], 2) if st["n"] else None
    return out
