"""Render the scored report as one self-contained HTML page.

No external requests: the audience is a busy engineering leader opening a link,
and a page that depends on a CDN is a page that can fail in front of them.

Colours are categorical slots 1-5 of the validated default palette, in fixed
order. They were not chosen by eye - the first attempt here used hand-picked
greens and purples and failed CVD separation at delta-E 1.7, which is
indistinguishable to a protanope. These pass every gate in both modes.
"""

from __future__ import annotations

import html
import json
from typing import Any

AXIS_LABELS = {
    "blast_radius": "Blast radius",
    "review_leverage": "Review leverage",
    "force_multiplier": "Force multiplier",
    "unblocking_speed": "Unblocking speed",
    "fix_forward": "Fix-forward",
}
AXIS_COLORS = {
    "blast_radius": "#2a78d6",
    "review_leverage": "#eb6834",
    "force_multiplier": "#1baf7a",
    "unblocking_speed": "#eda100",
    "fix_forward": "#e87ba4",
}
LEAD_TIE_POINTS = 8.0

AXIS_COLORS_DARK = {
    "blast_radius": "#3987e5",
    "review_leverage": "#d95926",
    "force_multiplier": "#199e70",
    "unblocking_speed": "#c98500",
    "fix_forward": "#d55181",
}


def why_line(engineer: dict[str, Any]) -> str:
    """One sentence telling an engineering leader why this person ranks where they do.

    Shown under each name, and realistically the only prose most readers will
    actually read. Two decisions shape it.

    First, near-ties are named rather than broken. `rnegron` and `Gilbert09` sit
    0.9 composite points apart for entirely different reasons - one maxes force
    multiplier, the other blast radius and fix-forward - so collapsing each card
    to a single "strongest axis" would imply a precision the scores do not have.
    Axes within LEAD_TIE_POINTS of the top are reported together.

    Second, a raw figure is appended where one exists, because "3.1h median
    review" lands harder than "unblocking speed 60/100" for a reader who has not
    read the methodology and never will.

    No em dashes: PostHog's own AGENTS.md bans them in user-facing copy as an AI
    tell, and this page is about PostHog.
    """
    axes = engineer["axes"]
    ranked = sorted(axes, key=lambda k: -float(axes[k]))
    top, second = ranked[0], ranked[1]
    raw = engineer["raw"]

    detail = {
        "blast_radius": f"{raw['merged_prs']} PRs to master",
        "review_leverage": f"{raw['reviews_given']} reviews given",
        "unblocking_speed": f"{raw['median_review_hours']}h median review",
        "fix_forward": f"{raw['merged_prs']} PRs to master",
    }.get(top)

    # Force multiplier has no single raw counter, so a card led by it would carry
    # no concrete figure at all. Fall back to the runner-up's stat rather than
    # leave the strongest engineer with the thinnest line on the page.
    if detail is None:
        detail = {
            "blast_radius": f"{raw['merged_prs']} PRs to master",
            "review_leverage": f"{raw['reviews_given']} reviews given",
            "unblocking_speed": f"{raw['median_review_hours']}h median review",
            "fix_forward": f"{raw['merged_prs']} PRs to master",
        }.get(second)

    tied = float(axes[top]) - float(axes[second]) <= LEAD_TIE_POINTS
    lead = (
        f"{AXIS_LABELS[top].lower()} and {AXIS_LABELS[second].lower()}"
        if tied
        else AXIS_LABELS[top].lower()
    )
    return f"Leads on {lead}" + (f", {detail}." if detail else ".")


def _axis_vars(colors: dict[str, str]) -> str:
    return "".join(f"  --{name.replace('_', '-')}: {hexv};\n" for name, hexv in colors.items())


