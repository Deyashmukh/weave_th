from pathlib import Path

from impact.ownership import Ownership, load_ownership

FIX = Path(__file__).parent / "fixtures"


def _ownership() -> Ownership:
    return load_ownership(
        (FIX / "codeowners.txt").read_text(),
        {"owners.yaml": (FIX / "owners_root.yaml").read_text()},
    )


def test_glob_star_star_matches_nested_path() -> None:
    assert _ownership().is_critical("posthog/clickhouse/migrations/0099_add_col.sql")


def test_exact_path_is_critical() -> None:
    assert _ownership().is_critical("posthog/api/authentication.py")


def test_prefix_star_matches() -> None:
    assert _ownership().is_critical("bin/dev-sandbox-run")


def test_unrelated_path_is_not_critical() -> None:
    assert not _ownership().is_critical("products/surveys/backend/api.py")


def test_later_ownerless_rule_removes_criticality() -> None:
    own = _ownership()
    assert own.is_critical("posthog/hogql/query.py")
    assert not own.is_critical("posthog/hogql/database/schema/events.py")


def test_teams_for_anchored_rule() -> None:
    assert "platform-ux" in _ownership().teams_for("frontend/src/lib/lemon-ui/Button.tsx")


def test_team_slug_canonicalisation_merges_legacy_slugs() -> None:
    from impact.ownership import canonical_team

    assert canonical_team("@PostHog/team-clickhouse") == canonical_team("clickhouse")
    assert canonical_team("@PostHog/hogql") == "hogql"


def test_unanchored_rule_matches_at_any_depth() -> None:
    own = _ownership()
    assert "devex" in own.teams_for("AGENTS.md")
    assert "devex" in own.teams_for("products/surveys/AGENTS.md")
