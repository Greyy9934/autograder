"""Generated approximation, fallback and parameter-boundary tests."""

import json

import mpmath as mp
from hypothesis import given, settings, strategies as st

from analyzers.complexity_math import (
    evaluate_complexity_expression,
    parse_complexity_expression,
)
from analyzers.complexity_graph import generate_complexity_graph


def evaluate(notation, n, parameters=None):
    parsed = parse_complexity_expression(notation, parameters=parameters)
    assert parsed.status == "completed", parsed.message
    return evaluate_complexity_expression(parsed.expression, n)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    lower=st.integers(min_value=1, max_value=5*10**8),
    gap=st.integers(min_value=0, max_value=5*10**8),
)
def test_log_star_is_monotone_for_generated_ordered_inputs(lower, gap):
    upper = lower + gap
    low_result = evaluate("log_star(n)", lower)
    high_result = evaluate("log_star(n)", upper)

    assert low_result.status == high_result.status == "completed"
    assert low_result.value <= high_result.value
    assert low_result.is_approximation is True
    assert "log_star" in " ".join(low_result.approximations)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    lower=st.integers(min_value=1, max_value=5*10**8),
    gap=st.integers(min_value=0, max_value=5*10**8),
)
def test_alpha_threshold_approximation_is_monotone(lower, gap):
    upper = lower + gap
    low_result = evaluate("alpha(n)", lower)
    high_result = evaluate("alpha(n)", upper)

    assert low_result.status == high_result.status == "completed"
    assert low_result.value <= high_result.value
    assert low_result.is_approximation is True
    assert "threshold-based" in " ".join(low_result.approximations)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    exponent=st.integers(min_value=1, max_value=8),
    n=st.integers(min_value=2, max_value=10000),
)
def test_parameterized_polynomials_preserve_finite_log_values(exponent, n):
    result = evaluate("n^k", n, {"k": exponent})

    assert result.status == "completed"
    assert mp.isfinite(result.value)
    assert mp.isfinite(result.log_value)
    assert mp.almosteq(result.log_value, exponent * mp.log(n))


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    n=st.integers(min_value=2, max_value=10**6),
    precision=st.integers(min_value=20, max_value=100),
)
def test_approximation_metadata_survives_graph_and_json_serialization(n, precision):
    parsed = parse_complexity_expression("log_star(n)")
    assert parsed.status == "completed"

    evaluated = evaluate_complexity_expression(
        parsed.expression, n, precision=precision
    )
    assert evaluated.status == "completed"
    assert evaluated.is_approximation is True
    assert evaluated.numerical_status == "approximate"

    serialized = evaluated.to_dict()
    json.dumps(serialized)
    assert serialized["is_approximation"] is True
    assert serialized["approximations"]

    graph = generate_complexity_graph("O(log_star(n))")
    assert graph["status"] == "completed"
    assert graph["curve_is_approximation"] is True
    assert graph["approximations"]
    assert any(point["x"] >= 2 for point in graph["points"])


def test_alpha_graph_reports_approximation_limitation():
    graph = generate_complexity_graph("O(alpha(n))")

    assert graph["status"] == "completed"
    assert graph["curve_is_approximation"] is True
    assert any("inverse-Ackermann" in item for item in graph["approximations"])
    assert any("approximation" in item.lower() for item in graph["limitations"])


def test_invalid_approximation_domain_is_reported_safely():
    for notation in ("log_star(n-10)", "alpha(n-10)"):
        parsed = parse_complexity_expression(notation)
        assert parsed.status == "completed"

        result = evaluate_complexity_expression(parsed.expression, 1)
        assert result.status == "invalid"
        assert result.value is None
        assert result.numerical_status == "not_evaluated"
        assert result.is_approximation is False


def test_failed_evaluation_serializes_without_non_finite_values():
    parsed = parse_complexity_expression("log(n-10)")
    result = evaluate_complexity_expression(parsed.expression, 1)

    assert result.status == "invalid"
    payload = result.to_dict()
    encoded = json.dumps(payload, allow_nan=False)
    assert '"status": "invalid"' in encoded
    assert payload["value"] is None
    assert payload["log_value"] is None
