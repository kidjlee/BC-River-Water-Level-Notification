"""Generate docs/history.html — a browsable forecast + conditions history.

Per river:
  * up to ~1 year of daily observed level/flow (backfilled from ECCC),
  * the forecast track record (accuracy vs actuals), and
  * a table of recent forecast -> actual comparisons (✓/✗).

Linked from the main dashboard. Self-contained, light/dark, mobile-first.
"""
from __future__ import annotations

import html
from datetime import datetime

from . import history

_SERIES = "#2563eb"
_OK, _BAD = "#2e9e5b", "#d64545"


def _year_chart(series: list, unit: str, w: int = 680, h: int = 130) -> str:
    pts = [(d, v) for d, v in series if v is not None]
    if len(pts) < 2:
        return '<div class="he">not enough history yet</div>'
    ys = [v for _, v in pts]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    pl, pr, pt, pb = 40, 8, 8, 18
    iw, ih = w - pl - pr, h - pt - pb
    n = len(pts)

    def x(i):
        return pl + (i / (n - 1)) * iw

    def y(v):
        return pt + ih - ((v - lo) / span) * ih

    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
    # month gridlines + labels
    ticks = ""
    last_m = None
    for i, (d, _) in enumerate(pts):
        m = d[:7]
        if m != last_m:
            last_m = m
            xx = x(i)
            ticks += (f'<line x1="{xx:.1f}" y1="{pt}" x2="{xx:.1f}" y2="{h-pb}" stroke="var(--line)" '
                      f'stroke-width="1"/><text x="{xx:.1f}" y="{h-5}" class="ax">{d[5:7]}</text>')
    yl = (f'<text x="2" y="{y(hi)+8:.0f}" class="ax">{hi:.2f}</text>'
          f'<text x="2" y="{y(lo):.0f}" class="ax">{lo:.2f}</text>')
    return (f'<svg class="hchart" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="1-year daily {unit} history">{ticks}{yl}'
            f'<polyline fill="none" stroke="{_SERIES}" stroke-width="1.5" points="{line}"/></svg>')


def _matches_table(station: str, unit: str) -> str:
    rows = history.recent_matches(station, limit=20)
    if not rows:
        return '<p class="he">No matured forecasts yet — this fills in as days pass.</p>'
    trs = []
    for r in rows:
        mark = f'<span style="color:{_OK}">✓</span>' if r["hit"] else f'<span style="color:{_BAD}">✗</span>'
        fmt = (lambda x: f"{x:.3f}") if unit == "m" else (lambda x: f"{x:,.0f}")
        trs.append(
            f'<tr><td>{r["target"].strftime("%b %d")}</td><td>{r["day"]}d</td>'
            f'<td>{fmt(r["pred"])}</td><td>{fmt(r["actual"])}</td>'
            f'<td>{html.escape(r["pred_vd"].replace("_"," "))}</td>'
            f'<td>{html.escape(r["actual_vd"].replace("_"," "))}</td><td>{mark}</td></tr>')
    return (f'<table class="ht"><thead><tr><th>for</th><th>ahead</th><th>predicted</th>'
            f'<th>actual</th><th>pred verdict</th><th>actual</th><th></th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def render(meta: list, actuals: dict, accuracy: dict, generated: str) -> str:
    sections = []
    for name, station, region, unit in meta:
        act = actuals.get(station, {})
        chart = _year_chart(act.get("series", []), unit)
        acc = accuracy.get(station)
        if acc and acc.get("n", 0) >= 5:
            summary = (f'{acc["n"]} forecasts checked · <b>{int(acc["hit_rate"]*100)}%</b> verdict match '
                       f'· ±{acc["mae"]} {unit} avg error')
        else:
            summary = "forecast track record builds as days pass (needs 5+ checks)"
        sections.append(f"""
        <section class="rc">
          <header><h2>{html.escape(name)}</h2><span class="reg">{html.escape(region)}</span></header>
          <p class="acc">📈 {summary}</p>
          {chart}
          <details><summary>Recent forecasts vs actual</summary>{_matches_table(station, unit)}</details>
        </section>""")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800"><title>Forecast History — BC Salmon Rivers</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f7fa; --fg:#0f172a; --card:#fff; --muted:#5b6472; --line:#e3e8ef; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1017; --fg:#e6eaf1; --card:#161b24; --muted:#93a0b4; --line:#232b38; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--fg); }}
  .wrap {{ max-width:900px; margin:0 auto; padding:20px 14px 48px; }}
  h1 {{ font-size:1.4rem; margin:0 0 2px; }}
  .sub {{ color:var(--muted); font-size:.85rem; margin:0 0 18px; }}
  a {{ color:#2563eb; }}
  .rc {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin:0 0 14px; }}
  .rc header {{ display:flex; justify-content:space-between; align-items:baseline; }}
  .rc h2 {{ font-size:1.05rem; margin:0; }}
  .reg {{ font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }}
  .acc {{ font-size:.85rem; color:var(--muted); margin:6px 0 8px; }}
  .hchart {{ width:100%; height:auto; }}
  .ax {{ fill:var(--muted); font-size:8px; }}
  .he {{ font-size:.8rem; color:var(--muted); padding:16px 0; text-align:center; }}
  details {{ margin-top:8px; font-size:.85rem; }}
  summary {{ cursor:pointer; color:var(--muted); }}
  .ht {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:.78rem; }}
  .ht th, .ht td {{ text-align:left; padding:3px 6px; border-bottom:1px solid var(--line); }}
  .ht th {{ color:var(--muted); font-weight:600; }}
</style></head><body>
<div class="wrap">
  <h1>📜 Forecast History</h1>
  <p class="sub"><a href="index.html">← back to conditions</a> · up to 1 year of daily levels + how the forecasts scored.
     Updated {html.escape(generated)}.</p>
  {"".join(sections)}
</div></body></html>"""
