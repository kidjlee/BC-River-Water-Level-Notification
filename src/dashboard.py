"""Generate docs/index.html — a mobile-first, installable dashboard.

Per river: verdict, current value + trend, a level gauge, and an INTERACTIVE
1-year history chart you can scrub (touch/drag) to read the level on any day.
No forecasting — current conditions + history only. Installable as an iPhone
home-screen web app (Add to Home Screen from Safari).
"""
from __future__ import annotations

import html
import json
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
_ZONE = {"low": "#2f74d0", "good": "#2e9e5b", "high": "#d97706", "blown": "#d64545"}
_MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt(v: float, unit: str) -> str:
    return f"{v:.3f} m" if unit == "m" else f"{v:,.0f} cms"


def _short(v: float, unit: str) -> str:
    if unit == "cms":
        return f"{v/1000:.1f}k" if abs(v) >= 1000 else f"{v:.0f}"
    return f"{v:.2f}"


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
        return f"{int(mins/60)}h ago"
    return f"{int(mins/1440)}d ago"


def _gauge(a: Assessment) -> str:
    if a.value is None:
        return ""
    gl, gh, bl = a.good_low, a.good_high, a.blown_out
    lo, hi = min(gl, a.value), max(bl, a.value)
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0
    pct = lambda v: max(0.0, min(100.0, (v - lo) / span * 100))
    segs = [(lo, gl, _ZONE["low"]), (gl, gh, _ZONE["good"]), (gh, bl, _ZONE["high"]), (bl, hi, _ZONE["blown"])]
    bars = "".join(f'<div style="position:absolute;left:{pct(s):.1f}%;width:{pct(e)-pct(s):.1f}%;top:0;bottom:0;'
                   f'background:{c};opacity:.55"></div>' for s, e, c in segs if e > s)
    return (f'<div class="gauge">{bars}<div class="gmark" style="left:{pct(a.value):.1f}%"></div></div>'
            f'<div class="glabels"><span>low</span><span>good</span><span>high</span><span>blown</span></div>')


def _history_chart(a: Assessment, series: list, w: int = 320, h: int = 150) -> str:
    """Interactive 1-year daily chart: scrub with touch/mouse to read any day."""
    pts = [(d, v) for d, v in (series or []) if v is not None]
    today = datetime.now(timezone.utc).date().isoformat()
    if a.value is not None and (not pts or pts[-1][0] != today):
        pts = pts + [(today, a.value)]
    if len(pts) < 5:
        return '<div class="chart-empty">history is still building…</div>'

    ys = [v for _, v in pts]
    lo, hi = min(ys + [a.good_low]), max(ys + [a.good_high])
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0
    pl, pr, pt, pb = 36, 10, 12, 20
    iw, ih = w - pl - pr, h - pt - pb
    n = len(pts)
    x = lambda i: pl + (i / (n - 1)) * iw
    y = lambda v: pt + ih - ((v - lo) / span) * ih

    band = (f'<rect x="{pl}" y="{y(a.good_high):.1f}" width="{iw}" height="{max(y(a.good_low)-y(a.good_high),0):.1f}" '
            f'fill="{_ZONE["good"]}" opacity="0.14"/>')
    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))

    # month ticks, spaced so labels never bunch (min ~42px apart)
    ticks, last_lbl_x, last_m = "", -999, None
    for i, (d, _) in enumerate(pts):
        m = d[:7]
        if m != last_m:
            last_m = m
            xx = x(i)
            if xx - last_lbl_x >= 42:
                last_lbl_x = xx
                ticks += (f'<line x1="{xx:.1f}" y1="{pt}" x2="{xx:.1f}" y2="{h-pb}" stroke="var(--line)" stroke-width="1"/>'
                          f'<text x="{xx:.1f}" y="{h-6}" class="ax" text-anchor="middle">{_MON[int(d[5:7])]}</text>')
    ylab = (f'<text x="4" y="{y(hi)+7:.0f}" class="ax">{_short(hi, a.unit)}</text>'
            f'<text x="4" y="{(pt+ih/2):.0f}" class="ax">{_short((hi+lo)/2, a.unit)}</text>'
            f'<text x="4" y="{y(lo):.0f}" class="ax">{_short(lo, a.unit)}</text>')

    # data for the JS scrubber: pixel x/y + human date + value label
    def datelabel(d):
        try:
            return datetime.fromisoformat(d).strftime("%b %-d, %Y")
        except ValueError:
            return d
    data = [[round(x(i), 1), round(y(v), 1), datelabel(d), _fmt(v, a.unit)] for i, (d, v) in enumerate(pts)]
    lo_v, hi_v = min(ys), max(ys)
    rng = f'1-yr range {_fmt(lo_v, a.unit)} – {_fmt(hi_v, a.unit)}'

    return (f'<div class="chartwrap">'
            f'<svg class="ichart" viewBox="0 0 {w} {h}" data-w="{w}" data-h="{h}" '
            f"data-pts='{json.dumps(data)}' role='img' aria-label='1 year of daily {a.metric}, scrub to read a day'>"
            f'{band}{ticks}{ylab}'
            f'<polyline fill="none" stroke="{_SERIES}" stroke-width="1.6" stroke-linejoin="round" points="{line}"/>'
            f'<line class="cross" x1="0" y1="{pt}" x2="0" y2="{h-pb}" stroke="var(--fg)" stroke-width="1" opacity="0"/>'
            f'<circle class="cdot" r="3.5" fill="{_SERIES}" stroke="var(--card)" stroke-width="1.5" opacity="0"/>'
            f'</svg><div class="tip" hidden></div></div>'
            f'<div class="crange">{rng} · <span class="muted">scrub the chart to read any day</span></div>')


