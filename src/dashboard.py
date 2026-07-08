"""Generate a self-contained dashboard (docs/index.html).

Per river: verdict, current value, trend, a chart of recent levels continuing
into the 1-3 day ML forecast with the "good zone" shaded, the best-time-of-day
window (melt-fed rivers), and a plain-language outlook. A summary header shows
how many rivers are in each state. No external assets (GitHub Pages ready).

Colors follow the dataviz skill: one data hue for the value series (observed
solid / forecast dashed), reserved status colors for the good-zone band and
verdict badges (always paired with a text label, never color-alone), recessive
grid and text in ink tokens.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .analyze import Assessment, VERDICT_ORDER
from .sources import StationData
from .weather import RainOutlook

# Reserved status colors (verdict badges + zone band). Each always ships a label.
_STATUS = {
    "GO": "#2e9e5b", "GET_READY": "#c9a227", "MARGINAL": "#d97706",
    "TOO_LOW": "#2f74d0", "BLOWN_OUT": "#d64545", "NO_DATA": "#8a94a6",
}
_LABEL = {
    "GO": "GO FISH", "GET_READY": "GET READY", "MARGINAL": "MARGINAL",
    "TOO_LOW": "TOO LOW", "BLOWN_OUT": "BLOWN OUT", "NO_DATA": "NO DATA",
}
_SERIES = "#2563eb"   # the value line (observed + forecast), one hue


def _fmt(v: float, unit: str) -> str:
    return f"{v:.2f} m" if unit == "m" else f"{v:,.0f} cms"


def _chart(a: Assessment, data: StationData, width: int = 300, height: int = 120) -> str:
    """Observed recent series -> forecast, with the good-zone band shaded."""
    obs = [v for _, v in data.series(a.metric)][-48:]
    fc_vals = [f.value for f in a.forecast]
    if len(obs) < 2 and not fc_vals:
        return '<div class="chart-empty">no recent readings</div>'

    all_vals = obs + fc_vals + [a.good_low, a.good_high]
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0
    pl, pr, pt, pb = 6, 6, 8, 8
    iw, ih = width - pl - pr, height - pt - pb

    def y(v):
        return pt + ih - ((v - lo) / span) * ih

    n_obs = len(obs)
    n_fc = len(fc_vals)
    total = max(n_obs + n_fc - 1, 1)

    def x(i):
        return pl + (i / total) * iw

    # good-zone band
    band_top, band_bot = y(a.good_high), y(a.good_low)
    band = (f'<rect x="{pl}" y="{band_top:.1f}" width="{iw}" height="{max(band_bot-band_top,0):.1f}" '
            f'fill="{_STATUS["GO"]}" opacity="0.13"/>')
    # blown-out line (if within view)
    blown_line = ""
    if lo <= a.blown_out <= hi:
        yb = y(a.blown_out)
        blown_line = (f'<line x1="{pl}" y1="{yb:.1f}" x2="{width-pr}" y2="{yb:.1f}" '
                      f'stroke="{_STATUS["BLOWN_OUT"]}" stroke-width="1" stroke-dasharray="2 3" opacity="0.7"/>')

    obs_pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(obs))
    obs_line = (f'<polyline fill="none" stroke="{_SERIES}" stroke-width="2" stroke-linejoin="round" '
                f'stroke-linecap="round" points="{obs_pts}"/>') if n_obs >= 2 else ""

    fc_line = fc_dots = divider = ""
    if n_fc:
        start_i = n_obs - 1 if n_obs else 0
        anchor = obs[-1] if obs else fc_vals[0]
        fpts_idx = [(start_i, anchor)] + [(n_obs + j, v) for j, v in enumerate(fc_vals)]
        fpts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in fpts_idx)
        fc_line = (f'<polyline fill="none" stroke="{_SERIES}" stroke-width="2" stroke-dasharray="4 3" '
                   f'opacity="0.75" points="{fpts}"/>')
        dots = []
        for j, (f, v) in enumerate(zip(a.forecast, fc_vals)):
            cx, cy = x(n_obs + j), y(v)
            c = _STATUS.get(f.verdict, _SERIES)
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{c}" stroke="var(--card)" '
                        f'stroke-width="1.5"><title>{f.label}: {_fmt(v, a.unit)} ({_LABEL[f.verdict]})</title></circle>')
        fc_dots = "".join(dots)
        xd = x(start_i)
        divider = (f'<line x1="{xd:.1f}" y1="{pt}" x2="{xd:.1f}" y2="{height-pb}" '
                   f'stroke="var(--line)" stroke-width="1" stroke-dasharray="1 3"/>')

    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="recent {a.metric} and forecast">'
            f'{band}{blown_line}{divider}{obs_line}{fc_line}{fc_dots}</svg>')


def _forecast_chips(a: Assessment) -> str:
    if not a.forecast:
        return ""
    chips = []
    for f in a.forecast:
        c = _STATUS.get(f.verdict, "#8a94a6")
        chips.append(f'<span class="chip" style="--c:{c}" title="{_LABEL[f.verdict]}">'
                     f'{html.escape(f.label)}: {_fmt(f.value, a.unit)}</span>')
    skill = ""
    if a.forecast_skill is not None:
        pct = int(round(a.forecast_skill * 100))
        tag = "beats baseline" if a.forecast_skill > 0 else "weak"
        skill = f'<span class="skill" title="cross-validated skill vs a no-change baseline">model {tag} ({pct:+d}%)</span>'
    return f'<div class="chips">{"".join(chips)}{skill}</div>'


def _card(a: Assessment, data: StationData) -> str:
    color = _STATUS.get(a.verdict, "#8a94a6")
    arrow = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": "·"}[a.trend]
    val = _fmt(a.value, a.unit) if a.value is not None else "—"
    updated = ""
    if a.updated:
        try:
            updated = datetime.fromisoformat(a.updated).astimezone(timezone.utc).strftime("%b %d, %H:%M UTC")
        except ValueError:
            updated = a.updated
    best = f'<p class="best">🕐 {html.escape(a.best_time)}</p>' if a.best_time else ""
    return f"""
    <article class="card" style="--accent:{color}">
      <header><h2>{html.escape(a.river)}</h2><span class="badge">{a.emoji} {_LABEL.get(a.verdict, a.verdict)}</span></header>
      <div class="topline"><span class="num">{val}</span><span class="trend">{arrow} {a.trend}</span>
        <span class="metric-tag">{a.metric}</span></div>
      {_chart(a, data)}
      {_forecast_chips(a)}
      <p class="headline">{html.escape(a.headline)}</p>
      <p class="outlook">{html.escape(a.outlook)}</p>
      {best}
      <footer><span>Station {html.escape(a.station)}</span><span>{html.escape(updated)}</span></footer>
    </article>"""


def _summary(assessments: list[Assessment]) -> str:
    counts = {v: 0 for v in VERDICT_ORDER}
    for a in assessments:
        counts[a.verdict] = counts.get(a.verdict, 0) + 1
    tiles = []
    for v in VERDICT_ORDER:
        if counts.get(v):
            tiles.append(f'<div class="tile" style="--c:{_STATUS[v]}"><span class="tn">{counts[v]}</span>'
                         f'<span class="tl">{_LABEL[v]}</span></div>')
    return f'<div class="tiles">{"".join(tiles)}</div>'


def render(results: list[tuple[Assessment, StationData, RainOutlook | None]], generated: str) -> str:
    order = {v: i for i, v in enumerate(VERDICT_ORDER)}
    results = sorted(results, key=lambda t: order.get(t[0].verdict, 99))
    assessments = [a for a, _, _ in results]
    cards = "\n".join(_card(a, d) for a, d, _ in results)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BC Salmon River Conditions</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f7fa; --fg:#0f172a; --card:#ffffff;
           --muted:#5b6472; --line:#e3e8ef; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1017; --fg:#e6eaf1; --card:#161b24; --muted:#93a0b4; --line:#232b38; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          background:var(--bg); color:var(--fg); }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:24px 16px 56px; }}
  h1 {{ font-size:1.55rem; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 18px; font-size:.9rem; }}
  .tiles {{ display:flex; flex-wrap:wrap; gap:10px; margin:0 0 22px; }}
  .tile {{ display:flex; flex-direction:column; align-items:center; min-width:76px;
           background:var(--card); border:1px solid var(--line); border-top:3px solid var(--c);
           border-radius:10px; padding:8px 12px; }}
  .tile .tn {{ font-size:1.5rem; font-weight:800; }}
  .tile .tl {{ font-size:.62rem; font-weight:700; letter-spacing:.05em; color:var(--muted); }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
           border-radius:12px; padding:16px; }}
  .card header {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; }}
  .card h2 {{ font-size:1.05rem; margin:0; }}
  .badge {{ font-size:.7rem; font-weight:800; letter-spacing:.04em; color:#fff; background:var(--accent);
            padding:3px 9px; border-radius:999px; white-space:nowrap; }}
  .topline {{ display:flex; align-items:baseline; gap:10px; margin:10px 0 4px; }}
  .num {{ font-size:1.7rem; font-weight:800; }}
  .trend {{ font-size:.82rem; color:var(--muted); }}
  .metric-tag {{ margin-left:auto; font-size:.62rem; text-transform:uppercase; letter-spacing:.06em;
                 color:var(--muted); border:1px solid var(--line); border-radius:6px; padding:1px 6px; }}
  .chart {{ width:100%; height:auto; margin:4px 0 6px; }}
  .chart-empty {{ font-size:.75rem; color:var(--muted); padding:24px 0; text-align:center; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 8px; }}
  .chip {{ font-size:.72rem; font-weight:600; border:1px solid var(--c); color:var(--fg);
           border-left:4px solid var(--c); border-radius:6px; padding:2px 7px; background:transparent; }}
  .skill {{ font-size:.68rem; color:var(--muted); align-self:center; }}
  .headline {{ margin:6px 0; font-weight:650; }}
  .outlook {{ margin:6px 0; font-size:.86rem; color:var(--muted); }}
  .best {{ margin:6px 0; font-size:.82rem; color:var(--fg); background:color-mix(in srgb, var(--accent) 10%, transparent);
           border-radius:8px; padding:6px 9px; }}
  .card footer {{ display:flex; justify-content:space-between; font-size:.7rem; color:var(--muted);
                  margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }}
  .legend {{ font-size:.72rem; color:var(--muted); margin:18px 0 0; display:flex; gap:16px; flex-wrap:wrap; }}
  .legend span::before {{ content:""; display:inline-block; width:14px; height:3px; margin-right:5px;
                          vertical-align:middle; }}
  .lg-obs::before {{ background:{_SERIES}; }}
  .lg-fc::before {{ background:{_SERIES}; opacity:.6;
                    background-image:repeating-linear-gradient(90deg,{_SERIES} 0 4px,transparent 4px 7px); }}
  .lg-zone::before {{ background:{_STATUS['GO']}; opacity:.4; height:10px; }}
  .foot {{ margin-top:26px; font-size:.78rem; color:var(--muted); text-align:center; }}
  a {{ color:inherit; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎣 BC Salmon River Conditions</h1>
  <p class="sub">Live water level / flow, a 1-3 day ML forecast, and rain outlook.
     Updated {html.escape(generated)}. Green band = good zone. Not a safety guarantee — check conditions yourself.</p>
  {_summary(assessments)}
  <div class="grid">
    {cards}
  </div>
  <div class="legend">
    <span class="lg-obs">observed</span>
    <span class="lg-fc">forecast (1-3 d)</span>
    <span class="lg-zone">good zone</span>
  </div>
  <p class="foot">Water: Environment and Climate Change Canada (wateroffice.ec.gc.ca).
     Rain: Open-Meteo. Forecast: ridge regression trained per station. Thresholds: calibrate in config/rivers.yaml.</p>
</div>
</body>
</html>"""
