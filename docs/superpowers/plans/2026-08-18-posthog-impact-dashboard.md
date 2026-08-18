# PostHog Engineer Impact Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 15,159 fetched PostHog PRs into a single-screen interactive dashboard naming the five most impactful engineers and showing, per person, exactly why.

**Architecture:** A four-stage offline pipeline — `fetch` → `enrich` → `score` → `render`. Raw GitHub JSONL is already captured, so every later stage is a pure function over cached data and runs offline with zero network. The dashboard is one self-contained HTML file with the scored JSON embedded, so hosting is a static file drop.

**Tech Stack:** Python 3.13, uv (locked deps), PyYAML, pytest, ruff, mypy. Vanilla JS + CSS in one HTML file — no build step, no framework, no Node.

## Global Constraints

- Window: **2026-04-28 → 2026-08-18** (112 days). Brief requires ≥ 90.
- Default branch is **`master`**, never `main`. Only `baseRefName == "master"` counts as shipped.
- Bot actors are excluded everywhere. Detection is GraphQL `__typename == "Bot"`, never a name heuristic.
- `CLAUDE.md` files are excluded from governance scoring — all 44 are symlinks to the sibling `AGENTS.md`.
- Axis weights: blast_radius 30, review_leverage 25, force_multiplier 20, unblocking_speed 15, fix_forward 10. Sum = 100.
- Eligibility, pre-committed: ≥ 5 merged `master` PRs **or** ≥ 10 human reviews given. Single pre-committed fallback: if the pool is < 30 engineers, both thresholds halve once and the dashboard reports it.
- Each axis is min-max normalized to 0–100 before weighting. 100 = best observed on that axis.
- Every unit test runs offline against committed fixtures. No test may touch the network.
- Type annotations on every function signature. `mypy --strict` must pass.
- Dashboard must fit 1440×900 with no vertical scroll.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project, pinned deps, ruff/mypy/pytest config |
| `src/impact/ownership.py` | Parse CODEOWNERS + 26 `owners.yaml` → path→team and path→critical lookups |
| `src/impact/classify.py` | Raw PR JSON → typed `PRFacts` / `ReviewFacts`: bots, autonomy, conventional-commit type, stack layers |
| `src/impact/axes.py` | The five per-event axis scorers. Pure functions, no I/O |
| `src/impact/score.py` | Eligibility, min-max normalization, weighted composite, sensitivity analysis |
| `src/impact/render.py` | Scored data → single self-contained `dashboard/index.html` |
| `src/impact/cli.py` | Wires the stages together; the only module doing file I/O |
| `tests/fixtures/` | Committed slices of real CODEOWNERS/owners.yaml/PR JSON |
| `dashboard/index.html` | Built artifact, committed so hosting is a file drop |

Files split by responsibility, not layer. `ownership` and `classify` are independently useful and independently testable; `axes` depends on both but does no I/O, which is what makes the scoring logic cheap to test.

---

### Task 1: Project setup and the ownership resolver

**Files:**
- Create: `pyproject.toml`, `src/impact/__init__.py`, `src/impact/ownership.py`
- Create: `tests/test_ownership.py`, `tests/fixtures/codeowners.txt`, `tests/fixtures/owners_root.yaml`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `Ownership` frozen dataclass with `is_critical(path: str) -> bool` and `teams_for(path: str) -> frozenset[str]`; constructor `load_ownership(codeowners_text: str, owners_files: dict[str, str]) -> Ownership` where `owners_files` maps repo-relative `owners.yaml` path → file text.

- [ ] **Step 1: Initialize the uv project**

```bash
cd ~/weave_th
uv init --lib --name impact --python 3.13
uv add pyyaml
uv add --dev pytest ruff mypy
```

Then replace the generated `[tool.*]` sections in `pyproject.toml` with:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RET"]

[tool.mypy]
python_version = "3.13"
strict = true
files = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create the fixtures**

`tests/fixtures/codeowners.txt` — a real slice, including the un-owning lines that make last-match-wins matter:

```
# ClickHouse team owns Clickhouse migrations
posthog/clickhouse/migrations/** @PostHog/clickhouse

# HogQL team owns HogQL changes
posthog/hogql/** @PostHog/hogql
# ...except per-table schema definitions
posthog/hogql/database/schema/**
posthog/hogql/database/test/__snapshots__/test_database.ambr

posthog/api/authentication.py @PostHog/team-security
bin/dev-sandbox* @PostHog/team-security
tools/owners/** @PostHog/team-security
```

`tests/fixtures/owners_root.yaml`:

```yaml
version: 1
owners: []
rules:
    - match:
          - Dockerfile
          - CLAUDE.md
          - AGENTS.md
      owners: team-devex
    - match: '/frontend/src/lib/lemon-ui/'
      owners: platform-ux
    - match: '/services/llm-gateway/'
      owners: team-ai-gateway
    - match: '/posthog/settings/data_warehouse.py'
      owners: team-data-stack
```

- [ ] **Step 3: Write the failing tests**

`tests/test_ownership.py`:

```python
from pathlib import Path

from impact.ownership import load_ownership

FIX = Path(__file__).parent / "fixtures"


def _ownership():
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
    """CODEOWNERS is last-match-wins; a rule with no owners un-owns the path."""
    own = _ownership()
    assert own.is_critical("posthog/hogql/query.py")
    assert not own.is_critical("posthog/hogql/database/schema/events.py")


def test_teams_for_anchored_rule() -> None:
    assert "platform-ux" in _ownership().teams_for("frontend/src/lib/lemon-ui/Button.tsx")


def test_team_slug_canonicalisation_merges_legacy_slugs() -> None:
    """'clickhouse' and 'team-clickhouse' are the same team; the prefix is legacy."""
    from impact.ownership import canonical_team

    assert canonical_team("@PostHog/team-clickhouse") == canonical_team("clickhouse")
    assert canonical_team("@PostHog/hogql") == "hogql"


def test_unanchored_rule_matches_at_any_depth() -> None:
    own = _ownership()
    assert "devex" in own.teams_for("AGENTS.md")
    assert "devex" in own.teams_for("products/surveys/AGENTS.md")
```

- [ ] **Step 4: Run the tests and watch them fail**

Run: `uv run pytest tests/test_ownership.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.ownership'`

- [ ] **Step 5: Implement `src/impact/ownership.py`**

```python
"""Resolve a repo path to its owning teams and to whether it is CODEOWNERS-critical.

Two independent systems are merged here. `.github/CODEOWNERS` gates *required*
review and is deliberately tiny; its semantics are last-match-wins, and a rule
listing no owners removes ownership rather than adding it. The 26 distributed
`owners.yaml` files drive *advisory* reviewer assignment and are additive.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import yaml


def canonical_team(raw: str) -> str:
    """Normalise a team reference to a bare slug.

    Some PostHog teams predate the `team-` convention (`hogql`, `clickhouse`,
    `platform-ux`), so stripping the prefix uniformly is what keeps one team's
    credit from being split across two spellings.
    """
    return raw.strip().removeprefix("@PostHog/").removeprefix("@").removeprefix("team-")


@dataclass(frozen=True)
class Rule:
    pattern: str
    owners: tuple[str, ...]


def _matches(pattern: str, path: str) -> bool:
    pat = pattern.lstrip("/")
    if pat.endswith("/**"):
        return path.startswith(pat[:-2])
    if pat.endswith("/"):
        return path.startswith(pat)
    if pattern.startswith("/"):
        return path == pat or fnmatch.fnmatch(path, pat)
    # Unanchored: match the whole path or any suffix segment of it.
    return path == pat or fnmatch.fnmatch(path, pat) or path.endswith("/" + pat)


@dataclass(frozen=True)
class Ownership:
    critical: tuple[Rule, ...]
    team_rules: tuple[Rule, ...]

    def is_critical(self, path: str) -> bool:
        owned = False
        for rule in self.critical:
            if _matches(rule.pattern, path):
                owned = bool(rule.owners)
        return owned

    def teams_for(self, path: str) -> frozenset[str]:
        found: set[str] = set()
        for rule in self.team_rules:
            if _matches(rule.pattern, path):
                found.update(rule.owners)
        return frozenset(found)


def _parse_codeowners(text: str) -> tuple[Rule, ...]:
    rules: list[Rule] = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        parts = stripped.split()
        rules.append(Rule(parts[0], tuple(canonical_team(p) for p in parts[1:])))
    return tuple(rules)


def _parse_owners_yaml(rel_path: str, text: str) -> tuple[Rule, ...]:
    doc = yaml.safe_load(text) or {}
    base = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    rules: list[Rule] = []
    for raw in doc.get("rules") or []:
        match = raw.get("match")
        patterns = [match] if isinstance(match, str) else list(match or [])
        owners_raw = raw.get("owners")
        owners = [owners_raw] if isinstance(owners_raw, str) else list(owners_raw or [])
        team_tuple = tuple(canonical_team(o) for o in owners)
        for pat in patterns:
            # A leading slash anchors the pattern to this file's directory.
            resolved = f"{base}{pat}" if pat.startswith("/") and base else pat
            rules.append(Rule(resolved, team_tuple))
    return tuple(rules)


def load_ownership(codeowners_text: str, owners_files: dict[str, str]) -> Ownership:
    team_rules: list[Rule] = []
    for rel_path, text in sorted(owners_files.items()):
        team_rules.extend(_parse_owners_yaml(rel_path, text))
    return Ownership(_parse_codeowners(codeowners_text), tuple(team_rules))
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest tests/test_ownership.py -v`
Expected: 8 passed

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/ tests/
git commit -m "feat(ownership): resolve repo paths to owning teams and critical zones