def _tags(a: Assessment) -> str:
    sp = "".join(f'<span class="tag">{html.escape(s)}</span>' for s in (a.species or [])[:5])
    off = "" if a.in_season else '<span class="tag off">off-season</span>'
    return f'<div class="tags">{off}{sp}</div>' if (sp or off) else ""


def _card(a: Assessment, now: datetime, actuals: dict | None) -> str:
    color = _STATUS.get(a.verdict, "#8a94a6")
    arrow = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": "·"}[a.trend]
    val = _fmt(a.value, a.unit) if a.value is not None else "—"
    rel = _rel_time(a.updated, now)
    basis = f'<div class="gbasis">zones: {html.escape(a.threshold_basis)}</div>' if a.threshold_basis else ""
    warn = (f'<p class="warn">⚠️ {a.gauge_quality} gauge — {html.escape(a.gauge_note)}. '
            f'Treat with caution.</p>') if a.gauge_quality not in ("OK", "") else ""
    best = f'<p class="best">🕐 {html.escape(a.best_time)}</p>' if a.best_time else ""
    series = (actuals or {}).get("series", [])
    dim = "" if a.in_season else " dim"
    return f"""
    <article class="card{dim}" style="--accent:{color}">
      <header><h3>{html.escape(a.river)}</h3><span class="badge">{a.emoji} {_LABEL.get(a.verdict, a.verdict)}</span></header>
      <div class="topline"><span class="num">{val}</span><span class="trend">{arrow} {a.trend}</span>
        <span class="asof">{html.escape(rel)}</span></div>
      {_gauge(a)}{basis}
      {_history_chart(a, series)}
      <p class="headline">{html.escape(a.headline)}</p>
      {warn}
      <p class="outlook">{html.escape(a.outlook)}</p>
      {best}
      {_tags(a)}
      <footer><span>{html.escape(a.region)}</span><span>Station {html.escape(a.station)}</span></footer>
    </article>"""


