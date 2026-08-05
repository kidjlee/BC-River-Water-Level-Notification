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

from . import regulations as regs
from .analyze import Assessment, BC_TZ, VERDICT_ORDER
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


def _history_chart(a: Assessment, series: list, data: StationData | None = None) -> str:
    """Emit raw daily data + a 7d/30d/1yr toggle; JS draws & handles scrubbing.

    Bridges ECCC's daily-mean lag (finalized ~weeks late) with the live
    real-time readings, so the recent 7d/30d windows show current days.
    """
    pts = [[d, round(v, 3)] for d, v in (series or []) if v is not None]
    last_daily = pts[-1][0] if pts else "0000-00-00"
    # append recent days derived from the live feed (daily mean), after the daily series
    if data is not None:
        buckets: dict[str, list] = {}
        for ts, v in data.series(a.metric):
            buckets.setdefault(ts.astimezone(BC_TZ).date().isoformat(), []).append(v)
        for d in sorted(buckets):
            if d > last_daily:
                pts.append([d, round(sum(buckets[d]) / len(buckets[d]), 3)])
    today = datetime.now(timezone.utc).astimezone(BC_TZ).date().isoformat()
    if a.value is not None and (not pts or pts[-1][0] != today):
        pts = pts + [[today, round(a.value, 3)]]
    if len(pts) < 5:
        return '<div class="chart-empty">history is still building…</div>'
    return (f'<div class="chartwrap" data-gl="{a.good_low}" data-gh="{a.good_high}" '
            f'data-unit="{a.unit}" data-series=\'{json.dumps(pts)}\'>'
            f'<div class="rangebtns">'
            f'<button type="button" data-r="7">7d</button>'
            f'<button type="button" data-r="30" class="on">30d</button>'
            f'<button type="button" data-r="366">1&nbsp;yr</button></div>'
            f'<svg class="ichart" role="img" aria-label="daily {a.metric} history, scrub to read a day"></svg>'
            f'<div class="tip" hidden></div><div class="crange"></div></div>')


def _tags(a: Assessment) -> str:
    sp = "".join(f'<span class="tag">{html.escape(s)}</span>' for s in (a.species or [])[:5])
    off = "" if a.in_season else '<span class="tag off">off-season</span>'
    return f'<div class="tags">{off}{sp}</div>' if (sp or off) else ""


def _readings(a: Assessment, now: datetime) -> str:
    """Both raw gauge readings, laid out the way Water Office reports them.

    The verdict rides on one metric, but anglers cross-check the station page,
    which always lists level and discharge together. A station that publishes
    only one of the two shows "—" rather than being silently dropped.
    """
    lvl = f"{a.level_m:.3f} m" if a.level_m is not None else "—"
    dis = f"{a.discharge_cms:,.3f} m³/s" if a.discharge_cms is not None else "—"
    stamp = a.level_at or a.discharge_at
    when = f'<div class="rwhen">as of {html.escape(_rel_time(stamp, now))}</div>' if stamp else ""
    return (
        '<div class="readings">'
        f'<div class="r"><span class="rk">Most Recent Water Level</span>'
        f'<span class="rv">{lvl}</span></div>'
        f'<div class="r"><span class="rk">Most Recent Discharge</span>'
        f'<span class="rv">{dis}</span></div>'
        f"</div>{when}"
    )


def _rules(a: Assessment, all_regs: dict, today) -> str:
    """DFO's rules for this river, with today's in force pulled to the top.

    A river with no entry on the Region 2 page renders nothing — plenty of our
    gauges sit outside that region (Cowichan, Skeena) or simply aren't listed,
    and inventing a rule for them would be worse than staying quiet.
    """
    entries = regs.for_river(all_regs, a.dfo_waters)
    if not entries:
        return ""
    active, rest = regs.split_active(entries, today)

    def row(e, live):
        shut = regs.is_closure(e)
        cls = "rule" + (" on" if live else "") + (" shut" if shut and live else "")
        return (f'<div class="{cls}"><span class="rsp">{html.escape(e["species"])}</span>'
                f'<span class="rdt">{html.escape(e["dates"])}</span>'
                f'<span class="rlm">{html.escape(e["limit"])}</span></div>')

    now_html = "".join(row(e, True) for e in active) or \
        '<div class="rule"><span class="rsp">—</span><span class="rlm">nothing open today</span></div>'
    later = "".join(row(e, False) for e in rest)
    later_html = (f'<details class="rmore"><summary>rest of the year '
                  f'({len(rest)})</summary>{later}</details>') if rest else ""

    areas = [e["area"] for e in entries if e.get("area")]
    area = ""
    if areas:
        seen = list(dict.fromkeys(areas))
        area = (f'<div class="rarea">Applies to: {html.escape(" / ".join(seen))}</div>')
    return (f'<div class="rules"><div class="ruleshead">DFO rules — in force today</div>'
            f'{now_html}{later_html}{area}</div>')