CODEOWNERS is last-match-wins and a rule with no owners un-owns the path,
which is how posthog/hogql/database/schema/ is carved out of the otherwise
critical posthog/hogql/ tree. Encoding that wrong would mark ~200 ordinary
schema files as blast-radius code.

Team slugs are canonicalised by stripping the 'team-' prefix because several
PostHog teams predate that convention, so 'clickhouse' and 'team-clickhouse'
are one team and must not split a contributor's credit."
```

---

### Task 2: PR classification

**Files:**
- Create: `src/impact/classify.py`, `tests/test_classify.py`, `tests/fixtures/prs_sample.jsonl`

**Interfaces:**
- Consumes: nothing from Task 1 (independent)
- Produces: frozen dataclasses `ReviewFacts(author: str, is_bot: bool, state: str, submitted_at: datetime | None, body_len: int)` and `PRFacts(number: int, title: str, author: str, is_bot_author: bool, created_at: datetime, merged_at: datetime, base_ref: str, is_stack_layer: bool, pr_type: str, scope: str | None, autonomy: str, paths: tuple[str, ...], files_truncated: bool, additions: int, deletions: int, review_threads: int, reviews: tuple[ReviewFacts, ...])`; functions `parse_title(title: str) -> tuple[str, str | None]`, `parse_autonomy(body: str) -> str`, `pr_facts(raw: dict[str, object]) -> PRFacts`.
- `autonomy` is one of `"human_driven"`, `"fully_autonomous"`, `"unstated"`.

- [ ] **Step 1: Create the fixture**

Extract five real PRs covering the tricky cases. Run this once and commit the result:

```bash
cd ~/weave_th
uv run python - <<'PY'
import json
SRC = "/private/tmp/claude-501/-Users-yashdeshmukh/6ebbae2e-157d-4f42-9107-ae8f3bdcf8d6/scratchpad/prs_raw.jsonl"
rows = [json.loads(l) for l in open(SRC) if l.strip()]

def pick(fn):
    return next(r for r in rows if fn(r))

wanted = [
    pick(lambda r: r["baseRefName"] != "master"),                       # stack layer
    pick(lambda r: (r["author"] or {}).get("__typename") == "Bot"),     # bot author
    pick(lambda r: "Fully autonomous" in (r["body"] or "")
                   and "Human-driven" not in (r["body"] or "")),        # autonomous
    pick(lambda r: "Human-driven" in (r["body"] or "")
                   and "Fully autonomous" not in (r["body"] or "")),    # human-driven
    pick(lambda r: r["files"]["totalCount"] > 60),                      # truncated files
]
with open("tests/fixtures/prs_sample.jsonl", "w") as fh:
    for r in wanted:
        fh.write(json.dumps(r) + "\n")
print("wrote", len(wanted), "fixture PRs")
PY
```

- [ ] **Step 2: Write the failing tests**

`tests/test_classify.py`:

```python
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
        ("revert: \"feat(mcp) add skill discovery\"", ("revert", None)),
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
    return [json.loads(line) for line in (FIX / "prs_sample.jsonl").read_text().splitlines() if line]


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
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `uv run pytest tests/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.classify'`

- [ ] **Step 4: Implement `src/impact/classify.py`**

```python
"""Turn raw GitHub GraphQL PR nodes into typed facts.

Three classifications here exist because PostHog's own tooling corrupts the
naive reading of the data: stacked PRs inflate PR counts, bot reviewers
outnumber humans roughly 8:1, and most PRs are agent-assisted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

TITLE_RE = re.compile(r"^\s*(feat|fix|chore|revert|refactor|docs|perf|test)\s*(?:\(([^)]*)\))?\s*:", re.I)

HUMAN_DRIVEN = "Human-driven"
FULLY_AUTONOMOUS = "Fully autonomous"


def parse_title(title: str) -> tuple[str, str | None]:
    """Split a conventional-commit PR title into (type, scope).

    PostHog mandates `<type>(<scope>): <description>` and only 0.2% of merged
    PRs deviate, so this is a reliable classifier here in a way it would not be
    in most repositories.
    """
    match = TITLE_RE.match(title)
    if not match:
        return "unconventional", None
    scope = match.group(2)
    return match.group(1).lower(), (scope.strip().lower() or None) if scope else None


def parse_autonomy(body: str) -> str:
    """Read the PR template's `Autonomy:` declaration.

    The template ships *both* options on one line, so a body containing both is
    an unedited template and declares nothing. Only a body containing exactly
    one of them represents a deliberate choice.
    """
    text = body or ""
    has_human = HUMAN_DRIVEN in text
    has_auto = FULLY_AUTONOMOUS in text
    if has_auto and not has_human:
        return "fully_autonomous"
    if has_human and not has_auto:
        return "human_driven"
    return "unstated"


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _is_bot(actor: dict[str, Any] | None) -> bool:
    return bool(actor) and actor.get("__typename") == "Bot"


@dataclass(frozen=True)
class ReviewFacts:
    author: str
    is_bot: bool
    state: str
    submitted_at: datetime | None
    body_len: int


@dataclass(frozen=True)
class PRFacts:
    number: int
    title: str
    author: str
    is_bot_author: bool
    created_at: datetime
    merged_at: datetime
    base_ref: str
    is_stack_layer: bool
    pr_type: str
    scope: str | None
    autonomy: str
    paths: tuple[str, ...]
    files_truncated: bool
    additions: int
    deletions: int
    review_threads: int
    reviews: tuple[ReviewFacts, ...]

    def title_snippet(self, limit: int = 72) -> str:
        return self.title if len(self.title) <= limit else self.title[: limit - 1] + "\u2026"


def pr_facts(raw: dict[str, Any]) -> PRFacts:
    author = raw.get("author") or {}
    pr_type, scope = parse_title(raw["title"])
    files = raw["files"]["nodes"]
    reviews = tuple(
        ReviewFacts(
            author=(r.get("author") or {}).get("login", ""),
            is_bot=_is_bot(r.get("author")),
            state=r.get("state", ""),
            submitted_at=_dt(r.get("submittedAt")),
            body_len=len(r.get("body") or ""),
        )
        for r in raw["reviews"]["nodes"]
    )
    created = _dt(raw["createdAt"])
    merged = _dt(raw["mergedAt"])
    assert created is not None and merged is not None
    return PRFacts(
        number=raw["number"],
        title=raw["title"],
        author=author.get("login", ""),
        is_bot_author=_is_bot(author),
        created_at=created,
        merged_at=merged,
        base_ref=raw["baseRefName"],
        is_stack_layer=raw["baseRefName"] != "master",
        pr_type=pr_type,
        scope=scope,
        autonomy=parse_autonomy(raw.get("body") or ""),
        paths=tuple(f["path"] for f in files),
        files_truncated=raw["files"]["totalCount"] > len(files),
        additions=raw["additions"],
        deletions=raw["deletions"],
        review_threads=raw["reviewThreads"]["totalCount"],
        reviews=reviews,
    )
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/test_classify.py -v`
Expected: 11 passed

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/impact/classify.py tests/test_classify.py tests/fixtures/prs_sample.jsonl
git commit -m "feat(classify): type raw PR nodes and detect stacks, bots, agent autonomy