def _hero(assessments: list[Assessment]) -> str:
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    live = [a for a in assessments if a.verdict != "NO_DATA"]
    if not live:
        return '<div class="hero none"><b>No live data right now.</b> Check back shortly.</div>'
    best = sorted(live, key=lambda a: (rank.get(a.verdict, 99), 0 if a.in_season else 1,
                                       0 if a.trend == "falling" else 1))[0]
    if best.verdict in ("GO", "GET_READY"):
        return (f'<div class="hero" style="--h:{_STATUS[best.verdict]}">'
                f'<span class="htag">{best.emoji} BEST BET</span><b>{html.escape(best.river)}</b> — '
                f'{html.escape(best.headline)}'
                f'{("<br><span class=hbest>🕐 "+html.escape(best.best_time)+"</span>") if best.best_time else ""}</div>')
    return (f'<div class="hero none">Nothing is prime right now. Closest: '
            f'<b>{html.escape(best.river)}</b> ({_LABEL[best.verdict]}) — {html.escape(best.headline)}</div>')


def _summary(assessments: list[Assessment]) -> str:
    counts = {}
    for a in assessments:
        counts[a.verdict] = counts.get(a.verdict, 0) + 1
    tiles = "".join(f'<div class="tile" style="--c:{_STATUS[v]}"><span class="tn">{counts[v]}</span>'
                    f'<span class="tl">{_LABEL[v]}</span></div>' for v in VERDICT_ORDER if counts.get(v))
    return f'<div class="tiles">{tiles}</div>'


_JS = """
document.querySelectorAll('.ichart').forEach(function(svg){
  var pts=JSON.parse(svg.dataset.pts), W=+svg.dataset.w;
  var wrap=svg.closest('.chartwrap'), tip=wrap.querySelector('.tip');
  var cross=svg.querySelector('.cross'), dot=svg.querySelector('.cdot');
  function move(clientX){
    var r=svg.getBoundingClientRect(); var vx=(clientX-r.left)/r.width*W;
    var best=0,bd=1e9; for(var i=0;i<pts.length;i++){var d=Math.abs(pts[i][0]-vx); if(d<bd){bd=d;best=i;}}
    var p=pts[best];
    cross.setAttribute('x1',p[0]); cross.setAttribute('x2',p[0]); cross.style.opacity=0.5;
    dot.setAttribute('cx',p[0]); dot.setAttribute('cy',p[1]); dot.style.opacity=1;
    tip.hidden=false; tip.innerHTML='<b>'+p[3]+'</b><br>'+p[2];
    var px=p[0]/W*r.width; tip.style.left=Math.max(4,Math.min(px-tip.offsetWidth/2,r.width-tip.offsetWidth-4))+'px';
  }
  function end(){ cross.style.opacity=0; dot.style.opacity=0; tip.hidden=true; }
  svg.addEventListener('pointermove',function(e){move(e.clientX);});
  svg.addEventListener('pointerdown',function(e){move(e.clientX);});
  svg.addEventListener('pointerleave',end);
  svg.addEventListener('touchstart',function(e){move(e.touches[0].clientX);},{passive:true});
  svg.addEventListener('touchmove',function(e){move(e.touches[0].clientX); e.preventDefault();},{passive:false});
  svg.addEventListener('touchend',end);
});
"""


