"""Per-event impact scorers. Pure functions: no I/O, no global state."""

from __future__ import annotations

from collections.abc import Mapping

from impact.classify import PRFacts, ReviewFacts
from impact.ownership import Ownership

CRITICAL_MULTIPLIER = 3.0
MIGRATION_MULTIPLIER = 1.5
TEAM_REACH_COEFFICIENT = 0.5
AUTONOMOUS_DISCOUNT = 0.6
FOREIGN_CODE_MULTIPLIER = 2.0

MIGRATION_MARKERS = ("clickhouse/migrations/", "/migrations/", "persons_migrations/")


def touches_critical(pr: PRFacts, own: Ownership) -> bool:
    return any(own.is_critical(p) for p in pr.paths)


def _is_migration(pr: PRFacts) -> bool:
    return any(marker in p for p in pr.paths for marker in MIGRATION_MARKERS)


def _teams_touched(pr: PRFacts, own: Ownership) -> int:
    teams: set[str] = set()
    for path in pr.paths:
        teams |= own.teams_for(path)
    return len(teams)


def _counts(pr: PRFacts) -> bool:
    return not pr.is_bot_author and not pr.is_stack_layer


def blast_radius(pr: PRFacts, own: Ownership) -> float:
    if not _counts(pr):
        return 0.0
    score = 1.0
    if touches_critical(pr, own):
        score *= CRITICAL_MULTIPLIER
    if _is_migration(pr):
        score *= MIGRATION_MULTIPLIER
    score *= 1.0 + TEAM_REACH_COEFFICIENT * _teams_touched(pr, own)
    if pr.autonomy == "fully_autonomous":
        score *= AUTONOMOUS_DISCOUNT
    return score


def fix_forward(pr: PRFacts, own: Ownership, prior_feat_author: Mapping[str, str]) -> float:
    if not _counts(pr) or pr.pr_type != "fix":
        return 0.0
    score = 1.0
    if touches_critical(pr, own):
        score *= CRITICAL_MULTIPLIER
    if any(prior_feat_author.get(p, pr.author) != pr.author for p in pr.paths):
        score *= FOREIGN_CODE_MULTIPLIER
    return score


CHANGES_REQUESTED_MULTIPLIER = 1.5
OUTSIDE_TEAM_MULTIPLIER = 2.0
THREAD_COEFFICIENT = 0.1


def review_leverage(
    pr: PRFacts,
    rev: ReviewFacts,
    own: Ownership,
    reviewer_home_teams: frozenset[str],
) -> float:
    if rev.is_bot or pr.is_bot_author or rev.author == pr.author or not rev.author:
        return 0.0
    score = 1.0
    if touches_critical(pr, own):
        score *= CRITICAL_MULTIPLIER
    touched_teams: set[str] = set()
    for path in pr.paths:
        touched_teams |= own.teams_for(path)
    if touched_teams and not (touched_teams & reviewer_home_teams):
        score *= OUTSIDE_TEAM_MULTIPLIER
    if rev.state == "CHANGES_REQUESTED":
        score *= CHANGES_REQUESTED_MULTIPLIER
    score *= 1.0 + THREAD_COEFFICIENT * pr.review_threads
    return score


def review_latency_hours(pr: PRFacts, rev: ReviewFacts) -> float | None:
    if rev.submitted_at is None or rev.is_bot:
        return None
    hours = (rev.submitted_at - pr.created_at).total_seconds() / 3600.0
    return hours if hours >= 0 else None


GOVERNANCE_BASENAMES = (
    "AGENTS.md",
    "SKILL.md",
    "owners.yaml",
    "CODEOWNERS",
    "AI_POLICY.md",
    "CONTRIBUTING.md",
    "pull_request_template.md",
)
TOOLING_PREFIXES = (".github/workflows/", "tools/", "bin/", "cli/")
GOVERNS_CRITICAL_MULTIPLIER = 2.0


def _is_governance(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in GOVERNANCE_BASENAMES or path.startswith(TOOLING_PREFIXES)


def _governs_critical(path: str, own: Ownership) -> bool:
    if own.is_critical(path):
        return True
    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    return bool(directory) and own.is_critical(f"{directory}/_probe")


def force_multiplier(pr: PRFacts, own: Ownership) -> float:
    if not _counts(pr):
        return 0.0
    total = 0.0
    for path in pr.paths:
        if not _is_governance(path):
            continue
        total += GOVERNS_CRITICAL_MULTIPLIER if _governs_critical(path, own) else 1.0
    return total
