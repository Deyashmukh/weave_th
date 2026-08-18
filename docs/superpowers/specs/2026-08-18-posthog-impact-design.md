# Measuring engineer impact in the PostHog repo

**Status:** approved design, pending implementation plan
**Date:** 2026-08-18
**Repo under analysis:** [PostHog/posthog](https://github.com/PostHog/posthog)
**Window:** 2026-04-28 → 2026-08-18 (112 days; the brief requires ≥ 90)

## Problem

A busy PostHog engineering leader wants to know who the five most impactful
engineers are, and why, without reading PRs. They understand roughly what their
people do; they lack a defensible cross-team view.

Volume metrics — commits, lines, PR counts, review counts — fail here for
reasons specific to this repo, not just in the abstract. Section 2 shows that
each of them is measurably corrupted by PostHog's own tooling.

## 1. What "impact" means here

Impact is **the risk a person absorbs and the leverage they create for others**,
not the volume they emit.

Five axes, each normalized to 0–100 across eligible engineers, then combined by
a weighted sum. Normalization comes first because the raw units differ by orders
of magnitude, and an un-normalized sum would let review count swamp every other
axis.

| # | Axis | Weight | Question it answers |
|---|------|-------:|---------------------|
| 1 | Blast radius shipped | 30 | How much *risk-weighted* change did they land on `master`? |
| 2 | Review leverage | 25 | Whose judgment does the codebase actually rely on? |
| 3 | Unblocking speed | 15 | How much latency do they remove from other people's work? |
| 4 | Force multiplier | 20 | Did they change how everyone else (and every agent) works? |
| 5 | Fix-forward ownership | 10 | Who cleans up production breakage, especially other people's? |

Weights are provisional. They are pinned only after the first full scoring run,
and the dashboard ships a **sensitivity check**: the published top 5 must be
stable when every weight is perturbed ±10 points. If it is not stable, the
instability is reported rather than hidden.

### Axis 1 — Blast radius shipped (30)

Per PR merged into `master`, authored by a human:

```
base                1.0
× 3.0               if any changed path is CODEOWNERS-protected
× 1.5               if it is a migration (clickhouse / django / persons)
× (1 + 0.5 · T)     T = distinct owning teams whose paths the PR touches
× 0.6               if the PR declares "Fully autonomous"
```

The ×3.0 multiplier is **not invented**. `.github/CODEOWNERS` states that adding
an entry is "an anti-social and anti-posthog-values thing to do" requiring
"extraordinary justification." The ~15 surviving paths are therefore PostHog's
own declaration of where blast radius is real: ClickHouse migrations, HogQL,
`posthog/api/authentication.py`, `posthog/auth.py`, SCIM auth, the security CI
workflows, `rust/persons_migrations/`, the MCP store catalog, and the reviewer
assignment machinery itself.

Cross-team reach `T` is resolved from the 26 distributed `owners.yaml` files,
which map paths to 33 teams.

### Axis 2 — Review leverage (25)

Per review **given** to another human's PR:

```
base                1.0
× 3.0               review is on a CODEOWNERS-protected path
× 2.0               reviewer's own team does not own the touched paths
× 1.5               state = CHANGES_REQUESTED (caught something)
× (1 + threads/10)  review opened discussion rather than rubber-stamping
bot reviewers       excluded entirely
```

The ×2.0 term exists because reviewer assignment is automated:
`.github/workflows/auto-assign-reviewers.yml` fires on `opened` /
`ready_for_review` and assigns from CODEOWNERS + `owners.yaml`. Being *requested*
is a routing-table outcome. Reviewing outside your own team's paths is
voluntary, and that is what the multiplier rewards.

### Axis 3 — Unblocking speed (15)

Median hours from PR creation to the engineer's review, compared against the
repo baseline. Scored inversely — faster is better — and only for engineers
above the review-count eligibility bar, so a single lucky fast review cannot
top the axis.

Measured baseline across 15,222 timed human reviews: **median 13.5h, p25 1.5h,
p75 49.1h.** The 33× spread between quartiles is the widest of any signal in the
dataset, which is why this axis exists at all.

### Axis 4 — Force multiplier (20)

PRs that change the rules and tools everyone else runs on:

```
governance docs     AGENTS.md, SKILL.md, owners.yaml, CODEOWNERS,
                    AI_POLICY.md, CONTRIBUTING.md, pull_request_template.md
CI + tooling        .github/workflows/, tools/, bin/, cli/
× 2.0               when the doc governs a CODEOWNERS-protected path
                    (e.g. posthog/clickhouse/migrations/AGENTS.md)
```

`CLAUDE.md` files are **excluded**: all 44 are git symlinks (mode `120000`,
9 bytes) pointing at the sibling `AGENTS.md`. Counting both double-credits every
governance edit.

Measured reach: 44 `AGENTS.md`, 238 `SKILL.md`, 26 `owners.yaml`, 126 CI
workflows. A merged `SKILL.md` is executable governance — it changes what every
agent in the repo does next.

### Axis 5 — Fix-forward ownership (10)

```
fix(...) PRs merged to master
× 3.0               on a CODEOWNERS-protected path
× 2.0               fixing a path whose recent feat() came from someone else
```

Reverts are **not** scored: only 8 exist across 4,789 sampled master PRs
(0.17%) — too few to rank five people on. They appear as evidence cards.
Fix-forward is the right proxy because PostHog fixes forward rather than
reverting: `fix` is 45.5% of merged PRs against `feat` at 40.1%.

## 2. De-noising rules (why volume metrics fail here)

Three corrections, each derived from repo structure and each changing the
ranking materially:

1. **Stack layers.** 2.2% of merged PRs target another feature branch, not
   `master`. `AGENTS.md` instructs engineers to "stack instead of stuffing," so
   raw PR count rewards whoever decomposes worst. Only `baseRefName == "master"`
   counts as shipped.
2. **Bots.** Machine reviewers outnumber the busiest human reviewer roughly 8:1
   (`greptile-apps` 291, `stamphog` 289, `posthog` 260, `veria-ai` 169,
   `parameterai` 85, plus Copilot, Codex, Cursor, Graphite and a security bot,
   against 155 for the top human in the same sample). Ranking "reviews given"
   naively puts Greptile first. GraphQL `__typename == "Bot"` separates them.
   Labels are equally polluted: the two most common labels are bot-applied.
3. **Agent authorship.** The PR template requires an `Autonomy:` line reading
   either `Human-driven (agent-assisted)` or `Fully autonomous`. In a 597-PR
   sample: 74% human-driven, 11% fully autonomous, 11% no section. Per
   `AI_POLICY.md` ("you own what you submit"), human-driven work is credited
   fully to the human DRI; fully autonomous work is discounted to 0.6.

## 3. Eligibility

An engineer enters the ranking with **≥ 5 merged `master` PRs or ≥ 10 human
reviews given** in the window. The bar prevents a single high-multiplier PR from
topping a ratio axis.

These two thresholds are **pre-committed here, before any scoring run**, so they
cannot be tuned after seeing who they include or exclude. One fallback is
pre-committed with them: if the eligible pool comes out below 30 engineers, both
thresholds halve once, and the dashboard reports that the fallback fired. No
other adjustment is permitted after the first run.

## 4. Data pipeline

GitHub GraphQL only — the repo is 6.4 GB, so cloning is not viable, and REST
would need ~27k calls against a 5,000/hr limit. GraphQL costs 4 points per 100
PRs, putting the whole pull near 1,200 points.

Pagination walks merged PRs by `UPDATED_AT DESC` and halts once a page's oldest
`updatedAt` precedes the cutoff. Since GitHub guarantees `updatedAt >= mergedAt`,
this provably cannot skip a PR merged inside the window — worth stating because
sorting by update time surfaces PRs merged as far back as 2020.

**Achieved coverage.** The walk reached `updatedAt = 2026-04-28`, so every PR
merged on or after that date is captured: 15,058 PRs over 112 days. Two
independent checks confirm completeness. GitHub's search API reports 13,395 PRs
merged in the required 90-day window (2026-05-20 → 2026-08-18); this dataset
holds 13,380 of them, a 99.9% match, with the residual explained by PRs merged
while the fetch was in flight. The per-week merge counts are also smooth across
the interior of the window, with thin counts only at the two partial edge weeks,
which is the shape complete coverage produces.

The walk was halted at 112 days rather than the originally planned 120 because
deep cursors began returning HTTP 502s at a rate that made the last eight days
cost far more than they were worth. The window still exceeds the brief's
requirement by three weeks.

Stages: `fetch` (raw JSONL) → `enrich` (ownership resolution, bot classification,
autonomy parsing) → `score` (five axes + composite) → `render` (static dashboard).
Each stage is separately testable; `fetch` output is cached so scoring can be
re-run without re-hitting the API.

## 5. Dashboard

One page, one laptop screen (1440×900), no scrolling.

- **Header:** the impact definition in one sentence, plus window and PR count.
- **Top 5 cards:** name, composite score, and a five-segment bar showing the axis
  breakdown, so rank is self-explaining.
- **Why panel:** for the selected engineer, the concrete evidence — their
  highest-blast-radius PRs, critical-path reviews, governance docs authored,
  fixes to others' code. Titles link to GitHub.
- **Interaction:** click an engineer to swap the why panel; hover an axis segment
  for its formula. Weight sliders drive the sensitivity check live.
- **Honesty strip:** bots excluded, stack layers excluded, autonomy discount, and
  the org-membership caveat below.

## 6. Known limitations

- **Org membership is not visible.** `orgs/PostHog/members` returns 27 people;
  the rest is private. Employee vs. community contributor is therefore inferred
  from whether an author has ever *given* a review. This is stated on the
  dashboard, not hidden.
- **Repo-level branch protection is not readable** without admin (404). Merge
  rules are taken from `AGENTS.md`, which documents them authoritatively.
- **Reviews are capped at 30 per PR and files at 60** in the fetch. PRs exceeding
  those keep a `totalCount`, so truncation is detectable and reported.
- **Impact outside this repo is invisible** — design, incident command, mentoring
  in Slack, and work in PostHog's other repos do not appear. The dashboard says so.
- **Support Hero rotation** (per-team, weekly, documented in CONTRIBUTING) is real
  engineering load that leaves no trace in PR data.

## 7. Non-goals

No login, no database, no live API calls from the browser, no multi-page app, no
historical trend beyond the window. The deliverable is one static page plus a
reproducible pipeline.
