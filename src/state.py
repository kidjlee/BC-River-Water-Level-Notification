"""Tiny JSON state store so we only alert on *changes*, not every run.

Without this, a river sitting in the "GO" zone would ping you every single
run. We remember each river's last verdict and only notify when it newly
becomes alertable (or transitions between GO/GET_READY).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .analyze import Assessment

STATE_PATH = Path(os.getenv("STATE_FILE", "state/state.json"))


def load() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save(assessments: list[Assessment]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {a.station: a.verdict for a in assessments}
    STATE_PATH.write_text(json.dumps(data, indent=2))


def newly_alertable(assessments: list[Assessment], previous: dict) -> list[Assessment]:
    """Rivers to notify about: alertable now, and either weren't before or
    changed verdict (e.g. GET_READY -> GO is worth a fresh ping)."""
    out = []
    for a in assessments:
        if not a.is_alertable:
            continue
        if previous.get(a.station) != a.verdict:
            out.append(a)
    return out
