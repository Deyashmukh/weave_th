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

WEIGHTS_FALLBACK = {
    "blast_radius": 30,
    "review_leverage": 25,
    "force_multiplier": 20,
    "unblocking_speed": 15,
    "fix_forward": 10,
}

AXIS_COLORS_DARK = {
    "blast_radius": "#3987e5",
    "review_leverage": "#d95926",
    "force_multiplier": "#199e70",
    "unblocking_speed": "#c98500",
    "fix_forward": "#d55181",
}


# What each axis measures and the exact arithmetic behind it. Single source of
# truth: the hover tooltips, the panel rows and the footer method block all read
# from here, so the published formula cannot drift from the one in axes.py.
AXIS_META: dict[str, dict[str, str]] = {
    "blast_radius": {
        "short": "Risk-weighted delivery on dangerous ground.",
        "captures": (
            "Rewards moving dangerous ground, not moving a lot of ground. A change to "
            "authentication or a ClickHouse migration counts far more than one to a "
            "product surface, and a change spanning several teams' code counts more "
            "than one confined to your own."
        ),
        "formula": (
            "1.0 per PR merged to master  ×3 if it touches a CODEOWNERS path  "
            "×1.5 if it is a migration  ×(1 + 0.5 per owning team touched)  "
            "×0.6 if declared fully autonomous"
        ),
    },
    "review_leverage": {
        "short": "Whose review judgement the codebase relies on.",
        "captures": (
            "Reviewer assignment here is automated, so being asked carries no signal. "
            "Choosing to review outside your own team's code does, and so does asking "
            "for changes rather than approving. Bot reviewers are excluded entirely: "
            "they outnumber the busiest human roughly 8 to 1."
        ),
        "formula": (
            "1.0 per review given to another human  ×3 on a CODEOWNERS path  "
            "×2 outside the reviewer's own team  ×1.5 for changes-requested  "
            "×(1 + threads ÷ 10)"
        ),
    },
    "force_multiplier": {
        "short": "Changes how everyone else, and every agent, works.",
        "captures": (
            "Edits to the rules and tooling the whole repo runs on: AGENTS.md, the 238 "
            "agent skills, ownership files, CI, and shared tooling. A merged skill is "
            "executable governance — it changes what every agent in the repo does next. "
            "None of this shows up in a feature count."
        ),
        "formula": (
            "1.0 per governance or tooling file changed (AGENTS.md, SKILL.md, "
            "owners.yaml, CODEOWNERS, .github/workflows, tools/, bin/, cli/)  "
            "×2 when that file governs a CODEOWNERS path"
        ),
    },
    "unblocking_speed": {
        "short": "Latency removed from other people's work.",
        "captures": (
            "The highest-variance signal in the dataset. Shipping volume varies about "
            "3× between engineers; review turnaround varies 33×. In a repo merging 150 "
            "PRs a day, reviewing in 1.5 hours instead of 49 removes days of waiting "
            "from other people's work while never appearing in your own PR count."
        ),
        "formula": (
            "Median hours from PR opened to their review, inverted on a log scale.  "
            "Repo baseline: p25 1.5h · median 13.5h · p75 49.1h"
        ),
    },
    "fix_forward": {
        "short": "Repairs shipped code, especially code they did not write.",
        "captures": (
            "Merging to master deploys to production, so repair work is real ownership. "
            "Picking up someone else's breakage counts double. Reverts are not scored: "
            "only 8 exist across 4,789 sampled PRs because PostHog fixes forward — "
            "45.5% of merged PRs are fixes against 40.1% features."
        ),
        "formula": (
            "1.0 per fix() PR merged to master  ×3 on a CODEOWNERS path  "
            "×2 when the path's most recent feat() came from someone else"
        ),
    },
}

COMPOSITE_NOTE = (
    "Each axis total is log1p-compressed, then scaled 0 to 100 across the 134 eligible "
    "engineers, so 100 is the best observed. Log scaling is load-bearing: one account "
    "merges 19.7 PRs a day, and on a linear scale it alone set the anchor."
)


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
        f'<span class="key" title="{html.escape(AXIS_META[n]["short"])}">'
        f'<i style="background:var(--{n.replace("_", "-")})"></i>'
        f"{AXIS_LABELS[n]} <b>{int(weights[n])}</b></span>"
        for n in AXIS_LABELS
    )


