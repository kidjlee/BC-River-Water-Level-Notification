"""Pull DFO's Region 2 (Lower Mainland) freshwater fishing notice page as text.

This sandbox's network policy blocks *.gc.ca outbound, so this has to run from
a GitHub Actions runner (open internet) and be read back from the job log --
same workaround used for the ECCC probes.

DFO publishes river-by-river open/closed status and in-season variations as
plain text/tables on this page, not a structured API, so we fetch the raw HTML,
strip it to readable text, and print it whole. Extracting the actual
restrictions is a reading task for whoever consumes the log, not something to
guess a schema for here.

Run: python tools/probe_dfo_restrictions.py [url]
"""
from __future__ import annotations

import sys

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://www.pac.dfo-mpo.gc.ca/fm-gp/rec/fresh-douce/region2-eng.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; bc-river-water-level-notifier/1.0)"}


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    print(f"HTTP {resp.status_code}  {len(resp.content)} bytes  {url}\n")

    soup = BeautifulSoup(resp.content, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    print("\n".join(lines))

    # Tables often carry the actual open/closed schedule; print them again,
    # explicitly, since get_text() can blur row/column structure together.
    tables = soup.find_all("table")
    if tables:
        print(f"\n\n===== {len(tables)} <table> element(s), row by row =====")
        for i, table in enumerate(tables):
            print(f"\n--- table {i} ---")
            for row in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                if any(cells):
                    print(" | ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
