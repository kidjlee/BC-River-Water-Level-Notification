"""Generate a self-contained dashboard (docs/index.html).

One card per river: verdict, current level, trend, a sparkline of recent
levels, and the rain-driven outlook. No external assets — works offline and
can be served free via GitHub Pages (Settings -> Pages -> /docs).
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .analyze import Assessment, VERDICT_ORDER
from .sources import StationData
from .weather import RainOutlook

_COLORS = {
    "GO": "#2e9e5b",
    "GET_READY": "#c9a227",
    "MARGINAL": "#d97706",
    "TOO_LOW": "#3b82f6",
    "BLOWN_OUT": "#dc2626",
    "NO_DATA": "#9ca3af",
}
_LABEL = {
    "GO": "GO FISH",
    "GET_READY": "GET READY",
    "MARGINAL": "MARGINAL",
    "TOO_LOW": "TOO LOW",
    "BLOWN_OUT": "BLOWN OUT",
    "NO_DATA": "NO DATA",
}


def _sparkline(data: StationData, color: str, width: int = 220, height: int = 44) -> str:
    levels = [(r.timestamp, r.level_m) for r in data.readings if r.level_m is not None]
    if len(levels) < 2:
        return '<div class="spark-empty">no recent readings</div>'
    ys = [v for _, v in levels]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    n = len(ys)
    pts = []
    for i, y in enumerate(ys):
        px = (i / (n - 1)) * (width - 4) + 2
        py = height - 2 - ((y - lo) / span) * (height - 4)
        pts.append(f"{px:.1f},{py:.1f}")
    polyline = " ".join(pts)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'role="img" aria-label="recent water level trend">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{polyline}"/>'
        f"</svg>"
    )


def _card(a: Assessment, data: StationData, rain: RainOutlook | None) -> str:
    color = _COLORS.get(a.verdict, "#9ca3af")
    label = _LABEL.get(a.verdict, a.verdict)
    trend_arrow = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": "·"}[a.trend]
    level_txt = f"{a.level_m:.2f} m" if a.level_m is not None else "—"
    updated = ""
    if a.updated:
        try:
            dt = datetime.fromisoformat(a.updated).astimezone(timezone.utc)
            updated = dt.strftime("%b %d, %H:%M UTC")
        except ValueError:
            updated = a.updated
    return f"""
    <article class="card" style="--accent:{color}">
      <header>
        <h2>{html.escape(a.river)}</h2>
        <span class="badge">{a.emoji} {label}</span>
      </header>
      <div class="metrics">
        <div class="level"><span class="num">{level_txt}</span><span class="trend">{trend_arrow} {a.trend}</span></div>
        {_sparkline(data, color)}
      </div>
      <p class="headline">{html.escape(a.headline)}</p>
      <p class="outlook">{html.escape(a.outlook)}</p>
      <footer><span>Station {html.escape(a.station)}</span><span>{html.escape(updated)}</span></footer>
    </article>"""


def render(results: list[tuple[Assessment, StationData, RainOutlook | None]], generated: str) -> str:
    order = {v: i for i, v in enumerate(VERDICT_ORDER)}
    results = sorted(results, key=lambda t: order.get(t[0].verdict, 99))
    cards = "\n".join(_card(a, d, r) for a, d, r in results)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BC Salmon River Conditions</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f6f7f9; --fg:#111827; --card:#fff; --muted:#6b7280; --line:#e5e7eb; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --fg:#e5e7eb; --card:#171a21; --muted:#9ca3af; --line:#262b33; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 24px; font-size:.9rem; }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
           border-radius:12px; padding:16px; }}
  .card header {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; }}
  .card h2 {{ font-size:1.05rem; margin:0; }}
  .badge {{ font-size:.72rem; font-weight:700; letter-spacing:.04em; color:#fff;
            background:var(--accent); padding:3px 8px; border-radius:999px; white-space:nowrap; }}
  .metrics {{ display:flex; align-items:center; gap:12px; margin:12px 0 6px; }}
  .level {{ display:flex; flex-direction:column; }}
  .num {{ font-size:1.5rem; font-weight:700; }}
  .trend {{ font-size:.8rem; color:var(--muted); }}
  .spark {{ flex:1; height:44px; }}
  .spark-empty {{ flex:1; font-size:.75rem; color:var(--muted); }}
  .headline {{ margin:6px 0; font-weight:600; }}
  .outlook {{ margin:6px 0; font-size:.88rem; color:var(--muted); }}
  .card footer {{ display:flex; justify-content:space-between; font-size:.72rem;
                  color:var(--muted); margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }}
  .foot {{ margin-top:28px; font-size:.8rem; color:var(--muted); text-align:center; }}
  a {{ color:inherit; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎣 BC Salmon River Conditions</h1>
  <p class="sub">Live water levels + rain outlook. Updated {html.escape(generated)}.
     Green = go fish. Not a safety guarantee — always check conditions yourself.</p>
  <div class="grid">
    {cards}
  </div>
  <p class="foot">Water data: Environment and Climate Change Canada (wateroffice.ec.gc.ca).
     Rain: Open-Meteo. Thresholds are personal estimates — tune them in config/rivers.yaml.</p>
</div>
</body>
</html>"""