Autonomy parsing treats a body containing BOTH template options as
'unstated' rather than guessing. The PR template ships the line as
'Human-driven (agent-assisted) - or - Fully autonomous', so presence of a
single option is the only evidence a human actually chose one.

Bot detection reads GraphQL __typename rather than matching on names: the
reviewer bots here include greptile-apps, stamphog, veria-ai and cursor,
which no name heuristic would catch as a set."
```

---

### Task 3: Delivery axes — blast radius and fix-forward

**Files:**
- Create: `src/impact/axes.py`, `tests/test_axes_delivery.py`

**Interfaces:**
- Consumes: `Ownership` (Task 1), `PRFacts` (Task 2)
- Produces: `blast_radius(pr: PRFacts, own: Ownership) -> float`, `fix_forward(pr: PRFacts, own: Ownership, prior_feat_author: dict[str, str]) -> float`, and helper `touches_critical(pr: PRFacts, own: Ownership) -> bool`. `prior_feat_author` maps a repo path to the login of the most recent `feat` author for that path, built in Task 7.

- [ ] **Step 1: Write the failing tests**

`tests/test_axes_delivery.py`:

```python
from datetime import UTC, datetime

from impact.axes import blast_radius, fix_forward
from impact.classify import PRFacts
from impact.ownership import load_ownership

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


def _own():
    return load_ownership(CODEOWNERS, OWNERS)


def _pr(**kw) -> PRFacts:
    base = dict(
        number=1, title="feat(surveys): add response filter", author="alice",
        is_bot_author=False,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        merged_at=datetime(2026, 6, 2, tzinfo=UTC),
        base_ref="master", is_stack_layer=False,
        pr_type="feat", scope=None, autonomy="human_driven",
        paths=("products/surveys/backend/api.py",), files_truncated=False,
        additions=10, deletions=2, review_threads=0, reviews=(),
    )
    base.update(kw)
    return PRFacts(**base)  # type: ignore[arg-type]


def test_ordinary_pr_scores_base_weight() -> None:
    assert blast_radius(_pr(), _own()) == 1.5  # 1.0 base x (1 + 0.5*1 team)


def test_critical_path_triples_the_score() -> None:
    pr = _pr(paths=("posthog/api/authentication.py",))
    # 1.0 x 3.0 critical x (1 + 0.5*0 teams) = 3.0
    assert blast_radius(pr, _own()) == 3.0


def test_migration_path_adds_its_own_multiplier() -> None:
    pr = _pr(paths=("posthog/clickhouse/migrations/0099.sql",))
    # 1.0 x 3.0 critical x 1.5 migration = 4.5
    assert blast_radius(pr, _own()) == 4.5


def test_cross_team_reach_scales_the_score() -> None:
    pr = _pr(paths=("products/surveys/a.py", "products/experiments/b.py"))
    assert blast_radius(pr, _own()) == 2.0  # 1.0 x (1 + 0.5*2)


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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_axes_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.axes'`

- [ ] **Step 3: Implement the delivery half of `src/impact/axes.py`**

```python
"""Per-event impact scorers. Pure functions: no I/O, no global state.

Every multiplier traces to something the repository states about itself rather
than to a number chosen here. The x3.0 critical multiplier uses CODEOWNERS,
whose header calls adding an entry "anti-social" and requiring "extraordinary
justification" - which makes the surviving paths PostHog's own declaration of
where blast radius is real.
"""

from __future__ import annotations

from collections.abc import Mapping

from impact.classify import PRFacts
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
    """Only human-authored PRs that actually reached master count as shipped."""
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
    """Credit for repairing shipped code, weighted up when it is not your own.

    Reverts are not scored: only 8 exist across 4,789 sampled master PRs, which
    cannot rank five people. PostHog fixes forward instead - `fix` is 45.5% of
    merged PRs against `feat` at 40.1% - so that is where the signal lives.
    """
    if not _counts(pr) or pr.pr_type != "fix":
        return 0.0
    score = 1.0
    if touches_critical(pr, own):
        score *= CRITICAL_MULTIPLIER
    if any(prior_feat_author.get(p, pr.author) != pr.author for p in pr.paths):
        score *= FOREIGN_CODE_MULTIPLIER
    return score
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_axes_delivery.py -v`
Expected: 10 passed

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/impact/axes.py tests/test_axes_delivery.py
git commit -m "feat(axes): score delivery blast radius and fix-forward ownership

Stack layers and bot-authored PRs score zero rather than being filtered
upstream, so the rule lives next to the weights it modifies and is covered
by its own test.

fix_forward doubles when the path's most recent feat author was somebody
else: picking up another engineer's production breakage is the behaviour
worth surfacing, and reverts are too rare here to measure it directly."
```

---

### Task 4: Review axes — leverage and unblocking speed

**Files:**
- Modify: `src/impact/axes.py` (append)
- Create: `tests/test_axes_review.py`

**Interfaces:**
- Consumes: `Ownership`, `PRFacts`, `ReviewFacts`
- Produces: `review_leverage(pr: PRFacts, rev: ReviewFacts, own: Ownership, reviewer_home_teams: frozenset[str]) -> float` and `review_latency_hours(pr: PRFacts, rev: ReviewFacts) -> float | None`. `reviewer_home_teams` is inferred in Task 7 from the teams owning the paths that reviewer authors in.

- [ ] **Step 1: Write the failing tests**

`tests/test_axes_review.py`:

```python
from datetime import UTC, datetime, timedelta

from impact.axes import review_latency_hours, review_leverage
from impact.classify import PRFacts, ReviewFacts
from impact.ownership import load_ownership

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


def _own():
    return load_ownership(CODEOWNERS, OWNERS)


def _rev(**kw) -> ReviewFacts:
    base = dict(author="bob", is_bot=False, state="APPROVED",
                submitted_at=CREATED + timedelta(hours=4), body_len=120)
    base.update(kw)
    return ReviewFacts(**base)  # type: ignore[arg-type]


