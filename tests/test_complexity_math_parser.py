import pytest

from analyzers.complexity_math import (
    ExpressionLimits,
    parse_complexity_expression,
)


@pytest.mark.parametrize("notation", [
    "O(1)", "O(n)", "O(n^7)", "O(n^2.7)", "O(n^(1/3))",
    "O(log(n))", "O(log n)", "O(log2(n))", "O(log_2 n)",
    "O(ln(n))", "O(sqrt(n))", "O(n*log(n))",
    "O(n log n)", "O(n^2*log(n)^3)", "O(3^n)",
    "O(2^(n^2))", "O(n^n)", "O(n!)", "O((2*n)!)",
    "O(n^log(n))", "O(n^2 + n)", "O((n^3+n^2)/n)",
    "Theta(n^4)", "Ω(n^2)", "O(exp(n))",
    "O(log(n)/log(log(n)))", "O(n*log(log(n)))",
])
def test_general_and_unseen_expression_families_parse(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "completed", result.message
    assert result.expression is not None
    assert result.expression.original_notation == notation


def test_expression_not_in_preset_library_is_accepted():
    result = parse_complexity_expression("O(n^17.35 + 3^(n/7))")
    assert result.status == "completed"


def test_original_notation_is_preserved():
    notation = "Theta(n^2 log n)"
    result = parse_complexity_expression(notation)
    assert result.expression.original_notation == notation
    assert result.expression.notation_family == "theta"


def test_parameters_must_be_explicit():
    missing = parse_complexity_expression("O(n^k)")
    supplied = parse_complexity_expression("O(n^k)", parameters={"k": 4})
    assert missing.error_code == "unknown_symbol"
    assert supplied.status == "completed"
    assert supplied.expression.parameter_values == {"k": 4.0}


@pytest.mark.parametrize("notation", [
    "", "__import__('os').system('id')", "open('/etc/passwd')",
    "n.__class__", "unknown(n)", "n[0]", "lambda x: x",
    "[x for x in range(10)]", "2**100000000",
    "O(n); import os", "log()", "log(n, 2)",
])
def test_unsafe_or_unsupported_syntax_is_rejected(notation):
    result = parse_complexity_expression(notation)
    assert result.status == "invalid"
    assert result.expression is None


def test_expression_character_limit():
    result = parse_complexity_expression("n+" + "1" * 600)
    assert result.error_code == "expression_too_long"


def test_ast_depth_limit():
    limits = ExpressionLimits(max_ast_depth=8)
    result = parse_complexity_expression("n", limits=limits)
    assert result.status == "completed"


def test_parameter_values_are_validated():
    assert parse_complexity_expression("n^k", parameters={"k": float("inf")}).status == "invalid"
    assert parse_complexity_expression("n^k", parameters={"k": True}).status == "invalid"
    assert parse_complexity_expression("n^k", parameters={"k": 2}).status == "completed"


def test_parser_reports_used_functions_and_symbols():
    result = parse_complexity_expression("O(n^2 * log(n))")
    assert result.status == "completed"
    assert "n" in result.expression.symbols
    assert "log" in result.expression.functions