def _summary_block() -> str:
    """Fills the space under the lowest-ranked card with a quick metric key.

    The full definitions and formulas live in the method section below the fold;
    this is the at-a-glance version, so a reader knows what the five colours in
    every bar actually mean without leaving the first screen.
    """
    rows = "".join(
        f'<div class="sr"><i style="background:var(--{n.replace("_", "-")})"></i>'
        f'<span class="srn">{AXIS_LABELS[n]}</span>'
        f'<span class="srw">{int(WEIGHTS_FALLBACK.get(n, 0))}</span>'
        f'<span class="srd">{html.escape(AXIS_META[n]["short"])}</span></div>'
        for n in AXIS_LABELS
    )
    return (
        '<section class="summary"><div class="sh">What the five metrics mean'
        '<span class="shx">full formulas below &darr;</span></div>'
        f"{rows}</section>"
    )


def _method_block(weights: dict[str, float]) -> str:
    """The full method, rendered into the column beneath the ranked cards.

    Deliberately not a tooltip. Hover is unavailable on touch and invisible to
    anyone who does not think to try it, and the method is the substance of this
    analysis rather than a footnote to it.
    """
    rows = "".join(
        f'<article class="mx">'
        f'<div class="mxh"><i style="background:var(--{n.replace("_", "-")})"></i>'
        f'<span class="mxn">{AXIS_LABELS[n]}</span>'
        f'<span class="mxw">weight {int(weights[n])}</span>'
        f'<span class="mxs">{html.escape(AXIS_META[n]["short"])}</span></div>'
        f'<p class="mxc">{html.escape(AXIS_META[n]["captures"])}</p>'
        f'<p class="mxf">{html.escape(AXIS_META[n]["formula"])}</p>'
        f"</article>"
        for n in AXIS_LABELS
    )
    return (
        '<section class="method">'
        "<h2>How each metric is calculated</h2>"
        f'<p class="mxi">{html.escape(COMPOSITE_NOTE)}</p>'
        '<p class="mxf mxfc">score = &Sigma; (weight &times; axis) &divide; 100</p>'
        f'<div class="mxgrid">{rows}</div></section>'
    )


def render(report: dict[str, Any]) -> str:
    totals, sens, weights = report["totals"], report["sensitivity"], report["weights"]
    cards = "".join(_card(e) for e in report["engineers"])
    method = _method_block(weights)
    summary = _summary_block()
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
body{{margin:0;min-height:100vh;
  background:var(--surface-0);color:var(--text-primary);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
header{{padding:12px 24px 9px;background:var(--surface-1);border-bottom:1px solid var(--line)}}
h1{{margin:0;font-size:18px;letter-spacing:-.01em}}
.sub{{color:var(--text-secondary);font-size:12.5px;margin-top:3px;max-width:none}}
.legend{{margin-top:7px;display:flex;flex-wrap:wrap;gap:4px 16px}}
.key{{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--text-secondary)}}
.key i{{width:10px;height:10px;border-radius:3px;display:inline-block;flex:none}}
.key b{{color:var(--text-muted);font-weight:600;font-variant-numeric:tabular-nums}}
main{{display:grid;grid-template-columns:1.2fr 1fr;gap:18px;padding:13px 24px;min-height:0}}
.col{{display:flex;flex-direction:column;gap:8px;min-height:0}}
.card{{display:grid;grid-template-columns:30px 1fr auto;gap:14px;align-items:center;
  text-align:left;padding:9px 13px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-1);cursor:pointer;font:inherit;color:inherit;
  transition:border-color .12s,box-shadow .12s}}
.card:hover{{border-color:var(--text-muted)}}
.card[aria-current="true"]{{border-color:var(--text-primary);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--text-primary) 10%,transparent)}}
.rank{{font-size:20px;font-weight:700;color:var(--text-muted);text-align:center;
  font-variant-numeric:tabular-nums}}
.body{{display:flex;flex-direction:column;min-width:0}}
.name{{font-weight:650;font-size:15px}}
.why{{color:var(--text-secondary);font-size:12.5px;margin:1px 0 5px}}
.bar{{display:flex;gap:2px;height:8px}}
.seg{{border-radius:2px;min-width:3px}}
.seg:first-child{{border-radius:4px 2px 2px 4px}}
.seg:last-child{{border-radius:2px 4px 4px 2px}}
.raw{{color:var(--text-muted);font-size:11.5px;margin-top:5px}}
.score{{font-size:23px;font-weight:700;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em}}
.panel{{border:1px solid var(--line);border-radius:10px;background:var(--surface-1);
  padding:13px 16px;overflow:auto;min-height:0}}
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
footer{{padding:8px 24px 10px;background:var(--surface-1);border-top:1px solid var(--line);
  font-size:11.5px;color:var(--text-muted);display:grid;
  grid-template-columns:minmax(250px,0.8fr) minmax(420px,1fr);
  gap:22px;align-items:start}}
