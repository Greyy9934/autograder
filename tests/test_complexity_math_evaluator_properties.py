import math

import mpmath as mp
import pytest
import sympy as sp
from hypothesis import given, settings, strategies as st

from analyzers.complexity_math import (
    evaluate_complexity_expression,
    parse_complexity_expression,
)


def evaluate(notation, n, parameters=None, precision=50):
    parsed = parse_complexity_expression(notation, parameters=parameters)
    assert parsed.status == "completed", parsed.message
    result = evaluate_complexity_expression(
        parsed.expression, n, precision=precision
    )
    assert result.status == "completed", result.message
    return result.value


@given(
    n=st.integers(min_value=1, max_value=10**6),
    exponent=st.integers(min_value=0, max_value=12),
)
@settings(max_examples=100)
def test_generated_integer_powers_match_python_integer_arithmetic(n, exponent):
    result = evaluate("n^k", n, {"k": exponent}, precision=100)
    assert result == n ** exponent


@given(
    n=st.integers(min_value=1, max_value=10**5),
    exponent=st.integers(min_value=1, max_value=8),
    coefficient=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_generated_polynomials_match_sympy(n, exponent, coefficient):
    result = evaluate(f"{coefficient}*n^{exponent}+n+1", n)
    symbol = sp.Symbol("n")
    reference = coefficient * symbol**exponent + symbol + 1
    expected = int(reference.subs(symbol, n))
    assert result == expected


@given(
    n=st.integers(min_value=2, max_value=10**9),
)
@settings(max_examples=100)
def test_logarithm_base_relationship(n):
    base_two = evaluate("log2(n)", n)
    natural = evaluate("log(n)", n)
    assert mp.almosteq(base_two * mp.log(2), natural)


@given(
    n=st.integers(min_value=1, max_value=10**6),
)
@settings(max_examples=100)
def test_square_root_squared_matches_input(n):
    result = evaluate("sqrt(n)^2", n)
    assert mp.almosteq(result, n)


@given(
    n=st.integers(min_value=1, max_value=1000),
    exponent=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100)
def test_power_multiplication_identity(n, exponent):
    left = evaluate("n^k*n^k", n, {"k": exponent})
    right = evaluate("n^(2*k)", n, {"k": exponent})
    assert mp.almosteq(left, right)


@given(
    n=st.integers(min_value=2, max_value=10**6),
)
@settings(max_examples=100)
def test_logarithm_product_identity(n):
    left = evaluate("log(n*n)", n)
    right = 2 * evaluate("log(n)", n)
    assert mp.almosteq(left, right)


@pytest.mark.parametrize(
    ("notation", "expected"),
    [
        ("n^0", 1),
        ("n^1", 7),
        ("n^2", 49),
        ("n^3", 343),
        ("2^n", 128),
        ("factorial(n)", 5040),
    ],
)
def test_known_exact_values(notation, expected):
    n = 7
    assert evaluate(notation, n) == expected


@pytest.mark.parametrize(
    ("notation", "error_code"),
    [
        ("log_star(-n)", "log_star_domain"),
        ("alpha(-n)", "alpha_domain"),
        ("log(-n)", "log_domain"),
        ("sqrt(-n)", "sqrt_domain"),
        ("factorial(-n)", "factorial_domain"),
    ],
)
def test_negative_function_domains_are_rejected(notation, error_code):
    parsed = parse_complexity_expression(notation)
    assert parsed.status == "completed"
    result = evaluate_complexity_expression(parsed.expression, 10)
    assert result.status == "invalid"
    assert result.error_code == error_code


def test_log_star_values_are_monotone_for_sampled_inputs():
    values = [evaluate("log_star(n)", n) for n in [1, 2, 4, 16, 256, 65536]]
    assert values == sorted(values)


def test_alpha_approximation_is_monotone_for_sampled_inputs():
    values = [
        evaluate("alpha(n)", n)
        for n in [1, 2, 4, 16, 65536, 10**9]
    ]
    assert values == sorted(values)


def test_high_precision_is_respected():
    parsed = parse_complexity_expression("sqrt(2)")
    result = evaluate_complexity_expression(parsed.expression, 2, precision=80)
    assert result.status == "completed"
    assert mp.isfinite(result.value)


def test_large_exponential_keeps_finite_log_value():
    parsed = parse_complexity_expression("exp(n)")
    result = evaluate_complexity_expression(parsed.expression, 10**6)
    assert result.status == "completed"
    assert mp.isfinite(result.value)
    assert mp.isfinite(result.log_value)
    assert mp.almosteq(result.log_value, 10**6)


def test_invalid_precision_is_rejected():
    parsed = parse_complexity_expression("n")
    result = evaluate_complexity_expression(parsed.expression, 10, precision=1000)
    assert result.status == "invalid"
    assert result.error_code == "invalid_precision"


def test_invalid_limits_are_rejected():
    parsed = parse_complexity_expression("n")
    result = evaluate_complexity_expression(
        parsed.expression,
        10,
        limits=object(),
    )
    assert result.status == "invalid"
    assert result.error_code == "invalid_limits"
