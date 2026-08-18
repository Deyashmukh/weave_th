"""Turn raw GitHub GraphQL PR nodes into typed facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

TITLE_RE = re.compile(
    r"^\s*(feat|fix|chore|revert|refactor|docs|perf|test)\s*(?:\(([^)]*)\))?\s*:", re.I
)

HUMAN_DRIVEN = "Human-driven"
FULLY_AUTONOMOUS = "Fully autonomous"


def parse_title(title: str) -> tuple[str, str | None]:
    match = TITLE_RE.match(title)
    if not match:
        return "unconventional", None
    scope = match.group(2)
    return match.group(1).lower(), (scope.strip().lower() or None) if scope else None


def parse_autonomy(body: str) -> str:
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
    return actor is not None and actor.get("__typename") == "Bot"


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
        return self.title if len(self.title) <= limit else self.title[: limit - 1] + "…"


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