def _card(a: Assessment, now: datetime, actuals: dict | None, data: StationData | None = None,
          all_regs: dict | None = None) -> str:
    color = _STATUS.get(a.verdict, "#8a94a6")
    arrow = {"rising": "↑", "falling": "↓", "steady": "→", "unknown": "·"}[a.trend]
    val = _fmt(a.value, a.unit) if a.value is not None else "—"
    rel = _rel_time(a.updated, now)
    basis = f'<div class="gbasis">zones: {html.escape(a.threshold_basis)}</div>' if a.threshold_basis else ""
    warn = (f'<p class="warn">⚠️ {a.gauge_quality} gauge — {html.escape(a.gauge_note)}. '
            f'Treat with caution.</p>') if a.gauge_quality not in ("OK", "") else ""
    best = f'<p class="best">🕐 {html.escape(a.best_time)}</p>' if a.best_time else ""
    readings = _readings(a, now)
    rules = _rules(a, all_regs or {}, now.astimezone(BC_TZ).date())
    series = (actuals or {}).get("series", [])
    chart = _history_chart(a, series, data)
    dim = "" if a.in_season else " dim"
    return f"""
    <article class="card{dim}" style="--accent:{color}">
      <header><h3>{html.escape(a.river)}</h3><span class="badge">{a.emoji} {_LABEL.get(a.verdict, a.verdict)}</span></header>
      <div class="topline"><span class="num">{val}</span><span class="trend">{arrow} {a.trend}</span>
        <span class="asof">{html.escape(rel)}</span></div>
      {_gauge(a)}{basis}
      {readings}
      {chart}
      <p class="headline">{html.escape(a.headline)}</p>
      {warn}
      <p class="outlook">{html.escape(a.outlook)}</p>
      {best}
      {rules}
      {_tags(a)}
      <footer><span>{html.escape(a.region)}</span><span>Station {html.escape(a.station)}</span></footer>
    </article>"""


def _dfo_general(all_regs: dict) -> str:
    """Region-wide limits, collapsed. These bind everywhere in Region 2, so they
    belong once at page level rather than repeated on all eighteen cards."""
    rules = all_regs.get("general") or []
    if not rules:
        return ""
    items = "".join(f"<li>{html.escape(r)}</li>" for r in rules)
    src = html.escape(all_regs.get("source", ""))
    when = html.escape(all_regs.get("date_modified") or "unknown")
    return (f'<details class="dfo"><summary>Region 2 rules that apply everywhere</summary>'
            f'<ul>{items}</ul>'
            f'<div class="src">Source: <a href="{src}">DFO Region 2 notice</a> · '
            f'page last modified {when}. Always confirm before you fish.</div></details>')