def render(results, generated: str, actuals: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    actuals = actuals or {}
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    assessments = [a for a, _, _ in results]

    regions: dict[str, list] = {}
    for a, _, _ in results:
        regions.setdefault(a.region or "Other", []).append(a)
    ordered = sorted(regions.items(),
                     key=lambda kv: (min(rank.get(a.verdict, 99) for a in kv[1]), kv[0]))
    sections = []
    for region, items in ordered:
        items.sort(key=lambda a: rank.get(a.verdict, 99))
        cards = "\n".join(_card(a, now, actuals.get(a.station)) for a in items)
        sections.append(f'<section><h2 class="region">{html.escape(region)}</h2><div class="grid">{cards}</div></section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="refresh" content="1800">
<title>BC Salmon River Conditions</title>
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#0d1017">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="BC Salmon">
<link rel="apple-touch-icon" href="icon-180.png">
<style>
  :root {{ color-scheme: light dark; --bg:#f5f7fa; --fg:#0f172a; --card:#fff; --muted:#5b6472; --line:#e3e8ef; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1017; --fg:#e6eaf1; --card:#161b24; --muted:#93a0b4; --line:#232b38; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          background:var(--bg); color:var(--fg); -webkit-text-size-adjust:100%; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:max(20px,env(safe-area-inset-top)) 14px 56px; }}
  h1 {{ font-size:1.5rem; margin:0 0 2px; }}
  .sub {{ color:var(--muted); margin:0 0 14px; font-size:.85rem; }}
  .hero {{ border-radius:14px; padding:14px 16px; margin:0 0 16px; background:var(--card); border:1px solid var(--line);
           border-left:5px solid var(--h,#8a94a6); }}
  .hero.none {{ --h:#8a94a6; }}
  .htag {{ font-size:.66rem; font-weight:800; letter-spacing:.06em; color:var(--h); margin-right:8px; }}
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
  .gauge {{ position:relative; height:12px; border-radius:6px; overflow:hidden; margin:2px 0; background:var(--line); }}
  .gmark {{ position:absolute; top:-3px; width:3px; height:18px; background:var(--fg); border-radius:2px;
            transform:translateX(-1.5px); box-shadow:0 0 0 2px var(--card); }}
  .glabels {{ display:flex; justify-content:space-between; font-size:.58rem; color:var(--muted); margin:0 0 8px; }}
  .gbasis {{ font-size:.6rem; color:var(--muted); font-style:italic; margin:-4px 0 8px; }}
  .chartwrap {{ position:relative; touch-action:pan-y; }}
  .ichart {{ width:100%; height:auto; display:block; touch-action:pan-y; }}
  .ax {{ fill:var(--muted); font-size:8px; }}
  .chart-empty {{ font-size:.75rem; color:var(--muted); padding:26px 0; text-align:center; }}
  .tip {{ position:absolute; top:2px; background:var(--fg); color:var(--bg); font-size:.7rem; line-height:1.25;
          padding:4px 7px; border-radius:6px; pointer-events:none; white-space:nowrap; box-shadow:0 1px 4px rgba(0,0,0,.3); }}
  .crange {{ font-size:.66rem; color:var(--muted); margin:2px 0 8px; }}
  .muted {{ color:var(--muted); }}
  .headline {{ margin:6px 0; font-weight:650; font-size:.95rem; }}
  .outlook {{ margin:5px 0; font-size:.84rem; color:var(--muted); }}
  .warn {{ margin:6px 0; font-size:.78rem; color:#b45309; background:color-mix(in srgb,#d97706 12%,transparent);
           border-radius:8px; padding:6px 9px; }}
  @media (prefers-color-scheme: dark) {{ .warn {{ color:#f0b866; }} }}
  .best {{ margin:6px 0; font-size:.8rem; background:color-mix(in srgb, var(--accent) 10%, transparent);
           border-radius:8px; padding:6px 9px; }}
  .tags {{ display:flex; flex-wrap:wrap; gap:5px; margin:8px 0 2px; }}
  .tag {{ font-size:.66rem; color:var(--muted); background:var(--line); border-radius:5px; padding:1px 6px; }}
  .tag.off {{ background:transparent; border:1px dashed var(--muted); }}
  .card footer {{ display:flex; justify-content:space-between; font-size:.68rem; color:var(--muted);
                  margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }}
  .foot {{ margin-top:24px; font-size:.76rem; color:var(--muted); text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎣 BC Salmon River Conditions</h1>
  <p class="sub">Live level/flow + 1-year history. Updated {html.escape(generated)}.
     Scrub any chart to read a day. Add to Home Screen for an app. Not a safety guarantee.</p>
  {_hero(assessments)}
  {_summary(assessments)}
  {"".join(sections)}
  <p class="foot">Water: Environment and Climate Change Canada (wateroffice.ec.gc.ca). Rain: Open-Meteo.
     Thresholds calibrated per month from each station's history.</p>
</div>
<script>{_JS}</script>
</body>
</html>"""