def _pr(**kw) -> PRFacts:
    base = dict(
        number=1, title="feat(surveys): add response filter", author="alice",
        is_bot_author=False, created_at=CREATED,
        merged_at=CREATED + timedelta(days=1), base_ref="master", is_stack_layer=False,
        pr_type="feat", scope=None, autonomy="human_driven",
        paths=("products/surveys/backend/api.py",), files_truncated=False,
        additions=10, deletions=2, review_threads=0, reviews=(),
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
    """Reviewer assignment is automated, so reviewing off your own patch is voluntary."""
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_axes_review.py -v`
Expected: FAIL — `ImportError: cannot import name 'review_leverage'`

- [ ] **Step 3: Append to `src/impact/axes.py`**

```python
CHANGES_REQUESTED_MULTIPLIER = 1.5
OUTSIDE_TEAM_MULTIPLIER = 2.0
THREAD_COEFFICIENT = 0.1


def review_leverage(
    pr: PRFacts,
    rev: ReviewFacts,
    own: Ownership,
    reviewer_home_teams: frozenset[str],
) -> float:
    """Score one review given to another human's PR.

    The outside-team multiplier exists because auto-assign-reviewers.yml routes
    review requests from CODEOWNERS and owners.yaml. Being asked is a routing
    outcome; reviewing outside your own team's paths is a choice.
    """
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
    """Hours from PR open to this review. None when unusable.

    Measured baseline across 15,222 timed human reviews: median 13.5h,
    p25 1.5h, p75 49.1h. That 33x spread is the widest of any signal here.
    """
    if rev.submitted_at is None or rev.is_bot:
        return None
    hours = (rev.submitted_at - pr.created_at).total_seconds() / 3600.0
    return hours if hours >= 0 else None
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_axes_review.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/impact/axes.py tests/test_axes_review.py
git commit -m "feat(axes): score review leverage and review turnaround

Reviews outside the reviewer's home teams double, because reviewer
assignment is automated by auto-assign-reviewers.yml: the request carries
no signal, only the choice to review off your own patch does.

Self-reviews and bot reviews score zero. Bot reviewers outnumber the
busiest human roughly 8:1 in this repo, so leaving them in would rank
Greptile above every engineer."
```

---

### Task 5: Force-multiplier axis

**Files:**
- Modify: `src/impact/axes.py` (append)
- Create: `tests/test_axes_multiplier.py`

**Interfaces:**
- Consumes: `Ownership`, `PRFacts`
- Produces: `force_multiplier(pr: PRFacts, own: Ownership) -> float`

- [ ] **Step 1: Write the failing tests**

`tests/test_axes_multiplier.py`:

```python
from datetime import UTC, datetime

from impact.axes import force_multiplier
from impact.classify import PRFacts
from impact.ownership import load_ownership

CODEOWNERS = "posthog/clickhouse/migrations/** @PostHog/clickhouse\n"


def _own():
    return load_ownership(CODEOWNERS, {})


def _pr(paths: tuple[str, ...], **kw) -> PRFacts:
    base = dict(
        number=1, title="feat(surveys): add response filter", author="alice",
        is_bot_author=False,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        merged_at=datetime(2026, 6, 2, tzinfo=UTC),
        base_ref="master", is_stack_layer=False, pr_type="chore", scope=None,
        autonomy="human_driven", paths=paths, files_truncated=False,
        additions=5, deletions=1, review_threads=0, reviews=(),
    )
    base.update(kw)
    return PRFacts(**base)  # type: ignore[arg-type]


def test_ordinary_product_code_scores_zero() -> None:
    assert force_multiplier(_pr(("products/surveys/backend/api.py",)), _own()) == 0.0


def test_root_agents_md_counts() -> None:
    assert force_multiplier(_pr(("AGENTS.md",)), _own()) == 1.0


def test_claude_md_is_excluded_as_a_symlink() -> None:
    """All 44 CLAUDE.md files are git symlinks to the sibling AGENTS.md."""
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_axes_multiplier.py -v`
Expected: FAIL — `ImportError: cannot import name 'force_multiplier'`

- [ ] **Step 3: Append to `src/impact/axes.py`**

```python
GOVERNANCE_BASENAMES = (
    "AGENTS.md", "SKILL.md", "owners.yaml", "CODEOWNERS",
    "AI_POLICY.md", "CONTRIBUTING.md", "pull_request_template.md",
)
TOOLING_PREFIXES = (".github/workflows/", "tools/", "bin/", "cli/")
GOVERNS_CRITICAL_MULTIPLIER = 2.0


def _is_governance(path: str) -> bool:
    # CLAUDE.md is deliberately absent: all 44 are symlinks to sibling AGENTS.md,
    # so counting them would double-credit every governance edit.
    return path.rsplit("/", 1)[-1] in GOVERNANCE_BASENAMES or path.startswith(TOOLING_PREFIXES)


def _governs_critical(path: str, own: Ownership) -> bool:
    """True when the file sits in a directory that CODEOWNERS protects."""
    if own.is_critical(path):
        return True
    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    return bool(directory) and own.is_critical(f"{directory}/_probe")


def force_multiplier(pr: PRFacts, own: Ownership) -> float:
    """Credit for changing the rules and tools every other engineer runs on.

    Reach is real: 44 AGENTS.md, 238 SKILL.md, 26 owners.yaml and 126 CI
    workflows. A merged SKILL.md is executable governance - it changes what
    every agent in the repo does next.
    """
    if not _counts(pr):
        return 0.0
    total = 0.0
    for path in pr.paths:
        if not _is_governance(path):
            continue
        total += GOVERNS_CRITICAL_MULTIPLIER if _governs_critical(path, own) else 1.0
    return total
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_axes_multiplier.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/impact/axes.py tests/test_axes_multiplier.py
git commit -m "feat(axes): score force-multiplier work on rules, skills and tooling

CLAUDE.md is excluded by name and covered by a test: all 44 are git
symlinks (mode 120000, 9 bytes) to the sibling AGENTS.md, so counting
both would double every governance edit.

Docs governing a CODEOWNERS-protected directory score double - editing
posthog/clickhouse/migrations/AGENTS.md steers every future migration."
```

---

### Task 6: Composite scoring, eligibility and sensitivity

**Files:**
- Create: `src/impact/score.py`, `tests/test_score.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — operates on plain `dict[str, float]` axis tallies
- Produces: `AXES: tuple[str, ...]`, `WEIGHTS: dict[str, float]`, `normalize(values: Mapping[str, float]) -> dict[str, float]`, `normalize_inverse_log(values: Mapping[str, float]) -> dict[str, float]`, `eligible(pr_counts: Mapping[str, int], review_counts: Mapping[str, int]) -> tuple[set[str], bool]`, `composite(axis_scores: Mapping[str, Mapping[str, float]], weights: Mapping[str, float]) -> dict[str, float]`, `sensitivity(axis_scores, weights, delta: float = 10.0) -> dict[str, object]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:

```python
import pytest

from impact.score import (
    WEIGHTS,
    composite,
    eligible,
    normalize,
    normalize_inverse_log,
    sensitivity,
)


def test_weights_sum_to_one_hundred() -> None:
    assert sum(WEIGHTS.values()) == 100


def test_normalize_maps_best_to_hundred_and_worst_to_zero() -> None:
    out = normalize({"a": 10.0, "b": 0.0, "c": 5.0})
    assert out["a"] == 100.0
    assert out["b"] == 0.0
    assert out["c"] == 50.0


def test_normalize_handles_all_equal_without_dividing_by_zero() -> None:
    out = normalize({"a": 3.0, "b": 3.0})
    assert out == {"a": 0.0, "b": 0.0}


def test_normalize_of_empty_input_is_empty() -> None:
    assert normalize({}) == {}


def test_inverse_log_scores_fast_reviewers_highest() -> None:
    """Latency: lower is better, and the distribution is heavily right-skewed."""
    out = normalize_inverse_log({"fast": 1.5, "mid": 13.5, "slow": 49.1})
    assert out["fast"] == 100.0
    assert out["slow"] == 0.0
    assert 0.0 < out["mid"] < 100.0


def test_eligibility_admits_on_either_threshold() -> None:
    pool, halved = eligible({"a": 5, "b": 0, "c": 1}, {"a": 0, "b": 10, "c": 1})
    assert pool == {"a", "b"}
    assert halved is False


def test_eligibility_fallback_halves_once_when_pool_too_small() -> None:
    pr_counts = {f"e{i}": 3 for i in range(20)}
    review_counts = {f"e{i}": 0 for i in range(20)}
    pool, halved = eligible(pr_counts, review_counts)
    assert halved is True
    assert len(pool) == 20


def test_composite_is_the_weighted_sum_of_normalized_axes() -> None:
    axis_scores = {name: {"a": 100.0, "b": 0.0} for name in WEIGHTS}
    out = composite(axis_scores, WEIGHTS)
    assert out["a"] == pytest.approx(100.0)
    assert out["b"] == pytest.approx(0.0)


def test_sensitivity_reports_a_stable_top_five() -> None:
    axis_scores = {
        name: {f"e{i}": float(100 - i * 10) for i in range(8)} for name in WEIGHTS
    }
    result = sensitivity(axis_scores, WEIGHTS)
    assert result["stable"] is True
    assert result["top5"] == ["e0", "e1", "e2", "e3", "e4"]


def test_sensitivity_detects_an_unstable_ranking() -> None:
    """One axis disagrees violently with the rest, so weight changes reorder the top 5."""
    names = list(WEIGHTS)
    axis_scores = {n: {f"e{i}": float(100 - i * 2) for i in range(8)} for n in names}
    axis_scores[names[0]] = {f"e{i}": float(i * 14) for i in range(8)}
    result = sensitivity(axis_scores, WEIGHTS)
    assert result["stable"] is False
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.score'`

- [ ] **Step 3: Implement `src/impact/score.py`**

```python
"""Combine per-axis tallies into one ranking, and check that ranking survives.

Each axis is min-max scaled to 0-100 before weighting, because the raw units
differ by orders of magnitude: an un-normalised sum would let review counts
swamp every other axis. Scaling to the observed best also gives the dashboard
a line an engineering leader can read directly - 100 means best observed.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping

AXES = ("blast_radius", "review_leverage", "force_multiplier", "unblocking_speed", "fix_forward")

WEIGHTS: dict[str, float] = {
    "blast_radius": 30.0,
    "review_leverage": 25.0,
    "force_multiplier": 20.0,
    "unblocking_speed": 15.0,
    "fix_forward": 10.0,
}

MIN_PRS = 5
MIN_REVIEWS = 10
MIN_POOL = 30
TOP_N = 5


def normalize(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return dict.fromkeys(values, 0.0)
    return {k: 100.0 * (v - lo) / (hi - lo) for k, v in values.items()}


def normalize_inverse_log(values: Mapping[str, float]) -> dict[str, float]:
    """Scale a lower-is-better, right-skewed quantity to 0-100.

    Review latency spans 1.5h to 49h between quartiles, so a linear inversion
    would compress every fast reviewer into a narrow band. Log first.
    """
    if not values:
        return {}
    logs = {k: math.log(max(v, 0.1)) for k, v in values.items()}
    lo, hi = min(logs.values()), max(logs.values())
    if hi == lo:
        return dict.fromkeys(values, 0.0)
    return {k: 100.0 * (hi - v) / (hi - lo) for k, v in logs.items()}


def eligible(
    pr_counts: Mapping[str, int], review_counts: Mapping[str, int]
) -> tuple[set[str], bool]:
    """Apply the pre-committed activity bar, with its one pre-committed fallback."""

    def pool_at(min_prs: int, min_reviews: int) -> set[str]:
        logins = set(pr_counts) | set(review_counts)
        return {
            login
            for login in logins
            if pr_counts.get(login, 0) >= min_prs or review_counts.get(login, 0) >= min_reviews
        }

    pool = pool_at(MIN_PRS, MIN_REVIEWS)
    if len(pool) >= MIN_POOL:
        return pool, False
    return pool_at(MIN_PRS // 2, MIN_REVIEWS // 2), True


def composite(
    axis_scores: Mapping[str, Mapping[str, float]], weights: Mapping[str, float]
) -> dict[str, float]:
    total_weight = sum(weights.values())
    logins = {login for scores in axis_scores.values() for login in scores}
    return {
        login: sum(weights[a] * axis_scores[a].get(login, 0.0) for a in weights) / total_weight
        for login in logins
    }


def _top(scores: Mapping[str, float], n: int = TOP_N) -> list[str]:
    return [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def sensitivity(
    axis_scores: Mapping[str, Mapping[str, float]],
    weights: Mapping[str, float],
    delta: float = 10.0,
) -> dict[str, object]:
    """Perturb every weight by +/- delta and report whether the top 5 holds.

    Weights are a judgement call, so the honest move is to publish how much the
    answer depends on them rather than to present one ranking as inevitable.
    """
    baseline = _top(composite(axis_scores, weights))
    variants: list[list[str]] = []
    for signs in itertools.product((-1.0, 1.0), repeat=len(weights)):
        perturbed = {
            name: max(1.0, weights[name] + sign * delta)
            for name, sign in zip(weights, signs, strict=True)
        }
        variants.append(_top(composite(axis_scores, perturbed)))
    stable = all(set(v) == set(baseline) for v in variants)
    churn = sorted({name for v in variants for name in set(v) ^ set(baseline)})
    return {"top5": baseline, "stable": stable, "variants_tested": len(variants), "churn": churn}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_score.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the whole suite, lint and type-check**

Run: `uv run pytest && uv run ruff check . && uv run ruff format . && uv run mypy`
Expected: 48 passed, no lint or type errors

- [ ] **Step 6: Commit**

```bash
git add src/impact/score.py tests/test_score.py
git commit -m "feat(score): normalize axes, apply eligibility, publish sensitivity

Latency is normalised on a log scale because the distribution is heavily
right-skewed (p25 1.5h, median 13.5h, p75 49.1h); a linear inversion would
compress every fast reviewer into one band.

sensitivity() perturbs all five weights by +/-10 across all 32 sign
combinations and reports whether the published top 5 survives. Weights are
a judgement call, so how much the answer depends on them is a result worth
shipping rather than hiding."
```

---

### Task 7: Pipeline wiring and the real scoring run

**Files:**
- Create: `src/impact/fetch.py`, `src/impact/cli.py`, `tests/test_cli.py`
- Create: `data/ownership/` (committed), `data/scored.json` (committed output)
- Modify: `.gitignore` (add `data/raw/`)

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: `build_report(raw_path: Path, ownership_dir: Path) -> dict[str, object]` and a `main()` entry point runnable as `uv run python -m impact.cli score`. The emitted JSON has keys `window`, `totals`, `engineers` (list of `{login, composite, axes, evidence}`), `sensitivity`, `caveats`.

- [ ] **Step 1: Add the raw-data ignore rule**

```bash
cd ~/weave_th
printf '\n# Raw GitHub pull (96MB); regenerate with `uv run python -m impact.fetch`\ndata/raw/\n' >> .gitignore
mkdir -p data/raw data/ownership/owners
cp /private/tmp/claude-501/-Users-yashdeshmukh/6ebbae2e-157d-4f42-9107-ae8f3bdcf8d6/scratchpad/prs_raw.jsonl data/raw/prs.jsonl
```

- [ ] **Step 2: Write `src/impact/fetch.py` (reproducibility, not re-run now)**

```python
"""Fetch PostHog PRs and ownership files from the GitHub API.

The repo is 6.4 GB, so cloning is not viable, and REST would need ~27k calls
against a 5,000/hr limit. GraphQL costs 4 points per 100 PRs, putting the whole
pull near 1,200 points.

Pagination walks merged PRs by UPDATED_AT descending and halts once a page's
oldest updatedAt precedes the cutoff. GitHub guarantees updatedAt >= mergedAt,
so that halt provably cannot skip a PR merged inside the window - which matters
because sorting by update time surfaces PRs merged as far back as 2020.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

CUTOFF = "2026-04-28T00:00:00Z"
REPO = ("PostHog", "posthog")

PR_QUERY = """
query($cursor: String) {
  rateLimit { cost remaining }
  repository(owner: "PostHog", name: "posthog") {
    pullRequests(states: MERGED, first: 100, after: $cursor,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body createdAt mergedAt updatedAt baseRefName
        additions deletions changedFiles
        author { login __typename }
        labels(first: 15) { nodes { name } }
        comments { totalCount }
        reviewThreads { totalCount }
        closingIssuesReferences(first: 5) { nodes { number } }
        reviews(first: 30) { totalCount nodes { state submittedAt body author { login __typename } } }
        files(first: 60) { totalCount nodes { path additions deletions } }
      }
    }
  }
}
"""


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def fetch_ownership(dest: Path) -> None:
    """Pull CODEOWNERS and every distributed owners.yaml."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "CODEOWNERS").write_text(
        _gh(["api", "repos/PostHog/posthog/contents/.github/CODEOWNERS",
             "-H", "Accept: application/vnd.github.raw"])
    )
    tree = json.loads(_gh(["api", "repos/PostHog/posthog/git/trees/master?recursive=1"]))
    owners_dir = dest / "owners"
    owners_dir.mkdir(exist_ok=True)
    for node in tree["tree"]:
        path = node["path"]
        if path.endswith("owners.yaml"):
            body = _gh(["api", f"repos/PostHog/posthog/contents/{path}",
                        "-H", "Accept: application/vnd.github.raw"])
            (owners_dir / path.replace("/", "__")).write_text(body)


