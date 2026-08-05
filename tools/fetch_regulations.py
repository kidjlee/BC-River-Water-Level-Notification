"""Scrape DFO's Region 2 salmon notice into config/regulations.json.

The page is the legal source for what you may actually keep, and it changes
in-season, so it gets refreshed on a schedule rather than transcribed once by
hand. Output shape:

  {
    "source": url, "date_modified": "2026-04-01", "fetched": iso8601,
    "general": ["...region-wide rules..."],
    "waters": {
      "Capilano River": [
        {"area": "including tributaries", "species": "Coho",
         "dates": "Apr 1 to Jun 30", "limit": "2 hatchery marked per day",
         "window": [4, 1, 6, 30]},
        ...
      ]
    }
  }

`window` is [start_month, start_day, end_month, end_day], or null when the
dates don't parse (e.g. "Apr 1 until further notice" -> [4, 1, null, null],
meaning in force from that date onward). Keeping the raw `dates` string beside
it means a parse we don't understand still gets shown verbatim rather than
silently dropped.

Needs internet; this sandbox blocks *.gc.ca, so run it from CI.
Run: python tools/fetch_regulations.py [--dump]
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/rivers.yaml"
OUT = ROOT / "config/regulations.json"
URL = "https://www.pac.dfo-mpo.gc.ca/fm-gp/rec/fresh-douce/region2-eng.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; bc-river-water-level-notifier/1.0)"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_window(text: str):
    """"Sep 1 to Nov 30" -> [9, 1, 11, 30]. Open-ended -> [m, d, None, None]."""
    words = text.replace("–", "-").replace("-", " to ").split()
    nums, months = [], []
    for w in words:
        key = w[:3].lower()
        if key in MONTHS:
            months.append(MONTHS[key])
        elif w.isdigit():
            nums.append(int(w))
    if len(months) == 2 and len(nums) == 2:
        return [months[0], nums[0], months[1], nums[1]]
    if len(months) == 1 and len(nums) == 1:
        return [months[0], nums[0], None, None]     # "until further notice"
    return None


def table_grid(table) -> list[list[str]]:
    """Expand a table's rowspan/colspan into a dense grid of cell text.

    DFO leans on rowspan for the Waters and Specific-area columns, so a naive
    row-by-row read attributes every species after the first to the wrong
    river. Carrying spans forward is the whole point of this function.
    """
    grid: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}   # col -> (text, rows remaining)
    for tr in table.find_all("tr"):
        row: list[str] = []
        col = 0
        cells = tr.find_all(["th", "td"])
        idx = 0
        while idx < len(cells) or col in pending:
            if col in pending:
                text, left = pending[col]
                row.append(text)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, left - 1)
                col += 1
                continue
            cell = cells[idx]
            idx += 1
            text = cell.get_text(" ", strip=True)
            span_r = int(cell.get("rowspan", 1) or 1)
            span_c = int(cell.get("colspan", 1) or 1)
            for _ in range(span_c):
                row.append(text)
                if span_r > 1:
                    pending[col] = (text, span_r - 1)
                col += 1
        grid.append(row)
    return grid


def scrape(url: str = URL) -> dict:
    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    table = soup.find("table")
    if table is None:
        raise RuntimeError("no <table> on the DFO page — layout changed?")

    # Region-wide rules: the bullets above the table. Drop list items that are
    # just a link (those are the page's navigation, not a rule).
    general = []
    for li in table.find_all_previous("li"):
        text = li.get_text(" ", strip=True)
        link = li.find("a")
        if not text or (link and link.get_text(" ", strip=True) == text):
            continue
        general.append(text)
    general.reverse()

    waters: dict[str, list] = {}
    current = ""
    for row in table_grid(table):
        cells = (row + [""] * 5)[:5]
        water, area, species, dates, limit = (c.strip() for c in cells)
        if water and not water.lower().startswith("waters"):
            current = water
        if not (species and dates) or species.lower() == "species":
            continue                      # header row
        # "Sumas River - See Chilliwack River" is a colspan'd pointer, not a
        # rule; it arrives with the same text smeared across every column.
        if species == dates or " - see " in water.lower():
            continue
        waters.setdefault(current, []).append({
            "area": area,
            "species": species,
            "dates": dates,
            "limit": limit,
            "window": parse_window(dates),
        })

    modified = ""
    stamp = soup.find("time")
    if stamp:
        modified = stamp.get_text(strip=True)

    return {
        "source": url,
        "date_modified": modified,
        "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "general": general,
        "waters": waters,
    }


def main() -> int:
    data = scrape()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True))

    print(f"source last modified {data['date_modified']}, "
          f"{len(data['general'])} region-wide rules, "
          f"{len(data['waters'])} waters\n")
    if "--dump" in sys.argv:
        for water, entries in sorted(data["waters"].items()):
            print(f"{water}")
            for e in entries:
                win = e["window"] or "UNPARSED"
                print(f"    {e['species']:9s} {e['dates']:26s} {e['limit']:44s} {win}")

    # Which configured rivers actually resolve to an entry?
    cfg = yaml.safe_load(CONFIG.read_text())
    print("\nriver -> DFO waters:")
    unmatched = []
    for river in cfg.get("rivers", []):
        key = river.get("dfo_waters")
        if key and key in data["waters"]:
            print(f"  {river['name'][:34]:34s} -> {key} ({len(data['waters'][key])} rules)")
        elif key:
            print(f"  {river['name'][:34]:34s} -> !! '{key}' NOT on the page")
            unmatched.append(river["name"])
        else:
            print(f"  {river['name'][:34]:34s} -- no dfo_waters set (outside Region 2?)")

    unparsed = [(w, e["dates"]) for w, es in data["waters"].items()
                for e in es if e["window"] is None]
    if unparsed:
        print(f"\n{len(unparsed)} date strings did not parse (shown verbatim on the site):")
        for w, d in unparsed:
            print(f"  {w}: {d!r}")
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} river(s) point at a missing DFO entry")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
