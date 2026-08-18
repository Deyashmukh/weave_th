"""Wire the stages together. The only module in the package that touches disk."""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from impact import axes as ax
from impact.classify import PRFacts, pr_facts
from impact.ownership import Ownership, load_ownership
from impact.score import (
    AXES,
    TOP_N,
    WEIGHTS,
    composite,
    eligible,
    normalize,
    normalize_inverse_log,
    sensitivity,
)

EVIDENCE_PER_AXIS = 3

# The pagination walk reached this updatedAt, and GitHub guarantees
# updatedAt >= mergedAt, so coverage is provably complete from here forward.
# The raw file also holds PRs merged slightly earlier, whose coverage is
# partial - reporting min(mergedAt) would claim completeness we do not have.
COMPLETE_FROM = "2026-04-28T00:00:00+00:00"


def load_ownership_dir(ownership_dir: Path) -> Ownership:
    owners = {
        p.name.replace("__", "/"): p.read_text()
        for p in sorted((ownership_dir / "owners").glob("*.yaml"))
    }
    return load_ownership((ownership_dir / "CODEOWNERS").read_text(), owners)


def _home_teams(prs: list[PRFacts], own: Ownership) -> dict[str, frozenset[str]]:
    tally: dict[str, Counter[str]] = defaultdict(Counter)
    for pr in prs:
        if pr.is_bot_author or pr.is_stack_layer:
            continue
        for path in pr.paths:
            tally[pr.author].update(own.teams_for(path))
    home: dict[str, frozenset[str]] = {}
    for login, counts in tally.items():
        total = sum(counts.values())
        home[login] = frozenset(t for t, n in counts.items() if total and n / total >= 0.20)
    return home


def build_report(raw_path: Path, ownership_dir: Path) -> dict[str, Any]:
    own = load_ownership_dir(ownership_dir)
    prs = [pr_facts(json.loads(line)) for line in raw_path.read_text().splitlines() if line.strip()]
    prs.sort(key=lambda p: p.merged_at)

    home = _home_teams(prs, own)
    tallies: dict[str, dict[str, float]] = {name: defaultdict(float) for name in AXES}
    latencies: dict[str, list[float]] = defaultdict(list)
    pr_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    evidence: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    prior_feat_author: dict[str, str] = {}

    for pr in prs:
        if not pr.is_bot_author and not pr.is_stack_layer:
            pr_counts[pr.author] += 1
        # Evaluated eagerly rather than as lambdas: the closures captured the
        # loop variable `pr` (ruff B023) and were untyped calls under mypy
        # --strict. They were only ever invoked in the same iteration, so
        # calling them directly is identical in behaviour and safe to refactor.
        for name, value in (
            ("blast_radius", ax.blast_radius(pr, own)),
            ("force_multiplier", ax.force_multiplier(pr, own)),
            ("fix_forward", ax.fix_forward(pr, own, prior_feat_author)),
        ):
            if value > 0:
                tallies[name][pr.author] += value
                evidence[pr.author][name].append(
                    {"number": pr.number, "title": pr.title_snippet(), "score": round(value, 2)}
                )
        # Update *after* scoring so a fix is judged against the state before it.
        if pr.pr_type == "feat" and not pr.is_bot_author:
            for path in pr.paths:
                prior_feat_author[path] = pr.author

        for rev in pr.reviews:
            value = ax.review_leverage(pr, rev, own, home.get(rev.author, frozenset()))
            if value > 0:
                tallies["review_leverage"][rev.author] += value
                review_counts[rev.author] += 1
                evidence[rev.author]["review_leverage"].append(
                    {"number": pr.number, "title": pr.title_snippet(), "score": round(value, 2)}
                )
            hours = ax.review_latency_hours(pr, rev)
            if hours is not None and not rev.is_bot and rev.author != pr.author:
                latencies[rev.author].append(hours)

    pool, halved = eligible(pr_counts, review_counts)
    median_latency = {k: statistics.median(v) for k, v in latencies.items() if len(v) >= 5}

    normalized: dict[str, dict[str, float]] = {}
    for name in AXES:
        if name == "unblocking_speed":
            source = {k: v for k, v in median_latency.items() if k in pool}
            normalized[name] = normalize_inverse_log(source)
        else:
            source = {k: v for k, v in tallies[name].items() if k in pool}
            normalized[name] = normalize(source)

    totals = composite(normalized, WEIGHTS)
    sens = sensitivity(normalized, WEIGHTS)
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))

    engineers = [
        {
            "login": login,
            "composite": round(score, 1),
            "rank": i + 1,
            "axes": {name: round(normalized[name].get(login, 0.0), 1) for name in AXES},
            "raw": {
                "merged_prs": pr_counts.get(login, 0),
                "reviews_given": review_counts.get(login, 0),
                "median_review_hours": round(median_latency.get(login, 0.0), 1),
            },
            "evidence": {
                name: sorted(items, key=lambda e: -e["score"])[:EVIDENCE_PER_AXIS]
                for name, items in evidence.get(login, {}).items()
            },
        }
        for i, (login, score) in enumerate(ranked)
    ]

    return {
        "window": {
            "start": COMPLETE_FROM,
            "end": max(p.merged_at for p in prs).isoformat(),
            "days": 112,
        },
        "totals": {
            "prs_fetched": len(prs),
            "merged_to_master": sum(1 for p in prs if not p.is_stack_layer),
            "stack_layers_excluded": sum(1 for p in prs if p.is_stack_layer),
            "bot_authored_excluded": sum(1 for p in prs if p.is_bot_author),
            "eligible_engineers": len(pool),
            "eligibility_fallback_fired": halved,
        },
        "weights": WEIGHTS,
        "engineers": engineers[:TOP_N],
        "all_ranked": [{"login": e["login"], "composite": e["composite"]} for e in engineers],
        "sensitivity": sens,
        "caveats": ["c1", "c2", "c3", "c4", "c5"],
    }


def main() -> int:
    report = build_report(Path("data/raw/prs.jsonl"), Path("data/ownership"))
    Path("data/scored.json").write_text(json.dumps(report, indent=2))
    print(f"top {TOP_N}: " + ", ".join(e["login"] for e in report["engineers"]))
    print(f"sensitivity stable: {report['sensitivity']['stable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