footer ul{{margin:3px 0 0;padding-left:14px;columns:2;column-gap:20px}}
footer li{{margin-bottom:2px}}
footer p{{margin:0 0 3px}}
.fcol{{min-width:0}}
.stab{{color:var(--text-secondary);font-weight:600;display:block;margin-bottom:3px}}
.hint{{font-weight:400;font-style:normal;color:var(--text-muted);font-size:10.5px}}
.fx{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
  color:var(--text-secondary);margin:0 0 4px}}
.fnote{{line-height:1.4}}
/* Pinned to one viewport so the dashboard honours the brief; the evidence panel
   scrolls inside it rather than growing the page. Genuinely small viewports get
   an escape hatch below, because clipping a card is worse than scrolling. */
.screen{{height:100vh;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}}
@media (max-height: 780px) {{
  .screen{{height:auto;overflow:visible}}
}}
.summary{{margin-top:8px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-1);padding:7px 12px 8px}}
.sh{{font-size:11.5px;font-weight:650;margin-bottom:4px;display:flex;
  justify-content:space-between;align-items:baseline;gap:10px}}
.shx{{font-weight:400;font-size:10.5px;color:var(--text-muted)}}
.sr{{display:grid;grid-template-columns:10px 104px 20px 1fr;gap:8px;
  align-items:baseline;font-size:11px;margin-bottom:1px}}
.sr i{{width:9px;height:9px;border-radius:2px;display:block;position:relative;top:1px}}
.srn{{color:var(--text-secondary)}}
.srw{{color:var(--text-muted);font-variant-numeric:tabular-nums;text-align:right}}
.srd{{color:var(--text-muted)}}
.method{{padding:26px 24px 40px;border-top:1px solid var(--line);background:var(--surface-1)}}
.method h2{{margin:0 0 6px;font-size:17px;letter-spacing:-.01em}}
.mxi{{margin:0 0 6px;font-size:13px;color:var(--text-secondary);line-height:1.5;
  max-width:760px}}
.mxgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));
  gap:0 30px;margin-top:14px}}
.mx{{padding:13px 0 14px;border-top:1px solid var(--line)}}
.mxh{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px}}
.mxh i{{width:10px;height:10px;border-radius:3px;flex:none}}
.mxn{{font-weight:650;font-size:13px}}
.mxw{{font-size:10.5px;color:var(--text-muted);border:1px solid var(--line);
  border-radius:20px;padding:1px 7px;white-space:nowrap}}
.mxs{{font-size:12px;color:var(--text-secondary)}}
.mxc{{margin:0 0 6px;font-size:12.5px;color:var(--text-secondary);line-height:1.5}}
.mxf{{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:11.5px;line-height:1.6;color:var(--text-muted);
  background:var(--surface-0);border-radius:6px;padding:7px 9px;
  overflow-wrap:anywhere}}
.mxfc{{margin-bottom:9px;color:var(--text-primary);font-size:12.5px}}

/* Short viewports cannot fit the summary under the cards, and .screen clips
   rather than scrolls, so half of it would vanish silently. Hide it outright;
   the full method section below the fold still carries every definition. */
@media (max-height: 860px) {{
  .summary{{display:none}}
}}

/* Phones: the desktop layout is a fixed-height two-column grid with hover-only
   formulas. Touch never fires a title tooltip, so the formula is rendered inline
   here instead, and the page is allowed to scroll. */
@media (max-width: 900px) {{
  body{{height:auto;min-height:100vh;overflow:visible;display:block}}
  header{{padding:13px 15px 10px}}
  h1{{font-size:16px}}
  .sub{{font-size:12px}}
  main{{grid-template-columns:1fr;padding:13px 15px;gap:13px}}
  .panel{{overflow:visible;max-height:none}}
  .col{{gap:9px}}
  .card{{grid-template-columns:24px 1fr auto;gap:10px;padding:11px 12px}}
  .rank{{font-size:17px}}
  .score{{font-size:20px}}
  .axrow{{grid-template-columns:104px 1fr 32px}}
  footer{{grid-template-columns:1fr;gap:15px;padding:13px 15px 20px}}
  .method{{padding:12px 13px}}
  .mxf{{font-size:11px}}
}}
</style></head><body>
<div class="screen">
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
  <div class="col" id="cards">{cards}{summary}</div>
  <div class="panel" id="panel"></div>
</main>
<footer>
  <div class="fcol">
    <span class="stab">Sensitivity</span>
    <p class="fnote">{html.escape(stability)}</p>
  </div>
  <div class="fcol">
    <span class="stab">Caveats</span><ul>{caveats}</ul>
  </div>
</footer>
</div>
{method}
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