def fetch_prs(dest: Path, cutoff: str = CUTOFF) -> int:
    query_file = dest.parent / "_query.graphql"
    query_file.write_text(PR_QUERY)
    cursor, kept = None, 0
    with dest.open("w") as fh:
        while True:
            args = ["api", "graphql", "-F", f"query=@{query_file}"]
            args += ["-F", "cursor=null" if cursor is None else f"cursor={cursor}"]
            try:
                payload = json.loads(_gh(args))
            except subprocess.CalledProcessError:
                continue  # transient 502 on deep cursors; retry the same page
            conn = payload["data"]["repository"]["pullRequests"]
            nodes = conn["nodes"]
            for node in nodes:
                if node["mergedAt"] and node["mergedAt"] >= cutoff:
                    fh.write(json.dumps(node) + "\n")
                    kept += 1
            if min(n["updatedAt"] for n in nodes) < cutoff or not conn["pageInfo"]["hasNextPage"]:
                break
            cursor = conn["pageInfo"]["endCursor"]
    query_file.unlink(missing_ok=True)
    return kept


def main() -> None:
    root = Path("data")
    fetch_ownership(root / "ownership")
    count = fetch_prs(root / "raw" / "prs.jsonl")
    print(f"fetched {count} PRs")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Populate the committed ownership snapshot**

