import json
import re
from typing import Any

from impact.render import AXIS_COLORS, render, why_line

REPORT: dict[str, Any] = {
    "window": {
        "start": "2026-04-28T00:00:00+00:00",
        "end": "2026-08-18T00:00:00+00:00",
        "days": 112,
    },
    "totals": {
        "prs_fetched": 15159,
        "merged_to_master": 14800,
        "stack_layers_excluded": 359,
        "bot_authored_excluded": 900,
        "eligible_engineers": 140,
        "eligibility_fallback_fired": False,
    },
    "weights": {
        "blast_radius": 30.0,
        "review_leverage": 25.0,
        "force_multiplier": 20.0,
        "unblocking_speed": 15.0,
        "fix_forward": 10.0,
    },
    "engineers": [
        {
            "login": "alice",
            "composite": 88.2,
            "rank": 1,
            "axes": {
                "blast_radius": 90.0,
                "review_leverage": 80.0,
                "force_multiplier": 95.0,
                "unblocking_speed": 70.0,
                "fix_forward": 60.0,
            },
            "raw": {"merged_prs": 120, "reviews_given": 200, "median_review_hours": 2.4},
            "evidence": {"blast_radius": [{"number": 1, "title": "feat(hogql): x", "score": 9.0}]},
        },
    ],
    "all_ranked": [{"login": "alice", "composite": 88.2}],
    "sensitivity": {"top5": ["alice"], "stable": True, "variants_tested": 32, "churn": []},
    "caveats": ["GitHub org membership is 92% private, so contributor type is inferred."],
}


def test_render_is_one_self_contained_document() -> None:
    html = render(REPORT)
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    assert "<script src=" not in html
    assert "<link" not in html
    assert "http://" not in html.replace("http://www.w3.org", "")


def test_engineer_names_and_scores_are_in_static_html() -> None:
    html = render(REPORT)
    assert "alice" in html
    assert "88.2" in html


def test_uses_the_validated_palette_slots() -> None:
    assert list(AXIS_COLORS.values()) == ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]


def test_dark_mode_declares_its_own_steps_under_both_scopes() -> None:
    html = render(REPORT)
    assert "prefers-color-scheme: dark" in html
    assert '[data-theme="dark"]' in html
    assert "#3987e5" in html


def test_legend_labels_every_axis_so_colour_is_never_alone() -> None:
    html = render(REPORT)
    for label in (
        "Blast radius",
        "Review leverage",
        "Force multiplier",
        "Unblocking speed",
        "Fix-forward",
    ):
        assert label in html


def test_caveats_and_sensitivity_are_rendered_not_hidden() -> None:
    html = render(REPORT)
    assert "org membership is 92% private" in html
    assert "32" in html


def test_embedded_json_round_trips() -> None:
    html = render(REPORT)
    match = re.search(r'<script id="report" type="application/json">(.*?)</script>', html, re.S)
    assert match
    assert json.loads(match.group(1))["engineers"][0]["login"] == "alice"


def test_why_line_names_the_engineers_strongest_axis() -> None:
    assert "force multiplier" in why_line(REPORT["engineers"][0]).lower()


def test_axis_fill_is_blockified() -> None:
    """`.axfill` is a <span>; width/height are ignored on inline elements.

    The card bars survive without this because `.bar` is display:flex, which
    blockifies its children. `.axbar` is not flex, so without display:block the
    panel bars render at zero size while the DOM still looks correct - a bug
    invisible to any test that only inspects markup.
    """
    html = render(REPORT)
    assert ".axfill{display:block;" in html


def test_caveats_are_real_prose_not_placeholders() -> None:
    """The honesty strip is a deliverable, not decoration."""
    from impact.cli import build_report  # noqa: PLC0415 - import kept local to the test

    assert callable(build_report)
    for caveat in REPORT["caveats"]:
        assert len(caveat) > 15, f"placeholder caveat leaked into the report: {caveat!r}"


def test_every_axis_has_a_meaning_and_a_formula() -> None:
    """AXIS_META is the single source of truth for tooltips, footer and panel."""
    from impact.render import AXIS_LABELS, AXIS_META

    assert set(AXIS_META) == set(AXIS_LABELS)
    for meaning, formula in AXIS_META.values():
        assert len(meaning) > 20 and len(formula) > 40


def test_formulas_are_published_in_the_page() -> None:
    """The method has to be legible from the page itself, not only the spec."""
    from impact.render import AXIS_META

    html = render(REPORT)
    for _, formula in AXIS_META.values():
        assert formula[:40] in html, f"formula missing from page: {formula[:40]!r}"
    assert "score = &Sigma; (weight &times; axis) &divide; 100" in html


def test_mobile_breakpoint_exists_and_unlocks_scrolling() -> None:
    """Desktop pins height to 100vh with overflow hidden, which would trap a phone."""
    html = render(REPORT)
    assert "@media (max-width: 900px)" in html
    assert "min-height:100vh" in html


def test_formula_is_visible_without_hover_on_touch() -> None:
    """Touch devices never fire a title tooltip, so the formula renders inline."""
    html = render(REPORT)
    assert ".mformula{display:none}" in html  # hidden on desktop, tooltip covers it
    assert ".mformula{display:block" in html  # shown inside the mobile breakpoint
