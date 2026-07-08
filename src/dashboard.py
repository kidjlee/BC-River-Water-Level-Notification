"""Generate a self-contained, mobile-first dashboard (docs/index.html).

Layout, top to bottom:
  * Header — title, local update time, summary tiles, auto-refresh.
  * "Best bet" hero — the single most fishable river right now (or the closest).
  * Rivers grouped by region. Each card shows:
      verdict badge, current value + trend + "as of",
      a level gauge (where the value sits low→blown-out),
      a chart of recent readings flowing into the 1-3 day ML forecast,
      forecast chips + model skill, plain-language advice, best time of day,
      species tags, and an off-season note when applicable.

Colors follow the dataviz skill: one data hue for the value series, reserved
status colors (each always paired with a text label), recessive grid/ink text.
No external assets — GitHub Pages ready; refreshes itself every 30 min.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .analyze import Assessment, VERDICT_ORDER
from .sources import StationData
from .weather import RainOutlook

_STATUS = {
    "GO": "#2e9e5b", "GET_READY": "#c9a227", "MARGINAL": "#d97706",
    "TOO_LOW": "#2f74d0", "BLOWN_OUT": "#d64545", "NO_DATA": "#8a94a6",
}
_LABEL = {
    "GO": "GO FISH", "GET_READY": "GET READY", "MARGINAL": "MARGINAL",
    "TOO_LOW": "TOO LOW", "BLOWN_OUT": "BLOWN OUT", "NO_DATA": "NO DATA",
}
_SERIES = "#2563eb"
_ZONE_COLORS = {"low": "#2f74d0", "good": "#2e9e5b", "high": "#d97706", "blown": "#d64545"}


def _fmt(v: float, unit: str) -> str:
    return f"{v:.2f} m" if unit == "m" else f"{v:,.0f} cms"


def _rel_time(updated: str | None, now: datetime) -> str:
    if not updated:
        return ""
    try:
        dt = datetime.fromisoformat(updated).astimezone(timezone.utc)
    except ValueError:
        return updated
    mins = (now - dt).total_seconds() / 60
    if mins < 0:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    if mins < 48 * 60:
        return f"{int(mins / 60)}h ago"
    return f"{int(mins / 1440)}d ago"


# --------------------------------------------------------------------------- gauge
def _gauge(a: Assessment) -> str:
    """A slim bar showing where the current value sits: too-low | good | high | blown."""
    if a.value is None:
        return ""
    gl, gh, bl = a.good_low, a.good_high, a.blown_out
    lo = min(gl, a.value)
    hi = max(bl, a.value)
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0

    def pct(v):
        return max(0.0, min(100.0, (v - lo) / span * 100))

    segs = [
        (lo, gl, _ZONE_COLORS["low"]),
        (gl, gh, _ZONE_COLORS["good"]),
        (gh, bl, _ZONE_COLORS["high"]),
        (bl, hi, _ZONE_COLORS["blown"]),
    ]
    bars = "".join(
        f'<div style="position:absolute;left:{pct(s):.1f}%;width:{pct(e)-pct(s):.1f}%;'
        f'top:0;bottom:0;background:{c};opacity:.55"></div>'
        for s, e, c in segs if e > s
    )
    mpct = pct(a.value)
    marker = (f'<div class="gmark" style="left:{mpct:.1f}%"></div>')
    return (f'<div class="gauge" title="current position between low and blown-out">'
            f'{bars}{marker}</div>'
            f'<div class="glabels"><span>low</span><span>good</span><span>high</span><span>blown</span></div>')


# --------------------------------------------------------------------------- chart
def _chart(a: Assessment, data: StationData, width: int = 300, height: int = 118) -> str:
    obs = [v for _, v in data.series(a.metric)][-48:]
    fc_vals = [f.value for f in a.forecast]
    if len(obs) < 2 and not fc_vals:
        return '<div class="chart-empty">no recent readings</div>'

    all_vals = obs + fc_vals + [a.good_low, a.good_high]
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.10 or 1.0
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0
    pl, pr, pt, pb = 34, 8, 8, 16
    iw, ih = width - pl - pr, height - pt - pb

    def y(v):
        return pt + ih - ((v - lo) / span) * ih

    n_obs, n_fc = len(obs), len(fc_vals)
    total = max(n_obs + n_fc - 1, 1)

    def x(i):
        return pl + (i / total) * iw

    band = (f'<rect x="{pl}" y="{y(a.good_high):.1f}" width="{iw}" '
            f'height="{max(y(a.good_low)-y(a.good_high),0):.1f}" fill="{_STATUS["GO"]}" opacity="0.13"/>')
    blown_line = ""
    if lo <= a.blown_out <= hi:
        blown_line = (f'<line x1="{pl}" y1="{y(a.blown_out):.1f}" x2="{width-pr}" y2="{y(a.blown_out):.1f}" '
                      f'stroke="{_STATUS["BLOWN_OUT"]}" stroke-width="1" stroke-dasharray="2 3" opacity="0.6"/>')

    # y-axis min/max labels
    yaxis = (f'<text x="2" y="{y(hi)+8:.1f}" class="ax">{_short(hi, a.unit)}</text>'
             f'<text x="2" y="{y(lo):.1f}" class="ax">{_short(lo, a.unit)}</text>')

    obs_pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(obs))
    obs_line = (f'<polyline fill="none" stroke="{_SERIES}" stroke-width="2" stroke-linejoin="round" '
                f'stroke-linecap="round" points="{obs_pts}"/>') if n_obs >= 2 else ""
    now_dot = (f'<circle cx="{x(n_obs-1):.1f}" cy="{y(obs[-1]):.1f}" r="3" fill="{_SERIES}" '
               f'stroke="var(--card)" stroke-width="1.5"/>') if n_obs else ""

    fc_line = fc_dots = divider = xlabels = ""
    if n_fc:
        start_i = n_obs - 1 if n_obs else 0
        anchor = obs[-1] if obs else fc_vals[0]
        fpts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in
                        [(start_i, anchor)] + [(n_obs + j, v) for j, v in enumerate(fc_vals)])
        fc_line = (f'<polyline fill="none" stroke="{_SERIES}" stroke-width="2" stroke-dasharray="4 3" '
                   f'opacity="0.75" points="{fpts}"/>')
        dots = []
        for j, (f, v) in enumerate(zip(a.forecast, fc_vals)):
            c = _STATUS.get(f.verdict, _SERIES)
            dots.append(f'<circle cx="{x(n_obs+j):.1f}" cy="{y(v):.1f}" r="3.5" fill="{c}" '
                        f'stroke="var(--card)" stroke-width="1.5">'
                        f'<title>{f.label}: {_fmt(v, a.unit)} ({_LABEL[f.verdict]})</title></circle>')
        fc_dots = "".join(dots)
        xd = x(start_i)
        divider = (f'<line x1="{xd:.1f}" y1="{pt}" x2="{xd:.1f}" y2="{height-pb}" '
                   f'stroke="var(--line)" stroke-width="1" stroke-dasharray="1 3"/>')
        xlabels = (f'<text x="{pl:.1f}" y="{height-3}" class="ax">-2d</text>'
                   f'<text x="{xd:.1f}" y="{height-3}" class="ax" text-anchor="middle">now</text>'
                   f'<text x="{width-pr:.1f}" y="{height-3}" class="ax" text-anchor="end">+{n_fc}d</text>')

    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="recent {a.metric} and forecast">'
            f'{band}{blown_line}{yaxis}{divider}{obs_line}{now_dot}{fc_line}{fc_dots}{xlabels}</svg>')


def _short(v: float, unit: str) -> str:
    if unit == "cms":
        return f"{v/1000:.1f}k" if abs(v) >= 1000 else f"{v:.0f}"
    return f"{v:.1f}"


# --------------------------------------------------------------------------- card pieces
def _forecast_chips(a: Assessment) -> str:
    if not a.forecast:
        return ""
    chips = "".join(
        f'<span class="chip" style="--c:{_STATUS.get(f.verdict, "#8a94a6")}" title="{_LABEL[f.verdict]}">'
        f'{html.escape(f.label)}: {_fmt(f.value, a.unit)}</span>' for f in a.forecast)
    skill = ""
    if a.forecast_skill is not None:
        pct = int(round(a.forecast_skill * 100))
        tag = "beats baseline" if a.forecast_skill > 0 else "weak"
        skill = (f'<span class="skill" title="cross-validated skill vs a no-change baseline">'
                 f'model {tag} ({pct:+d}%)</span>')
    return f'<div class="chips">{chips}{skill}</div>'


def _tags(a: Assessment) -> str:
    sp = "".join(f'<span class="tag">{html.escape(s)}</span>' for s in (a.species or [])[:5])
    off = "" if a.in_season else '<span class="tag off">off-season</span>'
    return f'<div class="tags">{off}{sp}</div>' if (sp or off) else ""


def _card(a: Assessment, data: StationData, now: datetime) -> str:
    color = _STATUS.get(a.verdict, "#8a94a6")
    arrow = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": "·"}[a.trend]
    val = _fmt(a.value, a.unit) if a.value is not None else "—"
    rel = _rel_time(a.updated, now)
    best = f'<p class="best">🕐 {html.escape(a.best_time)}</p>' if a.best_time else ""
    basis = f'<div class="gbasis">zones: {html.escape(a.threshold_basis)}</div>' if a.threshold_basis else ""
    dim = "" if a.in_season else " dim"
    return f"""
    <article class="card{dim}" style="--accent:{color}">
      <header><h3>{html.escape(a.river)}</h3><span class="badge">{a.emoji} {_LABEL.get(a.verdict, a.verdict)}</span></header>
      <div class="topline"><span class="num">{val}</span><span class="trend">{arrow} {a.trend}</span>
        <span class="asof">{html.escape(rel)}</span></div>
      {_gauge(a)}
      {basis}
      {_chart(a, data)}
      {_forecast_chips(a)}
      <p class="headline">{html.escape(a.headline)}</p>
      <p class="outlook">{html.escape(a.outlook)}</p>
      {best}
      {_tags(a)}
      <footer><span>{html.escape(a.region)}</span><span>Station {html.escape(a.station)}</span></footer>
    </article>"""


# --------------------------------------------------------------------------- hero + summary
def _hero(assessments: list[Assessment]) -> str:
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    live = [a for a in assessments if a.verdict != "NO_DATA"]
    if not live:
        return '<div class="hero none"><b>No live data right now.</b> Check back shortly.</div>'
    # best: prefer GO (esp. in-season & dropping), then GET_READY, then closest
    def score(a):
        return (rank.get(a.verdict, 99), 0 if a.in_season else 1, 0 if a.trend == "falling" else 1)
    best = sorted(live, key=score)[0]
    if best.verdict in ("GO", "GET_READY"):
        c = _STATUS[best.verdict]
        return (f'<div class="hero" style="--h:{c}">'
                f'<span class="htag">{best.emoji} BEST BET</span>'
                f'<b>{html.escape(best.river)}</b> — {html.escape(best.headline)}'
                f'{("<br><span class=hbest>🕐 "+html.escape(best.best_time)+"</span>") if best.best_time else ""}'
                f'</div>')
    return (f'<div class="hero none">Nothing is prime right now. Closest: '
            f'<b>{html.escape(best.river)}</b> ({_LABEL[best.verdict]}) — {html.escape(best.headline)}</div>')


def _summary(assessments: list[Assessment]) -> str:
    counts = {}
    for a in assessments:
        counts[a.verdict] = counts.get(a.verdict, 0) + 1
    tiles = "".join(
        f'<div class="tile" style="--c:{_STATUS[v]}"><span class="tn">{counts[v]}</span>'
        f'<span class="tl">{_LABEL[v]}</span></div>' for v in VERDICT_ORDER if counts.get(v))
    return f'<div class="tiles">{tiles}</div>'


def render(results: list[tuple[Assessment, StationData, RainOutlook | None]], generated: str) -> str:
    now = datetime.now(timezone.utc)
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    assessments = [a for a, _, _ in results]

    # group by region; regions ordered by their best verdict
    regions: dict[str, list] = {}
    for a, d, _ in results:
        regions.setdefault(a.region or "Other", []).append((a, d))
    def region_rank(items):
        return min(rank.get(a.verdict, 99) for a, _ in items)
    ordered_regions = sorted(regions.items(), key=lambda kv: (region_rank(kv[1]), kv[0]))

    sections = []
    for region, items in ordered_regions:
        items.sort(key=lambda t: rank.get(t[0].verdict, 99))
        cards = "\n".join(_card(a, d, now) for a, d in items)
        sections.append(f'<section><h2 class="region">{html.escape(region)}</h2><div class="grid">{cards}</div></section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>BC Salmon River Conditions</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f7fa; --fg:#0f172a; --card:#ffffff;
           --muted:#5b6472; --line:#e3e8ef; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1017; --fg:#e6eaf1; --card:#161b24; --muted:#93a0b4; --line:#232b38; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          background:var(--bg); color:var(--fg); -webkit-text-size-adjust:100%; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:20px 14px 56px; }}
  h1 {{ font-size:1.5rem; margin:0 0 2px; }}
  .sub {{ color:var(--muted); margin:0 0 14px; font-size:.86rem; }}
  .hero {{ border-radius:14px; padding:14px 16px; margin:0 0 16px; background:var(--card);
           border:1px solid var(--line); border-left:5px solid var(--h,#8a94a6); font-size:1rem; }}
  .hero.none {{ --h:#8a94a6; color:var(--fg); }}
  .htag {{ display:inline-block; font-size:.66rem; font-weight:800; letter-spacing:.06em; color:var(--h);
           margin-right:8px; }}
  .hbest {{ font-size:.82rem; color:var(--muted); }}
  .tiles {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px; }}
  .tile {{ display:flex; flex-direction:column; align-items:center; min-width:70px; background:var(--card);
           border:1px solid var(--line); border-top:3px solid var(--c); border-radius:10px; padding:7px 11px; }}
  .tile .tn {{ font-size:1.4rem; font-weight:800; }}
  .tile .tl {{ font-size:.6rem; font-weight:700; letter-spacing:.04em; color:var(--muted); }}
  .region {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
             margin:18px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
  .grid {{ display:grid; gap:14px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
           border-radius:12px; padding:15px; }}
  .card.dim {{ opacity:.72; }}
  .card header {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; }}
  .card h3 {{ font-size:1.05rem; margin:0; }}
  .badge {{ font-size:.68rem; font-weight:800; letter-spacing:.04em; color:#fff; background:var(--accent);
            padding:3px 9px; border-radius:999px; white-space:nowrap; }}
  .topline {{ display:flex; align-items:baseline; gap:10px; margin:9px 0 8px; }}
  .num {{ font-size:1.7rem; font-weight:800; }}
  .trend {{ font-size:.82rem; color:var(--muted); }}
  .asof {{ margin-left:auto; font-size:.72rem; color:var(--muted); }}
  .gauge {{ position:relative; height:12px; border-radius:6px; overflow:hidden; margin:2px 0 2px;
            background:var(--line); }}
  .gmark {{ position:absolute; top:-3px; width:3px; height:18px; background:var(--fg); border-radius:2px;
            transform:translateX(-1.5px); box-shadow:0 0 0 2px var(--card); }}
  .glabels {{ display:flex; justify-content:space-between; font-size:.58rem; color:var(--muted);
              margin:0 0 2px; letter-spacing:.03em; }}
  .gbasis {{ font-size:.6rem; color:var(--muted); margin:0 0 8px; font-style:italic; }}
  .chart {{ width:100%; height:auto; margin:2px 0 6px; }}
  .chart-empty {{ font-size:.75rem; color:var(--muted); padding:22px 0; text-align:center; }}
  .ax {{ fill:var(--muted); font-size:8px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 8px; }}
  .chip {{ font-size:.72rem; font-weight:600; border:1px solid var(--c); border-left:4px solid var(--c);
           border-radius:6px; padding:2px 7px; }}
  .skill {{ font-size:.66rem; color:var(--muted); align-self:center; }}
  .headline {{ margin:5px 0; font-weight:650; font-size:.95rem; }}
  .outlook {{ margin:5px 0; font-size:.84rem; color:var(--muted); }}
  .best {{ margin:6px 0; font-size:.8rem; background:color-mix(in srgb, var(--accent) 10%, transparent);
           border-radius:8px; padding:6px 9px; }}
  .tags {{ display:flex; flex-wrap:wrap; gap:5px; margin:8px 0 2px; }}
  .tag {{ font-size:.66rem; color:var(--muted); background:var(--line); border-radius:5px; padding:1px 6px; }}
  .tag.off {{ background:transparent; border:1px dashed var(--muted); }}
  .card footer {{ display:flex; justify-content:space-between; font-size:.68rem; color:var(--muted);
                  margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }}
  .legend {{ font-size:.72rem; color:var(--muted); margin:22px 0 0; display:flex; gap:16px; flex-wrap:wrap; }}
  .legend span::before {{ content:""; display:inline-block; width:14px; height:3px; margin-right:5px; vertical-align:middle; }}
  .lg-obs::before {{ background:{_SERIES}; }}
  .lg-fc::before {{ background-image:repeating-linear-gradient(90deg,{_SERIES} 0 4px,transparent 4px 7px); }}
  .lg-zone::before {{ background:{_STATUS['GO']}; opacity:.4; height:10px; }}
  .foot {{ margin-top:24px; font-size:.76rem; color:var(--muted); text-align:center; }}
  a {{ color:inherit; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎣 BC Salmon River Conditions</h1>
  <p class="sub">Live level/flow · 1-3 day ML forecast · rain outlook. Updated {html.escape(generated)}.
     Auto-refreshes every 30 min. Not a safety guarantee — check conditions yourself.</p>
  {_hero(assessments)}
  {_summary(assessments)}
  {"".join(sections)}
  <div class="legend">
    <span class="lg-obs">observed</span>
    <span class="lg-fc">forecast (1-3 d)</span>
    <span class="lg-zone">good zone</span>
  </div>
  <p class="foot">Water: Environment and Climate Change Canada (wateroffice.ec.gc.ca).
     Rain: Open-Meteo. Forecast: ridge regression trained per station.
     Thresholds are estimates — calibrate in config/rivers.yaml.</p>
</div>
</body>
</html>"""