def _card(engineer: dict[str, Any]) -> str:
    """One ranked card: rank, name, why, stacked composition bar, raw counts, score.

    Segment widths are the axis score scaled by its weight share, so the bar
    reads as the composition of the composite rather than five unrelated bars.
    """
    axes = engineer["axes"]
    total = sum(axes.values()) or 1.0
    segments = "".join(
        f'<span class="seg" style="flex:{axes[name] / total:.4f};'
        f'background:var(--{name.replace("_", "-")})" '
        f'title="{AXIS_LABELS[name]}: {axes[name]}"></span>'
        for name in AXIS_LABELS
        if axes[name] > 0
    )
    raw = engineer["raw"]
    return f"""
      <button class="card" data-login="{html.escape(engineer["login"])}" aria-current="false">
        <span class="rank">{engineer["rank"]}</span>
        <span class="body">
          <span class="name">{html.escape(engineer["login"])}</span>
          <span class="why">{html.escape(why_line(engineer))}</span>
          <span class="bar">{segments}</span>
          <span class="raw">{raw["merged_prs"]} PRs merged &middot;
            {raw["reviews_given"]} reviews given &middot;
            {raw["median_review_hours"]}h median review</span>
        </span>
        <span class="score">{engineer["composite"]}</span>
      </button>"""


def _legend(weights: dict[str, float]) -> str:
    return "".join(
        f'<span class="key"><i style="background:var(--{n.replace("_", "-")})"></i>'
        f"{AXIS_LABELS[n]} <b>{int(weights[n])}</b></span>"
        for n in AXIS_LABELS
    )


def render(report: dict[str, Any]) -> str:
    totals, sens, weights = report["totals"], report["sensitivity"], report["weights"]
    cards = "".join(_card(e) for e in report["engineers"])
    caveats = "".join(f"<li>{html.escape(c)}</li>" for c in report["caveats"])
    stability = (
        f"Top 5 held across all {sens['variants_tested']} weight perturbations (±10)."
        if sens["stable"]
        else f"UNSTABLE. {sens['variants_tested']} perturbations (±10) moved "
        f"{', '.join(sens['churn'])} in or out of the top 5."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PostHog &mdash; most impactful engineers</title>
<style>
:root {{
  color-scheme: light;
  --surface-0:#f4f2ef; --surface-1:#fcfcfb; --line:#e4e0da;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#86837c;
{_axis_vars(AXIS_COLORS)}}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --surface-0:#111110; --surface-1:#1a1a19; --line:#33322f;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8e8c84;
{_axis_vars(AXIS_COLORS_DARK)}  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface-0:#111110; --surface-1:#1a1a19; --line:#33322f;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8e8c84;
{_axis_vars(AXIS_COLORS_DARK)}}}
*{{box-sizing:border-box}}
body{{margin:0;height:100vh;overflow:hidden;display:grid;grid-template-rows:auto 1fr auto;
  background:var(--surface-0);color:var(--text-primary);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
header{{padding:16px 24px 12px;background:var(--surface-1);border-bottom:1px solid var(--line)}}
h1{{margin:0;font-size:18px;letter-spacing:-.01em}}
.sub{{color:var(--text-secondary);font-size:12.5px;margin-top:4px;max-width:none}}
.legend{{margin-top:9px;display:flex;flex-wrap:wrap;gap:4px 16px}}
.key{{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--text-secondary)}}
.key i{{width:10px;height:10px;border-radius:3px;display:inline-block;flex:none}}
.key b{{color:var(--text-muted);font-weight:600;font-variant-numeric:tabular-nums}}
main{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px;padding:18px 24px;min-height:0}}
.col{{display:flex;flex-direction:column;gap:10px;min-height:0}}
.card{{display:grid;grid-template-columns:30px 1fr auto;gap:14px;align-items:center;
  text-align:left;padding:12px 14px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-1);cursor:pointer;font:inherit;color:inherit;
  transition:border-color .12s,box-shadow .12s}}
.card:hover{{border-color:var(--text-muted)}}
.card[aria-current="true"]{{border-color:var(--text-primary);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--text-primary) 10%,transparent)}}
.rank{{font-size:20px;font-weight:700;color:var(--text-muted);text-align:center;
  font-variant-numeric:tabular-nums}}
.body{{display:flex;flex-direction:column;min-width:0}}
.name{{font-weight:650;font-size:15px}}
.why{{color:var(--text-secondary);font-size:12.5px;margin:2px 0 7px}}
.bar{{display:flex;gap:2px;height:8px}}
.seg{{border-radius:2px;min-width:3px}}
.seg:first-child{{border-radius:4px 2px 2px 4px}}
.seg:last-child{{border-radius:2px 4px 4px 2px}}
.raw{{color:var(--text-muted);font-size:11.5px;margin-top:7px}}
.score{{font-size:23px;font-weight:700;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em}}
.panel{{border:1px solid var(--line);border-radius:10px;background:var(--surface-1);
  padding:16px 18px;overflow:auto;min-height:0}}
