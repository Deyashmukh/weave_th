import json
from pathlib import Path

from impact.cli import build_report

FIX = Path(__file__).parent / "fixtures"


def _ownership_dir(tmp_path: Path, codeowners: str, owners: str) -> Path:
    own = tmp_path / "ownership"
    (own / "owners").mkdir(parents=True)
    (own / "CODEOWNERS").write_text(codeowners)
    (own / "owners" / "owners.yaml").write_text(owners)
    return own


def test_report_has_required_top_level_keys(tmp_path: Path) -> None:
    raw = tmp_path / "prs.jsonl"
    raw.write_text((FIX / "prs_sample.jsonl").read_text())
    own = _ownership_dir(
        tmp_path,
        "posthog/api/authentication.py @PostHog/team-security\n",
        (FIX / "owners_root.yaml").read_text(),
    )
    report = build_report(raw, own)
    for key in ("window", "totals", "engineers", "sensitivity", "caveats"):
        assert key in report
    assert isinstance(report["engineers"], list)
    assert json.dumps(report)  # must be JSON-serialisable for embedding


def test_bots_never_appear_as_engineers(tmp_path: Path) -> None:
    raw = tmp_path / "prs.jsonl"
    raw.write_text((FIX / "prs_sample.jsonl").read_text())
    own = _ownership_dir(tmp_path, "", "version: 1\nrules: []\n")
    report = build_report(raw, own)
    logins = {e["login"] for e in report["engineers"]}
    assert "posthog" not in logins
    assert not any(login.endswith("[bot]") for login in logins)


def test_window_start_reports_guaranteed_coverage_not_earliest_merge(tmp_path: Path) -> None:
    """The fetch kept PRs merged from 2026-04-20 but only walked back to 2026-04-28.

    Reporting min(mergedAt) would claim completeness the data does not have.
    """
    raw = tmp_path / "prs.jsonl"
    raw.write_text((FIX / "prs_sample.jsonl").read_text())
    own = _ownership_dir(tmp_path, "", "version: 1\nrules: []\n")
    report = build_report(raw, own)
    assert report["window"]["start"].startswith("2026-04-28")