```bash
cd ~/weave_th
uv run python -c "
from pathlib import Path
from impact.fetch import fetch_ownership
fetch_ownership(Path('data/ownership'))
print('ownership snapshot written')
"
ls data/ownership/owners | wc -l   # expect 26
```

- [ ] **Step 4: Write the failing test for the report builder**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

from impact.cli import build_report

FIX = Path(__file__).parent / "fixtures"


def test_report_has_required_top_level_keys(tmp_path: Path) -> None:
    raw = tmp_path / "prs.jsonl"
    raw.write_text((FIX / "prs_sample.jsonl").read_text())
    own = tmp_path / "ownership"
    (own / "owners").mkdir(parents=True)
    (own / "CODEOWNERS").write_text("posthog/api/authentication.py @PostHog/team-security\n")
    (own / "owners" / "owners.yaml").write_text((FIX / "owners_root.yaml").read_text())

    report = build_report(raw, own)
    for key in ("window", "totals", "engineers", "sensitivity", "caveats"):
        assert key in report
    assert isinstance(report["engineers"], list)
    assert json.dumps(report)  # must be JSON-serialisable for embedding


def test_bots_never_appear_as_engineers(tmp_path: Path) -> None:
    raw = tmp_path / "prs.jsonl"
    raw.write_text((FIX / "prs_sample.jsonl").read_text())
    own = tmp_path / "ownership"
    (own / "owners").mkdir(parents=True)
    (own / "CODEOWNERS").write_text("")
    (own / "owners" / "owners.yaml").write_text("version: 1\nrules: []\n")

    report = build_report(raw, own)
    logins = {e["login"] for e in report["engineers"]}
    assert "posthog" not in logins
    assert not any(login.endswith("[bot]") for login in logins)
```

- [ ] **Step 5: Run the test and watch it fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.cli'`

- [ ] **Step 6: Implement `src/impact/cli.py`**

```python
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


def load_ownership_dir(ownership_dir: Path) -> Ownership:
    owners = {
        p.name.replace("__", "/"): p.read_text()
        for p in sorted((ownership_dir / "owners").glob("*.yaml"))
    }
    return load_ownership((ownership_dir / "CODEOWNERS").read_text(), owners)


def _home_teams(prs: list[PRFacts], own: Ownership) -> dict[str, frozenset[str]]:
    """Infer each engineer's home teams from the paths they author in.

    GitHub team membership is not readable - orgs/PostHog/members returns 27 of
    a much larger engineering org - so authorship is the available proxy.
    """
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
    evidence: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    prior_feat_author: dict[str, str] = {}

    for pr in prs:
        if not pr.is_bot_author and not pr.is_stack_layer:
            pr_counts[pr.author] += 1
        for name, fn in (
            ("blast_radius", lambda: ax.blast_radius(pr, own)),
            ("force_multiplier", lambda: ax.force_multiplier(pr, own)),
            ("fix_forward", lambda: ax.fix_forward(pr, own, prior_feat_author)),
        ):
            value = fn()
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
        "window": {"start": min(p.merged_at for p in prs).isoformat(),
                   "end": max(p.merged_at for p in prs).isoformat(),
                   "days": 112},
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
        "caveats": [
            "GitHub org membership is 92% private (27 of a much larger org are visible), "
            "so employee vs community contributor is inferred, not known.",
            "Bot actors are excluded via GraphQL __typename, not name matching.",
            "Stack layers (PRs based on a non-master branch) are excluded as unshipped.",
            "Fully autonomous PRs are discounted to 0.6 per PostHog's AI_POLICY.md.",
            "Work outside this repository - design, incident command, Support Hero "
            "rotation, mentoring - is invisible to this analysis.",
        ],
    }


def main() -> int:
    report = build_report(Path("data/raw/prs.jsonl"), Path("data/ownership"))
    Path("data/scored.json").write_text(json.dumps(report, indent=2))
    print(f"top {TOP_N}: " + ", ".join(e["login"] for e in report["engineers"]))
    print(f"sensitivity stable: {report['sensitivity']['stable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 8: Run the real scoring pass**

Run: `uv run python -m impact.cli`
Expected: prints the top 5 logins and whether the ranking is weight-stable, and writes `data/scored.json`.

If `sensitivity stable: False`, do **not** tune the weights to force stability — that is the exact rationalisation the pre-commit rule exists to prevent. Record the instability; the dashboard displays it.

- [ ] **Step 9: Full verification gauntlet**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all green

- [ ] **Step 10: Commit**

```bash
git add src/impact/fetch.py src/impact/cli.py tests/test_cli.py .gitignore data/ownership data/scored.json
git commit -m "feat(cli): wire the pipeline and produce the scored report

prior_feat_author is updated only after a PR is scored, so a fix is judged
against the authorship state that existed before it landed rather than
against its own effect.

Home teams are inferred from the paths an engineer authors in, at a 20%
share threshold, because GitHub team membership is not readable: the org
members endpoint returns 27 people out of a much larger engineering org.
That inference is listed in the report's caveats rather than presented as
fact."
```

---

### Task 8: Single-screen interactive dashboard

**Files:**
- Create: `src/impact/render.py`, `tests/test_render.py`
- Create: `dashboard/index.html` (generated, committed)

**Interfaces:**
- Consumes: `data/scored.json` from Task 7
- Produces: `render(report: dict[str, Any]) -> str` returning a complete self-contained HTML document, and `why_line(engineer: dict[str, Any]) -> str` returning the one-sentence explanation on each card.

**Design constraints, from the dataviz skill's procedure:**

- **Form:** the composite is a *composition* of five weighted parts, so each engineer gets one horizontal stacked bar. Rank is the identity, so cards are ordered and numbered rather than plotted.
- **Palette:** categorical slots 1–5 of the validated default palette, assigned in fixed order and never cycled. `#2a78d6` blue, `#eb6834` orange, `#1baf7a` aqua, `#eda100` yellow, `#e87ba4` magenta; dark steps `#3987e5`, `#d95926`, `#199e70`, `#c98500`, `#d55181`.
- **Validation is done, not assumed.** `node scripts/validate_palette.js` returns ALL CHECKS PASS in both modes: worst adjacent CVD ΔE 9.1 light / 8.4 dark, worst normal-vision ΔE 19.6 light / 19.3 dark. The first palette tried here (hand-picked greens and purples) FAILED at CVD ΔE 1.7 — invisible to protanopes — which is why the script runs rather than the eye.
- **Relief rule:** the validator WARNs that aqua, yellow and magenta fall below 3:1 on the light surface. Relief is shipped two ways — a labelled legend, and numeric per-axis values in the drill-down panel, which is the table view.
- **2px surface gap** between stacked segments, per the mark spec.
- **Dark mode is selected, not flipped:** its own validated steps, declared under both the `prefers-color-scheme` media query and the `data-theme` scope.
- Colour never carries identity alone; text always wears text tokens, never a series colour.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:

