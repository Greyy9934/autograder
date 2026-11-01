"""Generated and adversarial tests for the restricted complexity parser."""

import math

import pytest
from hypothesis import given, settings, strategies as st

from analyzers.complexity_math import (
    ExpressionLimits,
    parse_complexity_expression,
)


# 100 distinct polynomial and fractional-power expressions.
@pytest.mark.parametrize("power", [i / 4 for i in range(-20, 80)])
def test_generated_polynomial_and_fractional_powers(power):
    result = parse_complexity_expression(f"O(n^{power})")
    assert result.status == "completed", (power, result.message)


# 100 distinct equivalent exponent spellings.
@pytest.mark.parametrize("power", range(1, 101))
def test_caret_and_python_power_notation_are_equivalent(power):
    caret = parse_complexity_expression(f"O(n^{power})")
    python_power = parse_complexity_expression(f"O(n**{power})")

    assert caret.status == "completed", caret.message
    assert python_power.status == "completed", python_power.message
    assert caret.expression.normalized_expression == (
        python_power.expression.normalized_expression
    )


# 75 nested logarithmic combinations.
@pytest.mark.parametrize("power", range(1, 76))
def test_generated_polynomial_logarithmic_combinations(power):
    result = parse_complexity_expression(f"O(n^2 * log(n)^{power})")
    assert result.status == "completed", (power, result.message)
    assert "log" in result.expression.functions


# Hypothesis generates another 100 varied expressions per test run.
@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    coefficient=st.integers(min_value=1, max_value=10**6),
    power=st.integers(min_value=0, max_value=100),
)
def test_generated_coefficient_and_power_expressions(coefficient, power):
    result = parse_complexity_expression(f"O({coefficient}*n^{power})")
    assert result.status == "completed", result.message


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    numerator=st.integers(min_value=1, max_value=100),
    denominator=st.integers(min_value=1, max_value=100),
)
def test_generated_fractional_exponents(numerator, denominator):
    result = parse_complexity_expression(
        f"O(n^({numerator}/{denominator}))"
    )
    assert result.status == "completed", result.message


