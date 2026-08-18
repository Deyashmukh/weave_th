import json
from pathlib import Path

import pytest

from impact.classify import parse_autonomy, parse_title, pr_facts

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat(insights): add retention graph export", ("feat", "insights")),
        ("fix(cohorts): handle empty cohort", ("fix", "cohorts")),
        ("chore: update AGENTS.md instructions", ("chore", None)),
        ('revert: "feat(mcp) add skill discovery"', ("revert", None)),
        ("Bump lodash from 1 to 2", ("unconventional", None)),
    ],
)
def test_parse_title(title: str, expected: tuple[str, str | None]) -> None:
    assert parse_title(title) == expected


def test_autonomy_unedited_template_is_unstated() -> None:
    """The template ships both options on one line; leaving it means nothing was declared."""
    body = "**Autonomy:** Human-driven (agent-assisted) - or - Fully autonomous"
    assert parse_autonomy(body) == "unstated"


def test_autonomy_human_driven() -> None:
    assert parse_autonomy("**Autonomy:** Human-driven (agent-assisted)") == "human_driven"


def test_autonomy_fully_autonomous() -> None:
    assert parse_autonomy("**Autonomy:** Fully autonomous") == "fully_autonomous"


def test_autonomy_absent_section() -> None:
    assert parse_autonomy("## Problem\nfixes a thing") == "unstated"


def _fixtures() -> list[dict[str, object]]:
    return [
        json.loads(line) for line in (FIX / "prs_sample.jsonl").read_text().splitlines() if line
    ]


def test_stack_layer_detected() -> None:
    facts = [pr_facts(r) for r in _fixtures()]
    assert any(f.is_stack_layer for f in facts)
    assert all(f.base_ref == "master" for f in facts if not f.is_stack_layer)


def test_bot_author_detected_by_typename_not_name() -> None:
    facts = [pr_facts(r) for r in _fixtures()]
    assert any(f.is_bot_author for f in facts)


def test_truncated_file_list_is_flagged() -> None:
    facts = [pr_facts(r) for r in _fixtures()]
    truncated = [f for f in facts if f.files_truncated]
    assert truncated, "fixture should include a PR with >60 changed files"
    assert len(truncated[0].paths) <= 60
