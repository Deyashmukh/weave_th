from datetime import UTC, datetime, timedelta

from impact.axes import review_latency_hours, review_leverage
from impact.classify import PRFacts, ReviewFacts
from impact.ownership import Ownership, load_ownership

CODEOWNERS = "posthog/api/authentication.py @PostHog/team-security\n"
OWNERS = {
    "owners.yaml": """
version: 1
rules:
    - match: '/products/surveys/'
      owners: team-surveys
"""
}
CREATED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _own() -> Ownership:
    return load_ownership(CODEOWNERS, OWNERS)


def _rev(**kw: object) -> ReviewFacts:
    base = dict(
        author="bob",
        is_bot=False,
        state="APPROVED",
        submitted_at=CREATED + timedelta(hours=4),
        body_len=120,
    )
    base.update(kw)
    return ReviewFacts(**base)  # type: ignore[arg-type]


def _pr(**kw: object) -> PRFacts:
    base = dict(
        number=1,
        title="feat(surveys): add response filter",
        author="alice",
        is_bot_author=False,
        created_at=CREATED,
        merged_at=CREATED + timedelta(days=1),
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


def test_bot_review_scores_zero() -> None:
    assert review_leverage(_pr(), _rev(is_bot=True), _own(), frozenset()) == 0.0


def test_self_review_scores_zero() -> None:
    assert review_leverage(_pr(), _rev(author="alice"), _own(), frozenset()) == 0.0


def test_review_inside_own_team_is_base_weight() -> None:
    assert review_leverage(_pr(), _rev(), _own(), frozenset({"surveys"})) == 1.0


def test_review_outside_own_team_is_doubled() -> None:
    assert review_leverage(_pr(), _rev(), _own(), frozenset({"experiments"})) == 2.0


def test_review_on_critical_path_is_tripled() -> None:
    pr = _pr(paths=("posthog/api/authentication.py",))
    assert review_leverage(pr, _rev(), _own(), frozenset({"security"})) == 3.0


def test_changes_requested_outweighs_approval() -> None:
    own, home = _own(), frozenset({"surveys"})
    approved = review_leverage(_pr(), _rev(state="APPROVED"), own, home)
    changed = review_leverage(_pr(), _rev(state="CHANGES_REQUESTED"), own, home)
    assert changed == approved * 1.5


def test_discussion_threads_raise_the_score() -> None:
    own, home = _own(), frozenset({"surveys"})
    quiet = review_leverage(_pr(review_threads=0), _rev(), own, home)
    noisy = review_leverage(_pr(review_threads=10), _rev(), own, home)
    assert noisy == quiet * 2.0


def test_latency_is_hours_between_open_and_review() -> None:
    assert review_latency_hours(_pr(), _rev()) == 4.0


def test_latency_is_none_when_review_has_no_timestamp() -> None:
    assert review_latency_hours(_pr(), _rev(submitted_at=None)) is None


def test_negative_latency_is_rejected() -> None:
    early = _rev(submitted_at=CREATED - timedelta(hours=1))
    assert review_latency_hours(_pr(), early) is None
