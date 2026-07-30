"""Water Office provisional history — the bridge between ECCC's two feeds.

ECCC's OGC API leaves a hole we can't fill from either end:

  hydrometric-daily-mean  approved archive. Rows exist right up to today, but
                          the recent ones carry LEVEL/DISCHARGE = null until
                          they're finalized. The last *non-null* day lags from
                          a few weeks (Vedder) to ~19 months (Alouette, Skeena).
  hydrometric-realtime    a strict rolling 30-day window.

So for most stations the last year is mostly hole. Water Office serves the same
gauges' *provisional* readings at 5-minute resolution for ~18 months back,
which covers the whole gap. We average those to daily means and splice them in
under the approved values.

Values are provisional and may be revised; approved data always wins on any day
both sources cover.
"""
from __future__ import annotations

import csv
import datetime as dt

import requests

URL = "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"
PARAM = {"level": 46, "flow": 47}
UA = {"User-Agent": "bc-river-water-level-notifier/1.0"}


def fetch_daily_means(
    station: str,
    metric: str,
    start: dt.date,
    end: dt.date,
    timeout: int = 180,
) -> dict[str, float]:
    """Return {YYYY-MM-DD: daily mean} of provisional readings in [start, end].

    Streams the CSV — a year of 5-minute data is ~7 MB per station.
    """
    param = PARAM.get(metric, 46)
    params = {
        "stations[]": station,
        "parameters[]": param,
        "start_date": f"{start.isoformat()} 00:00:00",
        "end_date": f"{end.isoformat()} 23:59:59",
    }
    resp = requests.get(URL, params=params, headers=UA, timeout=timeout, stream=True)
    resp.raise_for_status()
    resp.encoding = "utf-8-sig"

    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    reader = csv.reader(resp.iter_lines(decode_unicode=True))
    for row in reader:
        # ID, Date, Parameter, Value, Qualifier, Symbol, Approval, Grade
        if len(row) < 4:
            continue
        date_s, value_s = row[1].strip(), row[3].strip()
        if not value_s or not date_s[:4].isdigit():
            continue          # header row, or a reading with no value
        try:
            value = float(value_s)
        except ValueError:
            continue
        day = date_s[:10]
        sums[day] = sums.get(day, 0.0) + value
        counts[day] = counts.get(day, 0) + 1

    return {d: sums[d] / counts[d] for d in sums if counts[d]}