```python
import json
import re
from pathlib import Path

from impact.render import AXIS_COLORS, render, why_line

REPORT = {
    "window": {"start": "2026-04-28T00:00:00+00:00", "end": "2026-08-18T00:00:00+00:00", "days": 112},
    "totals": {"prs_fetched": 15159, "merged_to_master": 14800, "stack_layers_excluded": 359,
               "bot_authored_excluded": 900, "eligible_engineers": 140,
               "eligibility_fallback_fired": False},
    "weights": {"blast_radius": 30.0, "review_leverage": 25.0, "force_multiplier": 20.0,
                "unblocking_speed": 15.0, "fix_forward": 10.0},
    "engineers": [
        {"login": "alice", "composite": 88.2, "rank": 1,
         "axes": {"blast_radius": 90.0, "review_leverage": 80.0, "force_multiplier": 95.0,
                  "unblocking_speed": 70.0, "fix_forward": 60.0},
         "raw": {"merged_prs": 120, "reviews_given": 200, "median_review_hours": 2.4},
         "evidence": {"blast_radius": [{"number": 1, "title": "feat(hogql): x", "score": 9.0}]}},
    ],
    "all_ranked": [{"login": "alice", "composite": 88.2}],
    "sensitivity": {"top5": ["alice"], "stable": True, "variants_tested": 32, "churn": []},
    "caveats": ["org membership is 92% private"],
}


def test_render_is_one_self_contained_document() -> None:
    html = render(REPORT)
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    assert "<script src=" not in html
    assert "<link" not in html
    assert "http://" not in html.replace("http://www.w3.org", "")


def test_engineer_names_and_scores_are_in_static_html() -> None:
    """Top 5 must be readable even if the JS never runs."""
    html = render(REPORT)
    assert "alice" in html
    assert "88.2" in html


def test_uses_the_validated_palette_slots() -> None:
    """Hand-picked colours failed CVD at delta-E 1.7; these are the validated slots."""
    assert list(AXIS_COLORS.values()) == ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]


def test_dark_mode_declares_its_own_steps_under_both_scopes() -> None:
    html = render(REPORT)
    assert "prefers-color-scheme: dark" in html
    assert '[data-theme="dark"]' in html
    assert "#3987e5" in html  # dark step for slot 1, not a flipped light value


def test_legend_labels_every_axis_so_colour_is_never_alone() -> None:
    html = render(REPORT)
    for label in ("Blast radius", "Review leverage", "Force multiplier",
                  "Unblocking speed", "Fix-forward"):
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'impact.render'`

- [ ] **Step 3: Implement `src/impact/render.py`**

`why_line` is left for a human — see the TODO(human). Everything around it is complete.

```python
"""Render the scored report as one self-contained HTML page.

No external requests: the audience is a busy engineering leader opening a link,
and a page that depends on a CDN is a page that can fail in front of them.

Colours are categorical slots 1-5 of the validated default palette, in fixed
order. They were not chosen by eye - the first attempt here used hand-picked
greens and purples and failed CVD separation at delta-E 1.7, which is
indistinguishable to a protanope. These pass every gate in both modes.
"""

from __future__ import annotations

import html
import json
from typing import Any

AXIS_LABELS = {
    "blast_radius": "Blast radius",
    "review_leverage": "Review leverage",
    "force_multiplier": "Force multiplier",
    "unblocking_speed": "Unblocking speed",
    "fix_forward": "Fix-forward",
}
AXIS_COLORS = {
    "blast_radius": "#2a78d6",
    "review_leverage": "#eb6834",
    "force_multiplier": "#1baf7a",
    "unblocking_speed": "#eda100",
    "fix_forward": "#e87ba4",
}
AXIS_COLORS_DARK = {
    "blast_radius": "#3987e5",
    "review_leverage": "#d95926",
    "force_multiplier": "#199e70",
    "unblocking_speed": "#c98500",
    "fix_forward": "#d55181",
}


def why_line(engineer: dict[str, Any]) -> str:
    """One sentence telling an engineering leader why this person ranks here.

    TODO(human): implement this.
    """
    raise NotImplementedError


def _axis_vars(colors: dict[str, str]) -> str:
    return "".join(f"  --{name.replace('_', '-')}: {hexv};\n" for name, hexv in colors.items())


def _card(engineer: dict[str, Any]) -> str:
    """One ranked card: rank, name, why, stacked composition bar, raw counts, score.

    Segment widths are the axis score scaled by its weight share, so the bar
    reads as the composition of the composite rather than five unrelated bars.
    """
    axes = engineer["axes"]
    total = sum(axes.values()) or 1.0
    segments = "".join(
        f'<span class="seg" style="flex:{axes[name] / total:.4f};'
        f'background:var(--{name.replace("_", "-")})" '
        f'title="{AXIS_LABELS[name]}: {axes[name]}"></span>'
        for name in AXIS_LABELS
        if axes[name] > 0
    )
    raw = engineer["raw"]
    return f"""
      <button class="card" data-login="{html.escape(engineer["login"])}" aria-current="false">
        <span class="rank">{engineer["rank"]}</span>
        <span class="body">
          <span class="name">{html.escape(engineer["login"])}</span>
          <span class="why">{html.escape(why_line(engineer))}</span>
          <span class="bar">{segments}</span>
          <span class="raw">{raw["merged_prs"]} PRs merged &middot;
            {raw["reviews_given"]} reviews given &middot;
            {raw["median_review_hours"]}h median review</span>
        </span>
        <span class="score">{engineer["composite"]}</span>
      </button>"""


def _legend(weights: dict[str, float]) -> str:
    return "".join(
        f'<span class="key"><i style="background:var(--{n.replace("_", "-")})"></i>'
        f'{AXIS_LABELS[n]} <b>{int(weights[n])}</b></span>'
        for n in AXIS_LABELS
    )


def render(report: dict[str, Any]) -> str:
    totals, sens, weights = report["totals"], report["sensitivity"], report["weights"]
    cards = "".join(_card(e) for e in report["engineers"])
    caveats = "".join(f"<li>{html.escape(c)}</li>" for c in report["caveats"])
    stability = (
        f"Top 5 held across all {sens['variants_tested']} weight perturbations (±10)."
        if sens["stable"]
        else f"UNSTABLE — {sens['variants_tested']} perturbations (±10) moved "
        f"{', '.join(sens['churn'])} in or out of the top 5."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PostHog &mdash; most impactful engineers</title>
<style>
:root {{
  color-scheme: light;
  --surface-0:#f4f2ef; --surface-1:#fcfcfb; --line:#e4e0da;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#86837c;
{_axis_vars(AXIS_COLORS)}}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --surface-0:#111110; --surface-1:#1a1a19; --line:#33322f;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8e8c84;
{_axis_vars(AXIS_COLORS_DARK)}  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface-0:#111110; --surface-1:#1a1a19; --line:#33322f;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8e8c84;
{_axis_vars(AXIS_COLORS_DARK)}}}
*{{box-sizing:border-box}}
body{{margin:0;height:100vh;overflow:hidden;display:grid;grid-template-rows:auto 1fr auto;
  background:var(--surface-0);color:var(--text-primary);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
header{{padding:16px 24px 12px;background:var(--surface-1);border-bottom:1px solid var(--line)}}
h1{{margin:0;font-size:18px;letter-spacing:-.01em}}
.sub{{color:var(--text-secondary);font-size:12.5px;margin-top:4px;max-width:none}}
.legend{{margin-top:9px;display:flex;flex-wrap:wrap;gap:4px 16px}}
.key{{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--text-secondary)}}
.key i{{width:10px;height:10px;border-radius:3px;display:inline-block;flex:none}}
.key b{{color:var(--text-muted);font-weight:600;font-variant-numeric:tabular-nums}}
main{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px;padding:18px 24px;min-height:0}}
.col{{display:flex;flex-direction:column;gap:10px;min-height:0}}
.card{{display:grid;grid-template-columns:30px 1fr auto;gap:14px;align-items:center;
  text-align:left;padding:12px 14px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-1);cursor:pointer;font:inherit;color:inherit;
  transition:border-color .12s,box-shadow .12s}}
.card:hover{{border-color:var(--text-muted)}}
.card[aria-current="true"]{{border-color:var(--text-primary);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--text-primary) 10%,transparent)}}
.rank{{font-size:20px;font-weight:700;color:var(--text-muted);text-align:center;
  font-variant-numeric:tabular-nums}}
.body{{display:flex;flex-direction:column;min-width:0}}
.name{{font-weight:650;font-size:15px}}
.why{{color:var(--text-secondary);font-size:12.5px;margin:2px 0 7px}}
.bar{{display:flex;gap:2px;height:8px}}
.seg{{border-radius:2px;min-width:3px}}
.seg:first-child{{border-radius:4px 2px 2px 4px}}
.seg:last-child{{border-radius:2px 4px 4px 2px}}
.raw{{color:var(--text-muted);font-size:11.5px;margin-top:7px}}
.score{{font-size:23px;font-weight:700;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em}}
.panel{{border:1px solid var(--line);border-radius:10px;background:var(--surface-1);
  padding:16px 18px;overflow:auto;min-height:0}}
.panel h2{{margin:0 0 12px;font-size:15px}}
.axrow{{display:grid;grid-template-columns:112px 1fr 34px;gap:10px;align-items:center;
  margin-bottom:7px;font-size:12.5px;color:var(--text-secondary)}}
.axbar{{height:8px;background:var(--surface-0);border-radius:4px;overflow:hidden}}
.axfill{{height:100%;border-radius:4px}}
.axval{{text-align:right;font-variant-numeric:tabular-nums;color:var(--text-primary);
  font-weight:600}}
.ev{{margin:14px 0 0;padding:0;list-style:none;font-size:12.5px}}
.ev li{{padding:6px 0;border-top:1px solid var(--line);color:var(--text-secondary)}}
.ev a{{color:var(--text-primary);font-variant-numeric:tabular-nums}}
.ev em{{font-style:normal;color:var(--text-muted)}}
footer{{padding:10px 24px;background:var(--surface-1);border-top:1px solid var(--line);
  font-size:11.5px;color:var(--text-muted);display:grid;
  grid-template-columns:auto 1fr;gap:24px;align-items:start}}
footer ul{{margin:0;padding-left:15px;columns:2;column-gap:24px}}
footer li{{margin-bottom:1px}}
.stab{{color:var(--text-secondary);font-weight:600}}
</style></head><body>
<header>
  <h1>Who is most impactful in the PostHog repo</h1>
  <div class="sub">Impact is the risk a person absorbs and the leverage they create &mdash;
    not the volume they emit. {totals["merged_to_master"]:,} PRs merged to
    <code>master</code> across {report["window"]["days"]} days;
    {totals["stack_layers_excluded"]:,} stack layers and
    {totals["bot_authored_excluded"]:,} bot-authored PRs excluded;
    {totals["eligible_engineers"]} engineers eligible.</div>
  <div class="legend">{_legend(weights)}</div>
</header>
<main>
  <div class="col" id="cards">{cards}</div>
  <div class="panel" id="panel"></div>
</main>
<footer>
  <div><span class="stab">Sensitivity</span><br>{html.escape(stability)}</div>
  <div><span class="stab">Caveats</span><ul>{caveats}</ul></div>
</footer>
<script id="report" type="application/json">{json.dumps(report)}</script>
<script>
const REPORT = JSON.parse(document.getElementById('report').textContent);
const LABELS = {json.dumps(AXIS_LABELS)};
const panel = document.getElementById('panel');

function show(login) {{
  const e = REPORT.engineers.find(x => x.login === login);
  document.querySelectorAll('.card').forEach(c =>
    c.setAttribute('aria-current', String(c.dataset.login === login)));
  // Numeric values here are the relief the palette validator requires for the
  // three light-mode hues that fall below 3:1 contrast.
  const rows = Object.keys(LABELS).map(k => `
    <div class="axrow"><span>${{LABELS[k]}}</span>
      <span class="axbar"><span class="axfill" style="width:${{e.axes[k]}}%;
        background:var(--${{k.replace(/_/g,'-')}})"></span></span>
      <span class="axval">${{e.axes[k]}}</span></div>`).join('');
  const ev = Object.entries(e.evidence || {{}}).flatMap(([axis, items]) => items.map(i =>
    `<li><em>${{LABELS[axis]}}</em> &middot;
      <a href="https://github.com/PostHog/posthog/pull/${{i.number}}"
         target="_blank" rel="noopener">#${{i.number}}</a> ${{i.title}}</li>`)).join('');
  panel.innerHTML = `<h2>${{e.login}} &mdash; why</h2>${{rows}}
    <ul class="ev">${{ev || '<li>No evidence recorded.</li>'}}</ul>`;
}}

