"""Resolve a repo path to its owning teams and to whether it is CODEOWNERS-critical."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import yaml


def canonical_team(raw: str) -> str:
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
            resolved = f"{base}{pat}" if pat.startswith("/") and base else pat
            rules.append(Rule(resolved, team_tuple))
    return tuple(rules)


def load_ownership(codeowners_text: str, owners_files: dict[str, str]) -> Ownership:
    team_rules: list[Rule] = []
    for rel_path, text in sorted(owners_files.items()):
        team_rules.extend(_parse_owners_yaml(rel_path, text))
    return Ownership(_parse_codeowners(codeowners_text), tuple(team_rules))