# Unicode and common mathematical spellings.
@pytest.mark.parametrize("notation", [
    "O(√n)",
    "O(√(n))",
    "O(n × log(n))",
    "O(n · log(n))",
    "O(n − 1)",
    "O(n ÷ log(n))",
    "O(π*n)",
    "O(n²)",
    "O(n³)",
    "Θ(n²)",
    "Ω(n log n)",
])
def test_unicode_mathematical_notation(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "completed", (notation, result.message)


@pytest.mark.parametrize("notation", [
    "O((n^2 + n)/(log(n)+1))",
    "O(log(log(log(n))))",
    "O(sqrt(log(n)))",
    "O(n^(1/2) * log(n))",
    "O(exp(sqrt(n)))",
    "O(n^(log(log(n))))",
    "O((n+1)*(n+2)*(n+3))",
    "O(log(n)/log(log(n)))",
    "O(n^2 + n*log(n) + 1)",
])
def test_nested_functions_and_compound_expressions(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "completed", (notation, result.message)


# 150 adversarial or unsupported expressions.
UNSAFE_EXPRESSIONS = [
    "__import__('os')",
    "open('/etc/passwd')",
    "eval('n')",
    "exec('n')",
    "compile('n', '', 'eval')",
    "globals()",
    "locals()",
    "getattr(n, 'real')",
    "n.__class__",
    "n.__dict__",
    "n[0]",
    "n.real",
    "lambda x: x",
    "[x for x in range(10)]",
    "{x for x in range(10)}",
    "{'x': n}",
    "(x := n)",
    "n if n else 1",
    "n and 1",
    "n or 1",
    "not n",
    "n // 2",
    "n << 2",
    "n >> 2",
    "n & 1",
    "n | 1",
    "log(n, 2)",
    "sqrt()",
    "factorial(n, 2)",
]
UNSAFE_EXPRESSIONS = [
    expression + suffix
    for expression in UNSAFE_EXPRESSIONS
    for suffix in ("", "+1", "*2", "/3")
]


@pytest.mark.parametrize("notation", UNSAFE_EXPRESSIONS)
def test_unsafe_and_unsupported_expression_variants_are_rejected(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "invalid", notation
    assert result.expression is None


@pytest.mark.parametrize("notation", [
    "O(",
    "O(n",
    "O(n))",
    "O((n)",
    "O(n)) extra",
    "O(n);",
    "O(n) + O(n^2)",
    "Theta(",
    "Omega(n",
    "O()",
    "O((n + 1",
    "O(n + ))",
    "O(n **)",
    "O(log(n)",
])
def test_malformed_wrappers_and_parentheses_are_rejected(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "invalid", notation


def test_deeply_nested_expression_respects_ast_depth_limit():
    notation = "O(" + "log(" * 40 + "n" + ")" * 40 + ")"
    result = parse_complexity_expression(
        notation,
        limits=ExpressionLimits(max_ast_depth=12),
    )
    assert result.status == "invalid"
    assert result.error_code == "too_deep"


def test_token_limit_is_enforced():
    result = parse_complexity_expression(
        "O(" + "+".join(["n"] * 150) + ")",
        limits=ExpressionLimits(max_tokens=20),
    )
    assert result.status == "invalid"
    assert result.error_code == "too_many_tokens"


def test_ast_node_limit_is_enforced():
    result = parse_complexity_expression(
        "O(" + "+".join(["n"] * 30) + ")",
        limits=ExpressionLimits(max_ast_nodes=20),
    )
    assert result.status == "invalid"
    assert result.error_code == "too_many_nodes"


@pytest.mark.parametrize("parameters", [
    {"n": 2},
    {"log": 2},
    {"pi": 3},
    {"sqrt": 2},
    {"bad-name": 2},
    {"x": float("nan")},
    {"x": float("inf")},
    {"x": -float("inf")},
    {"x": True},
    {"x": "2"},
])
def test_invalid_parameter_sets_are_rejected(parameters):
    result = parse_complexity_expression("O(n^x)", parameters=parameters)
    assert result.status == "invalid"


def test_missing_parameter_is_rejected_even_in_nested_expression():
    result = parse_complexity_expression("O(n^log(k))")
    assert result.status == "invalid"
    assert result.error_code == "unknown_symbol"


def test_explicit_parameter_is_recorded():
    result = parse_complexity_expression(
        "O(n^k * log(n))",
        parameters={"k": 2.5},
    )
    assert result.status == "completed"
    assert result.expression.parameters == frozenset({"k"})
    assert result.expression.parameter_values["k"] == 2.5


def test_unused_parameter_is_not_reported_as_used():
    result = parse_complexity_expression("O(n^2)", parameters={"k": 3})
    assert result.status == "completed"
    assert result.expression.parameters == frozenset()


@pytest.mark.parametrize("value", [
    1e101,
    1e200,
    10**101,
])
def test_extreme_numeric_literals_are_rejected(value):
    result = parse_complexity_expression(f"O({value})")
    assert result.status == "invalid"


def test_boolean_is_not_accepted_as_notation():
    result = parse_complexity_expression(True)
    assert result.status == "invalid"
    assert result.error_code == "invalid_type"


def test_non_string_parameter_mapping_is_rejected_without_crashing():
    result = parse_complexity_expression("O(n^2)", parameters={"k": math.inf})
    assert result.status == "invalid"


@pytest.mark.parametrize("notation", ["n^2", "n ^ 2", "n^2+1", "n ^ 2*2"])
def test_caret_is_valid_mathematical_exponentiation(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "completed", result.message


# Balanced wrapper parsing and notation-family preservation.

@pytest.mark.parametrize("wrapper,family", [
    ("O", "big_o"),
    ("Theta", "theta"),
    ("Θ", "theta"),
    ("Omega", "omega"),
    ("Ω", "omega"),
    ("BigO", "big_o"),
    ("BigTheta", "theta"),
    ("BigOmega", "omega"),
])
@pytest.mark.parametrize("expression", [
    "n",
    "n^2",
    "log(n)",
    "n^2 + n",
    "(n+1)*(n+2)",
    "log(log(n))",
    "(n^3+n^2)/n",
])
def test_balanced_wrappers_preserve_expression_and_family(
    wrapper, family, expression
):
    result = parse_complexity_expression(f"{wrapper}({expression})")
    assert result.status == "completed", result.message
    assert result.expression.notation_family == family


@pytest.mark.parametrize("notation", [
    "O(",
    "O(n",
    "O(n))",
    "O((n)",
    "O(n)) extra",
    "O()",
    "Theta(",
    "Theta(n))",
    "Omega((n)",
    "BigO(n",
    "O(n) trailing",
    "O(n)) + 1",
])
def test_malformed_asymptotic_wrappers_are_rejected(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "invalid"
    assert result.expression is None


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    power=st.integers(min_value=0, max_value=100),
    wrapper=st.sampled_from([
        "O", "Theta", "Ω", "Omega", "Θ",
    ]),
)
def test_generated_balanced_wrappers(power, wrapper):
    notation = f"{wrapper}(n^{power} + log(n))"
    result = parse_complexity_expression(notation)
    assert result.status == "completed", (notation, result.message)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    depth=st.integers(min_value=1, max_value=20),
    wrapper=st.sampled_from(["O", "Theta", "Omega"]),
)
def test_generated_nested_parentheses_inside_wrappers(depth, wrapper):
    expression = "n"
    for _ in range(depth):
        expression = f"({expression}+1)"

    result = parse_complexity_expression(f"{wrapper}({expression})")
    assert result.status == "completed", result.message


def test_wrapper_with_unbalanced_inner_parentheses_is_rejected():
    result = parse_complexity_expression("O(log((n))")
    assert result.status == "invalid"


def test_wrapper_does_not_accept_trailing_expression():
    result = parse_complexity_expression("O(n^2) + n")
    assert result.status == "invalid"


# Resource and exception safety.

@pytest.mark.parametrize("field,value", [
    ("max_characters", 0),
    ("max_characters", 10001),
    ("max_tokens", -1),
    ("max_ast_nodes", 0),
    ("max_ast_depth", 0),
    ("max_ast_depth", 101),
    ("max_parameter_count", -1),
    ("max_numeric_literal", float("inf")),
    ("max_numeric_literal", float("nan")),
    ("max_exponent_literal", -1),
])
def test_invalid_resource_limits_return_structured_errors(field, value):
    limits = ExpressionLimits(**{field: value})
    result = parse_complexity_expression("O(n^2)", limits=limits)
    assert result.status == "invalid"
    assert result.error_code == "invalid_limits"
    assert result.expression is None


def test_wrong_limits_object_returns_structured_error():
    result = parse_complexity_expression("O(n)", limits=None)
    assert result.status == "invalid"
    assert result.error_code == "invalid_limits"


@pytest.mark.parametrize("parameters", [
    [],
    (),
    "k=2",
    123,
    {"k": 10**1000},
    {"k": float("nan")},
    {"k": float("inf")},
    {"k": True},
])
def test_hostile_parameter_containers_and_values_are_rejected(parameters):
    result = parse_complexity_expression("O(n^k)", parameters=parameters)
    assert result.status == "invalid"
    assert result.expression is None


def test_parameter_count_limit_is_enforced():
    parameters = {f"k{i}": i + 1 for i in range(17)}
    result = parse_complexity_expression("O(n^2)", parameters=parameters)
    assert result.status == "invalid"
    assert result.error_code == "too_many_parameters"


@pytest.mark.parametrize("notation", [
    "O(" + "("*200 + "n" + ")"*200 + ")",
    "O(" + "log("*150 + "n" + ")"*150 + ")",
    "O(" + "+" .join(["n"]*250) + ")",
    "O(" + "1"*513 + ")",
    "O(n" + " "*5000 + ")",
])
def test_adversarial_parser_inputs_never_escape_as_exceptions(notation):
    result = parse_complexity_expression(notation)
    assert result.status in {"invalid", "completed"}
    assert result.expression is None or result.status == "completed"


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    depth=st.integers(min_value=1, max_value=250),
    symbol=st.sampled_from(["n", "pi", "e"]),
)
def test_generated_nested_input_never_crashes_parser(depth, symbol):
    notation = "O(" + "(" * depth + symbol + ")" * depth + ")"
    result = parse_complexity_expression(notation)
    assert result.status in {"invalid", "completed"}


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    count=st.integers(min_value=1, max_value=300),
    operator=st.sampled_from(["+", "*", "/", "^"]),
)
def test_generated_long_operator_chains_are_bounded(count, operator):
    notation = "O(" + operator.join(["n"] * count) + ")"
    result = parse_complexity_expression(notation)
    assert result.status in {"invalid", "completed"}