.panel h2{{margin:0 0 12px;font-size:15px}}
.axrow{{display:grid;grid-template-columns:112px 1fr 34px;gap:10px;align-items:center;
  margin-bottom:7px;font-size:12.5px;color:var(--text-secondary)}}
.axbar{{height:8px;background:var(--surface-0);border-radius:4px;overflow:hidden}}
.axfill{{display:block;height:100%;border-radius:4px}}
.axval{{text-align:right;font-variant-numeric:tabular-nums;color:var(--text-primary);
  font-weight:600}}
.ev{{margin:14px 0 0;padding:0;list-style:none;font-size:12.5px}}
.ev li{{padding:6px 0;border-top:1px solid var(--line);color:var(--text-secondary)}}
.ev a{{color:var(--text-primary);font-variant-numeric:tabular-nums}}
.ev em{{font-style:normal;color:var(--text-muted)}}
footer{{padding:10px 24px;background:var(--surface-1);border-top:1px solid var(--line);
  font-size:11.5px;color:var(--text-muted);display:grid;
  grid-template-columns:auto 1fr;gap:24px;align-items:start}}
footer ul{{margin:0;padding-left:15px;columns:2;column-gap:24px}}
footer li{{margin-bottom:1px}}
.stab{{color:var(--text-secondary);font-weight:600}}
</style></head><body>
<header>
  <h1>Who is most impactful in the PostHog repo</h1>
  <div class="sub">Impact is the risk a person absorbs and the leverage they create,
    not the volume they emit. {totals["merged_to_master"]:,} PRs merged to
    <code>master</code> across {report["window"]["days"]} days;
    {totals["stack_layers_excluded"]:,} stack layers and
    {totals["bot_authored_excluded"]:,} bot-authored PRs excluded;
    {totals["eligible_engineers"]} engineers eligible.</div>
  <div class="legend">{_legend(weights)}</div>
</header>
<main>
  <div class="col" id="cards">{cards}</div>
  <div class="panel" id="panel"></div>
</main>
<footer>
  <div><span class="stab">Sensitivity</span><br>{html.escape(stability)}</div>
  <div><span class="stab">Caveats</span><ul>{caveats}</ul></div>
</footer>
<script id="report" type="application/json">{json.dumps(report)}</script>
<script>
const REPORT = JSON.parse(document.getElementById('report').textContent);
const LABELS = {json.dumps(AXIS_LABELS)};
const panel = document.getElementById('panel');

function show(login) {{
  const e = REPORT.engineers.find(x => x.login === login);
  document.querySelectorAll('.card').forEach(c =>
    c.setAttribute('aria-current', String(c.dataset.login === login)));
  // Numeric values here are the relief the palette validator requires for the
  // three light-mode hues that fall below 3:1 contrast.
  const rows = Object.keys(LABELS).map(k => `
    <div class="axrow"><span>${{LABELS[k]}}</span>
      <span class="axbar"><span class="axfill" style="width:${{e.axes[k]}}%;
        background:var(--${{k.replace(/_/g,'-')}})"></span></span>
      <span class="axval">${{e.axes[k]}}</span></div>`).join('');
  const ev = Object.entries(e.evidence || {{}}).flatMap(([axis, items]) => items.map(i =>
    `<li><em>${{LABELS[axis]}}</em> &middot;
      <a href="https://github.com/PostHog/posthog/pull/${{i.number}}"
         target="_blank" rel="noopener">#${{i.number}}</a> ${{i.title}}</li>`)).join('');
  panel.innerHTML = `<h2>${{e.login}} &mdash; why</h2>${{rows}}
    <ul class="ev">${{ev || '<li>No evidence recorded.</li>'}}</ul>`;
}}

document.querySelectorAll('.card').forEach(c =>
  c.addEventListener('click', () => show(c.dataset.login)));
if (REPORT.engineers.length) show(REPORT.engineers[0].login);
</script>
</body></html>"""
