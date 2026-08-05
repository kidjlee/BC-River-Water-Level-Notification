"""DFO Region 2 salmon rules: load them, and say which are in force today.

config/regulations.json is scraped by tools/fetch_regulations.py. This module
only answers "does this rule apply on this date", which is fiddly enough to be
worth isolating: several windows wrap the calendar year (Sep 15 to Jan 31), and
one is open-ended ("Apr 1 until further notice").
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

_PATH = Path("config/regulations.json")


def load(path: Path | None = None) -> dict:
    try:
        return json.loads((path or _PATH).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def in_window(window, on: dt.date) -> bool:
    """Is `on` inside [start, end]? Handles year-wrapping and open-ended."""
    if not window:
        return False
    sm, sd, em, ed = window
    if sm is None:
        return False
    start = (sm, sd)
    today = (on.month, on.day)
    if em is None:
        return True          # in force from its start date until revoked
    end = (em, ed)
    if start <= end:
        return start <= today <= end
    return today >= start or today <= end     # wraps the new year


def for_river(regs: dict, dfo_waters: str) -> list[dict]:
    return (regs.get("waters") or {}).get(dfo_waters) or []


def split_active(entries: list[dict], on: dt.date) -> tuple[list, list]:
    """(in force today, everything else) preserving the page's order."""
    active = [e for e in entries if in_window(e.get("window"), on)]
    rest = [e for e in entries if not in_window(e.get("window"), on)]
    return active, rest


def is_closure(entry: dict) -> bool:
    """Does this rule mean you can't keep (or can't fish for) the species?"""
    limit = (entry.get("limit") or "").lower()
    return "non-retention" in limit or "no fishing" in limit
