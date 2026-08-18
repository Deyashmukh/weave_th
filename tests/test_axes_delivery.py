from datetime import UTC, datetime

from impact.axes import blast_radius, fix_forward
from impact.classify import PRFacts
from impact.ownership import Ownership, load_ownership

CODEOWNERS = """
posthog/clickhouse/migrations/** @PostHog/clickhouse
posthog/api/authentication.py @PostHog/team-security
"""
OWNERS = {
    "owners.yaml": """
version: 1
rules:
    - match: '/products/surveys/'
      owners: team-surveys
    - match: '/products/experiments/'
      owners: team-experiments
"""
}


def _own() -> Ownership:
    return load_ownership(CODEOWNERS, OWNERS)


def _pr(**kw: object) -> PRFacts:
    base = dict(
        number=1,
        title="feat(surveys): add response filter",
        author="alice",
        is_bot_author=False,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        merged_at=datetime(2026, 6, 2, tzinfo=UTC),
        base_ref="master",
        is_stack_layer=False,
        pr_type="feat",
        scope=None,
        autonomy="human_driven",
        paths=("products/surveys/backend/api.py",),
        files_truncated=False,
        additions=10,
        deletions=2,
        review_threads=0,
        reviews=(),
    )
    base.update(kw)
    return PRFacts(**base)  # type: ignore[arg-type]


def test_ordinary_pr_scores_base_weight() -> None:
    assert blast_radius(_pr(), _own()) == 1.5


def test_critical_path_triples_the_score() -> None:
    pr = _pr(paths=("posthog/api/authentication.py",))
    assert blast_radius(pr, _own()) == 3.0


def test_migration_path_adds_its_own_multiplier() -> None:
    pr = _pr(paths=("posthog/clickhouse/migrations/0099.sql",))
    assert blast_radius(pr, _own()) == 4.5


def test_cross_team_reach_scales_the_score() -> None:
    pr = _pr(paths=("products/surveys/a.py", "products/experiments/b.py"))
    assert blast_radius(pr, _own()) == 2.0


def test_fully_autonomous_is_discounted() -> None:
    solo = blast_radius(_pr(), _own())
    auto = blast_radius(_pr(autonomy="fully_autonomous"), _own())
    assert auto == solo * 0.6


def test_stack_layer_scores_zero() -> None:
    assert blast_radius(_pr(is_stack_layer=True, base_ref="feat/x"), _own()) == 0.0


def test_bot_authored_pr_scores_zero() -> None:
    assert blast_radius(_pr(is_bot_author=True), _own()) == 0.0


def test_fix_forward_only_counts_fix_prs() -> None:
    assert fix_forward(_pr(pr_type="feat"), _own(), {}) == 0.0


def test_fix_to_own_code_scores_less_than_fix_to_others() -> None:
    own = _own()
    path = "products/surveys/backend/api.py"
    mine = fix_forward(_pr(pr_type="fix"), own, {path: "alice"})
    theirs = fix_forward(_pr(pr_type="fix"), own, {path: "bob"})
    assert theirs == mine * 2.0


def test_fix_on_critical_path_is_weighted_highest() -> None:
    pr = _pr(pr_type="fix", paths=("posthog/api/authentication.py",))
    assert fix_forward(pr, _own(), {"posthog/api/authentication.py": "bob"}) == 6.0
