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


def test_every_axis_has_a_definition_and_a_formula() -> None:
    """AXIS_META is the single source for the page, the panel and the tooltips."""
    from impact.render import AXIS_LABELS, AXIS_META

    assert set(AXIS_META) == set(AXIS_LABELS)
    for name, meta in AXIS_META.items():
        assert set(meta) == {"short", "captures", "formula"}, name
        assert len(meta["short"]) > 20, name
        assert len(meta["captures"]) > 120, f"{name}: definition too thin to be clear"
        assert len(meta["formula"]) > 40, name


def test_every_metric_detail_is_embedded_for_the_interactive_pane() -> None:
    """The pane is driven client-side, so all five definitions ship in the page."""
    from impact.render import AXIS_META

    html = render(REPORT)
    for name, meta in AXIS_META.items():
        assert meta["captures"][:60] in html, f"definition missing for {name}"
        assert meta["formula"][:40] in html, f"formula missing for {name}"


def test_metric_rows_are_buttons_so_touch_and_keyboard_both_reach_them() -> None:
    """Hover alone would strand phone users and anyone navigating by keyboard."""
    html = render(REPORT)
    assert html.count('class="sr" data-metric=') == 5
    assert "addEventListener('mouseenter'" in html
    assert "addEventListener('click'" in html
    assert "addEventListener('focus'" in html


def test_detail_pane_flexes_into_leftover_space() -> None:
    """Space under the last card varies by viewport, so the pane cannot be fixed-height."""
    html = render(REPORT)
    assert ".sdetail{flex:1;min-height:0;overflow:auto" in html
    assert '<div class="sdetail" id="sdetail">' in html


def test_dashboard_occupies_exactly_one_screen() -> None:
    """The brief asks the dashboard to fit one laptop screen."""
    html = render(REPORT)
    assert '<div class="screen">' in html
    assert ".screen{height:100vh;" in html
    assert "@media (max-height: 780px)" in html  # escape hatch: scroll, never clip


def test_mobile_breakpoint_exists_and_unlocks_scrolling() -> None:
    """Desktop pins height to 100vh with overflow hidden, which would trap a phone."""
    html = render(REPORT)
    assert "@media (max-width: 900px)" in html
    assert "min-height:100vh" in html


def test_mobile_releases_the_pinned_screen_not_just_the_body() -> None:
    """`.screen` pins 100vh with overflow:hidden; releasing only `body` still clips.

    This regressed once: the phone layout reported a page height exactly equal to
    the viewport, meaning everything past the first screen had been discarded.
    """
    html = render(REPORT)
    mobile = html.split("@media (max-width: 900px)", 1)[1]
    assert ".screen{height:auto;overflow:visible" in mobile