def _hero(assessments: list[Assessment]) -> str:
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    all_regs = regs.load()
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
var MON=['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
var W=320,H=170,PL=36,PR=10,PT=12,PB=22;
function fmtDate(d){var p=d.split('-');return MON[+p[1]]+' '+(+p[2])+', '+p[0];}
function draw(wrap,range){
  var all=JSON.parse(wrap.dataset.series), gl=+wrap.dataset.gl, gh=+wrap.dataset.gh, unit=wrap.dataset.unit;
  // window by CALENDAR DAYS (not point count), so gaps don't drag in old dates
  var lastMs=new Date(all[all.length-1][0]+'T00:00:00Z').getTime();
  var cut=lastMs-(range-1)*86400000;
  var pts=all.filter(function(p){return new Date(p[0]+'T00:00:00Z').getTime()>=cut;});
  if(pts.length<2) pts=all.slice(-2);
  var n=pts.length;
  var ys=pts.map(function(p){return p[1];});
  var lo=Math.min.apply(null,ys.concat([gl])), hi=Math.max.apply(null,ys.concat([gh]));
  var pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad; var span=(hi-lo)||1;
  var iw=W-PL-PR, ih=H-PT-PB;
  var X=function(i){return PL+(n===1?iw/2:(i/(n-1))*iw);};
  var Y=function(v){return PT+ih-((v-lo)/span)*ih;};
  var fmt=unit==='m'?function(v){return v.toFixed(3)+' m';}:function(v){return Math.round(v).toLocaleString()+' cms';};
  var sh=unit==='cms'?function(v){return Math.abs(v)>=1000?(v/1000).toFixed(1)+'k':''+Math.round(v);}:function(v){return v.toFixed(2);};
  var monthMode=range>60, s='';
  s+='<rect x="'+PL+'" y="'+Y(gh).toFixed(1)+'" width="'+iw+'" height="'+Math.max(Y(gl)-Y(gh),0).toFixed(1)+'" fill="#2e9e5b" opacity="0.14"/>';
  var lastX=-999,lastKey=null;
  for(var i=0;i<n;i++){var d=pts[i][0]; var key=monthMode?d.slice(0,7):d;
    if(key!==lastKey){lastKey=key; var xx=X(i);
      if(xx-lastX>=42){lastX=xx; var lbl=monthMode?MON[+d.slice(5,7)]:(+d.slice(5,7))+'/'+(+d.slice(8,10));
        s+='<line x1="'+xx.toFixed(1)+'" y1="'+PT+'" x2="'+xx.toFixed(1)+'" y2="'+(H-PB)+'" stroke="var(--line)"/>';
        s+='<text x="'+xx.toFixed(1)+'" y="'+(H-6)+'" class="ax" text-anchor="middle">'+lbl+'</text>';}}}
  s+='<text x="4" y="'+(Y(hi)+7).toFixed(0)+'" class="ax">'+sh(hi)+'</text>';
  s+='<text x="4" y="'+(PT+ih/2).toFixed(0)+'" class="ax">'+sh((hi+lo)/2)+'</text>';
  s+='<text x="4" y="'+Y(lo).toFixed(0)+'" class="ax">'+sh(lo)+'</text>';
  var gapMax=range>60?3:1.5, seg=[], segs=[];  // break the line across real data gaps
  for(var j=0;j<n;j++){
    if(j>0){var gd=(new Date(pts[j][0]+'T00:00:00Z')-new Date(pts[j-1][0]+'T00:00:00Z'))/86400000; if(gd>gapMax){segs.push(seg);seg=[];}}
    seg.push(X(j).toFixed(1)+','+Y(pts[j][1]).toFixed(1));
  }
  segs.push(seg);
  segs.forEach(function(sg){
    if(sg.length>1) s+='<polyline fill="none" stroke="#2563eb" stroke-width="1.8" stroke-linejoin="round" points="'+sg.join(' ')+'"/>';
    else if(sg.length===1){var xy=sg[0].split(','); s+='<circle cx="'+xy[0]+'" cy="'+xy[1]+'" r="1.8" fill="#2563eb"/>';}
  });
  s+='<line class="cross" y1="'+PT+'" y2="'+(H-PB)+'" stroke="var(--fg)" stroke-width="1.5" opacity="0"/>';
  s+='<circle class="cdot" r="5" fill="#2563eb" stroke="var(--card)" stroke-width="2" opacity="0"/>';
  s+='<rect class="hit" x="0" y="0" width="'+W+'" height="'+H+'" fill="transparent"/>';
  var svg=wrap.querySelector('svg'); svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.innerHTML=s;
  svg._pts=pts.map(function(p,i){return [X(i),Y(p[1]),fmtDate(p[0]),fmt(p[1])];}); svg._W=W;
  var lo2=Math.min.apply(null,ys), hi2=Math.max.apply(null,ys);
  var label=range<=7?'last 7 days':range<=30?'last 30 days':'last year';
  wrap.querySelector('.crange').innerHTML=label+' · range '+fmt(lo2)+' – '+fmt(hi2)+' · <span class="muted">scrub to read a day</span>';
}
function scrub(svg,clientX){
  var pts=svg._pts; if(!pts) return; var r=svg.getBoundingClientRect(); var vx=(clientX-r.left)/r.width*svg._W;
  var best=0,bd=1e9; for(var i=0;i<pts.length;i++){var dx=Math.abs(pts[i][0]-vx); if(dx<bd){bd=dx;best=i;}}
  var p=pts[best], cross=svg.querySelector('.cross'), dot=svg.querySelector('.cdot'), tip=svg.parentNode.querySelector('.tip');
  cross.setAttribute('x1',p[0]); cross.setAttribute('x2',p[0]); cross.style.opacity=0.5;
  dot.setAttribute('cx',p[0]); dot.setAttribute('cy',p[1]); dot.style.opacity=1;
  tip.hidden=false; tip.innerHTML='<b>'+p[3]+'</b><br>'+p[2];
  var px=p[0]/svg._W*r.width; tip.style.left=Math.max(4,Math.min(px-tip.offsetWidth/2,r.width-tip.offsetWidth-4))+'px';
}
document.querySelectorAll('.chartwrap').forEach(function(wrap){
  var svg=wrap.querySelector('svg');
  draw(wrap,30);
  wrap.querySelectorAll('.rangebtns button').forEach(function(b){
    b.addEventListener('click',function(){
      wrap.querySelectorAll('.rangebtns button').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on'); draw(wrap,+b.dataset.r);
    });
  });
  function end(){var c=svg.querySelector('.cross'),d=svg.querySelector('.cdot');if(c)c.style.opacity=0;if(d)d.style.opacity=0;wrap.querySelector('.tip').hidden=true;}
  svg.addEventListener('pointerdown',function(e){scrub(svg,e.clientX);});
  svg.addEventListener('pointermove',function(e){if(e.pressure>0||e.buttons)scrub(svg,e.clientX);else scrub(svg,e.clientX);});
  svg.addEventListener('pointerleave',end);
  svg.addEventListener('touchstart',function(e){scrub(svg,e.touches[0].clientX);},{passive:true});
  svg.addEventListener('touchmove',function(e){scrub(svg,e.touches[0].clientX);e.preventDefault();},{passive:false});
  svg.addEventListener('touchend',end);
});
"""


def render(results, generated: str, actuals: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    actuals = actuals or {}
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    all_regs = regs.load()
    assessments = [a for a, _, _ in results]

    regions: dict[str, list] = {}
    for a, d, _ in results:
        regions.setdefault(a.region or "Other", []).append((a, d))
    ordered = sorted(regions.items(),
                     key=lambda kv: (min(rank.get(a.verdict, 99) for a, _ in kv[1]), kv[0]))
    sections = []
    for region, items in ordered:
        items.sort(key=lambda t: rank.get(t[0].verdict, 99))
        cards = "\n".join(_card(a, now, actuals.get(a.station), d, all_regs) for a, d in items)
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
  .readings {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:8px 0 2px; }}
  .readings .r {{ background:rgba(255,255,255,.04); border:1px solid var(--line);
                  border-radius:8px; padding:6px 8px; min-width:0; }}
  .rk {{ display:block; font-size:.58rem; letter-spacing:.02em; color:var(--muted);
         text-transform:uppercase; }}
  .rv {{ display:block; font-size:.95rem; font-weight:650; font-variant-numeric:tabular-nums;
         margin-top:1px; }}
  .rwhen {{ font-size:.58rem; color:var(--muted); margin:3px 0 6px; }}
  .rules {{ margin:10px 0 2px; border-top:1px solid var(--line); padding-top:8px; }}
  .ruleshead {{ font-size:.58rem; font-weight:800; letter-spacing:.06em; text-transform:uppercase;
                color:var(--muted); margin-bottom:5px; }}
  .rule {{ display:grid; grid-template-columns:auto auto 1fr; gap:6px; align-items:baseline;
           font-size:.72rem; padding:3px 6px; border-radius:6px; border-left:3px solid transparent; }}
  .rule.on {{ background:rgba(46,158,91,.12); border-left-color:#2e9e5b; }}
  .rule.on.shut {{ background:rgba(214,69,69,.12); border-left-color:#d64545; }}
  .rule .rsp {{ font-weight:700; }}
  .rule .rdt {{ color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .rule .rlm {{ text-align:right; }}
  .rmore {{ margin-top:4px; }}
  .rmore summary {{ font-size:.64rem; color:var(--muted); cursor:pointer; padding:2px 6px; }}
  .rmore .rule {{ opacity:.75; }}
  .rarea {{ font-size:.58rem; color:var(--muted); margin:5px 0 0; line-height:1.4; }}
  .dfo {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:10px 14px; margin:0 0 16px; font-size:.76rem; }}
  .dfo summary {{ cursor:pointer; font-weight:700; }}
  .dfo ul {{ margin:8px 0 4px; padding-left:18px; color:var(--muted); }}
  .dfo li {{ margin:3px 0; }}
  .dfo .src {{ font-size:.62rem; color:var(--muted); margin-top:6px; }}
  .chartwrap {{ position:relative; }}
  .rangebtns {{ display:flex; gap:5px; justify-content:flex-end; margin:2px 0 2px; }}
  .rangebtns button {{ font:inherit; font-size:.68rem; font-weight:600; color:var(--muted); background:var(--bg);
                       border:1px solid var(--line); border-radius:999px; padding:3px 10px; cursor:pointer;
                       -webkit-tap-highlight-color:transparent; }}
  .rangebtns button.on {{ color:#fff; background:var(--accent); border-color:var(--accent); }}
  .ichart {{ width:100%; height:auto; display:block; touch-action:pan-y; cursor:crosshair; }}
  .ax {{ fill:var(--muted); font-size:8px; }}
  .chart-empty {{ font-size:.75rem; color:var(--muted); padding:26px 0; text-align:center; }}
  .tip {{ position:absolute; top:34px; background:var(--fg); color:var(--bg); font-size:.72rem; line-height:1.3;
          padding:5px 8px; border-radius:7px; pointer-events:none; white-space:nowrap; box-shadow:0 1px 6px rgba(0,0,0,.35); z-index:2; }}
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
  {_dfo_general(all_regs)}
  {_summary(assessments)}
  {"".join(sections)}
  <p class="foot">Water: Environment and Climate Change Canada (wateroffice.ec.gc.ca). Rain: Open-Meteo.
     Thresholds calibrated per month from each station's history.</p>
</div>
<script>{_JS}</script>
</body>
</html>"""