document.querySelectorAll('.card').forEach(c =>
  c.addEventListener('click', () => show(c.dataset.login)));
if (REPORT.engineers.length) show(REPORT.engineers[0].login);
</script>
</body></html>"""
```

- [ ] **Step 4: Human implements `why_line`**

Stop and request the human contribution for `why_line`. It is the one piece of genuine editorial judgement in the render layer: what a busy engineering leader needs to read in a single sentence.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/test_render.py -v`
Expected: 8 passed

- [ ] **Step 6: Generate the dashboard, then look at it**

```bash
cd ~/weave_th
mkdir -p dashboard
uv run python -c "
import json, pathlib
from impact.render import render
report = json.loads(pathlib.Path('data/scored.json').read_text())
pathlib.Path('dashboard/index.html').write_text(render(report))
print('bytes:', pathlib.Path('dashboard/index.html').stat().st_size)
"
open dashboard/index.html
```

The validator checks colour, not layout. Confirm by eye at 1440×900: no vertical
scrollbar anywhere, all five cards visible, no clipped labels in the stacked bar,
the drill-down panel swaps on click, and the page is legible in both light and
dark mode (toggle the OS setting to check the dark steps).

- [ ] **Step 7: Commit**

```bash
git add src/impact/render.py tests/test_render.py dashboard/index.html
git commit -m "feat(render): single self-contained page for the top five engineers

Palette is categorical slots 1-5 of the validated default, run through the
dataviz validator rather than chosen by eye: the first attempt used
hand-picked greens and purples and failed CVD separation at delta-E 1.7,
which a protanope cannot distinguish at all. The shipped set passes every
gate in both light and dark.

Three light-mode hues sit below 3:1 contrast, so the validator's relief
rule applies: a labelled legend and numeric per-axis values in the panel
both ship, and colour never carries identity alone.

No external requests of any kind. Names and scores live in the static HTML
rather than being painted by script, so the answer survives a JS failure."
```

---

### Task 9: Host, verify, and finish the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Decide the hosting target**

The dashboard is one static file with no backend, so any static host works. Confirm with the user which they want, because it affects repository visibility:

- **GitHub Pages** needs the repo public on a free plan. Simplest, but publishes the take-home solution.
- **A separate public repo** holding only `dashboard/index.html`, with `weave_th` staying private. Keeps the solution private but splits the submission.
- **Vercel / Netlify / Cloudflare Pages** — public URL, source stays private, needs one account.

- [ ] **Step 2: Deploy (GitHub Pages variant)**

```bash
cd ~/weave_th
gh repo edit Deyashmukh/weave_th --visibility public --accept-visibility-change-consequences
gh api -X POST repos/Deyashmukh/weave_th/pages \
  -f 'source[branch]=master' -f 'source[path]=/docs' 2>/dev/null \
  || gh api -X PUT repos/Deyashmukh/weave_th/pages -f 'source[branch]=master' -f 'source[path]=/docs'
```

- [ ] **Step 3: Verify the live URL actually serves the dashboard**

```bash
URL=$(gh api repos/Deyashmukh/weave_th/pages --jq .html_url)
echo "$URL"
curl -sS -o /tmp/live.html -w '%{http_code}\n' "$URL"
grep -c 'id="report"' /tmp/live.html    # expect 1
```

Expected: HTTP 200 and the embedded report present. A 404 means Pages has not finished building — wait and retry rather than assuming success.

- [ ] **Step 4: Fill in the README**

Replace the placeholder sections written in the repo shell with: the live URL, the impact definition in three sentences, the three de-noising rules with their measured numbers, how to reproduce (`uv sync && uv run python -m impact.fetch && uv run python -m impact.cli`), and the limitations section copied from the spec.

- [ ] **Step 5: Final verification gauntlet**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Expected: all green. Paste the real output into the PR description — do not summarise it.

- [ ] **Step 6: Commit and open the PR for review**

```bash
git add README.md
git commit -m "docs: record the live dashboard URL, method, and limitations"
git push
gh pr ready 1
```
