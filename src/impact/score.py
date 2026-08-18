"""Combine per-axis tallies into one ranking, and check that ranking survives."""

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
    """Log-compress, then scale to 0-100."""
    if not values:
        return {}
    logs = {k: math.log1p(max(v, 0.0)) for k, v in values.items()}
    lo, hi = min(logs.values()), max(logs.values())
    if hi == lo:
        return dict.fromkeys(values, 0.0)
    return {k: 100.0 * (v - lo) / (hi - lo) for k, v in logs.items()}


def normalize_inverse_log(values: Mapping[str, float]) -> dict[str, float]:
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
