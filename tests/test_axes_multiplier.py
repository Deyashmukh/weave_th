from datetime import UTC, datetime

from impact.axes import force_multiplier
from impact.classify import PRFacts
from impact.ownership import Ownership, load_ownership

CODEOWNERS = "posthog/clickhouse/migrations/** @PostHog/clickhouse\n"


def _own() -> Ownership:
    return load_ownership(CODEOWNERS, {})


def _pr(paths: tuple[str, ...], **kw: object) -> PRFacts:
    base = dict(
        number=1,
        title="feat(surveys): add response filter",
        author="alice",
        is_bot_author=False,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        merged_at=datetime(2026, 6, 2, tzinfo=UTC),
        base_ref="master",
        is_stack_layer=False,
        pr_type="chore",
        scope=None,
        autonomy="human_driven",
        paths=paths,
        files_truncated=False,
        additions=5,
        deletions=1,
        review_threads=0,
        reviews=(),
    )
    base.update(kw)
    return PRFacts(**base)  # type: ignore[arg-type]


def test_ordinary_product_code_scores_zero() -> None:
    assert force_multiplier(_pr(("products/surveys/backend/api.py",)), _own()) == 0.0


def test_root_agents_md_counts() -> None:
    assert force_multiplier(_pr(("AGENTS.md",)), _own()) == 1.0


def test_claude_md_is_excluded_as_a_symlink() -> None:
    assert force_multiplier(_pr(("CLAUDE.md",)), _own()) == 0.0


def test_skill_file_counts() -> None:
    assert force_multiplier(_pr((".agents/skills/writing-tests/SKILL.md",)), _own()) == 1.0


def test_ci_workflow_counts() -> None:
    assert force_multiplier(_pr((".github/workflows/ci-backend.yml",)), _own()) == 1.0


def test_tooling_counts() -> None:
    assert force_multiplier(_pr(("tools/hogli/main.py",)), _own()) == 1.0


def test_doc_governing_a_critical_path_is_doubled() -> None:
    pr = _pr(("posthog/clickhouse/migrations/AGENTS.md",))
    assert force_multiplier(pr, _own()) == 2.0


def test_multiple_governance_files_accumulate() -> None:
    pr = _pr(("AGENTS.md", ".agents/skills/a/SKILL.md", "tools/x.py"))
    assert force_multiplier(pr, _own()) == 3.0


def test_bot_authored_scores_zero() -> None:
    assert force_multiplier(_pr(("AGENTS.md",), is_bot_author=True), _own()) == 0.0
