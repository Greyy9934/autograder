"""Generated numerical-stability tests for the complexity evaluator."""

import mpmath as mp

from hypothesis import given, settings, strategies as st

from analyzers.complexity_math import (
    evaluate_complexity_expression,
    parse_complexity_expression,
)


def evaluate(notation, n):
    parsed = parse_complexity_expression(notation)
    assert parsed.status == "completed", parsed.message

    result = evaluate_complexity_expression(parsed.expression, n)
    assert result.status == "completed", result.message
    assert result.value is not None
    assert result.log_value is not None
    assert mp.isfinite(result.value)
    assert mp.isfinite(result.log_value)
    return result


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=10**6),
    exponent=st.integers(min_value=0, max_value=20),
)
def test_generated_polynomial_values_and_logarithms_remain_stable(n, exponent):
    result = evaluate(f"n^{exponent}", n)

    expected_log = exponent * mp.log(n)
    assert mp.almosteq(result.log_value, expected_log)

    if exponent == 0:
        assert mp.almosteq(result.value, 1)
    else:
        assert result.value > 0


@settings(max_examples=100, derandomize=True, deadline=None)
@given(n=st.integers(min_value=1, max_value=10000))
def test_generated_factorials_keep_finite_logarithmic_values(n):
    result = evaluate("factorial(n)", n)

    expected_log = mp.loggamma(n + 1)
    assert mp.almosteq(result.log_value, expected_log)
    assert result.value > 0


@settings(max_examples=100, derandomize=True, deadline=None)
@given(n=st.integers(min_value=1, max_value=10**6))
def test_generated_exponentials_preserve_logarithmic_values(n):
    result = evaluate("exp(n)", n)

    assert mp.almosteq(result.log_value, n)
    assert result.value > 0
