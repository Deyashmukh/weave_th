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


def test_normalize_is_log_scaled_not_linear() -> None:
    out = normalize({"a": 10.0, "b": 0.0, "c": 5.0})
    assert out["c"] == pytest.approx(74.7, abs=0.1)


def test_normalize_resists_a_single_extreme_outlier() -> None:
    field = {f"e{i}": float(i + 1) for i in range(20)}
    field["outlier"] = 2209.0
    out = normalize(field)
    median_log = sorted(v for k, v in out.items() if k != "outlier")[10]
    # What a LINEAR min-max would have produced for the same field.
    median_linear = 100.0 * (10.5 - 1.0) / (2209.0 - 1.0)
    assert median_linear < 1.0, "linear scaling should crush the field"
    assert median_log > 20 * median_linear, (
        f"log scaling lifted the median only {median_log / median_linear:.0f}x"
    )


def test_normalize_handles_all_equal_without_dividing_by_zero() -> None:
    out = normalize({"a": 3.0, "b": 3.0})
    assert out == {"a": 0.0, "b": 0.0}


def test_normalize_of_empty_input_is_empty() -> None:
    assert normalize({}) == {}


def test_inverse_log_scores_fast_reviewers_highest() -> None:
    out = normalize_inverse_log({"fast": 1.5, "mid": 13.5, "slow": 49.1})
    assert out["fast"] == 100.0
    assert out["slow"] == 0.0
    assert 0.0 < out["mid"] < 100.0


def test_eligibility_admits_on_either_threshold() -> None:
    pool, halved = eligible({"a": 5, "b": 0, "c": 1}, {"a": 0, "b": 10, "c": 1})
    assert pool == {"a", "b"}


def test_fallback_does_not_fire_when_the_pool_is_large_enough() -> None:
    pool, halved = eligible({f"e{i}": 9 for i in range(40)}, {})
    assert len(pool) == 40
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
    axis_scores = {name: {f"e{i}": float(100 - i * 10) for i in range(8)} for name in WEIGHTS}
    result = sensitivity(axis_scores, WEIGHTS)
    assert result["stable"] is True
    assert result["top5"] == ["e0", "e1", "e2", "e3", "e4"]


def test_sensitivity_detects_an_unstable_ranking() -> None:
    names = list(WEIGHTS)
    axis_scores = {n: {f"e{i}": 50.0 for i in range(8)} for n in names}
    for n in names:
        axis_scores[n]["eA"] = 0.0
        axis_scores[n]["eB"] = 0.0
    axis_scores[names[0]]["eA"] = 100.0
    axis_scores[names[3]]["eB"] = 100.0
    result = sensitivity(axis_scores, WEIGHTS)
    assert result["stable"] is False
    assert result["churn"]
