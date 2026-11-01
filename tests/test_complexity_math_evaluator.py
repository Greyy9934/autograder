import pytest

from analyzers.complexity_math import (
    EvaluationLimits,
    evaluate_complexity_expression,
    parse_complexity_expression,
)


def evaluate(notation, n=16, *, parameters=None, **kwargs):
    parsed = parse_complexity_expression(notation, parameters=parameters)
    assert parsed.status == "completed", parsed.message
    return evaluate_complexity_expression(parsed.expression, n, **kwargs)


@pytest.mark.parametrize(
    ("notation", "n", "expected"),
    [
        ("O(1)", 16, 1),
        ("O(n)", 16, 16),
        ("O(n^2)", 10, 100),
        ("O(n^3 + 2*n)", 4, 72),
        ("O(log2(n))", 8, 3),
        ("O(log10(n))", 100, 2),
        ("O(sqrt(n))", 81, 9),
        ("O(exp(1))", 4, 2.718281828459045),
        ("O(2^n)", 10, 1024),
        ("O(n^k)", 4, 64),
    ],
)
def test_basic_expression_evaluation(notation, n, expected):
    parameters = {"k": 3} if "k" in notation else None
    result = evaluate(notation, n, parameters=parameters)
    assert result.status == "completed"
    assert float(result.value) == pytest.approx(expected, rel=1e-12)


def test_log_star_is_documented_approximation():
    result = evaluate("O(log_star(n))", 16)
    assert result.status == "completed"
    assert result.value == 3
    assert result.approximations


def test_alpha_is_documented_approximation():
    result = evaluate("O(alpha(n))", 16)
    assert result.status == "completed"
    assert result.approximations


@pytest.mark.parametrize(
    ("notation", "n", "error"),
    [
        ("O(log(n))", 0, "input_size_limit"),
        ("O(log(n))", 1, None),
        ("O(1/(n-n))", 10, "division_by_zero"),
        ("O(sqrt(n-20))", 4, "sqrt_domain"),
        ("O(log(n-20))", 4, "log_domain"),
        ("O(factorial(n))", 4, None),
        ("O(factorial(n))", 4, None),
    ],
)
def test_domains_and_valid_factorial(notation, n, error):
    result = evaluate(notation, n)
    if error is None:
        assert result.status == "completed"
    else:
        assert result.status == "invalid"
        assert result.error_code == error


def test_factorial_rejects_non_integer_argument():
    result = evaluate("O(factorial(n))", 3)
    assert result.status == "completed"
    result = evaluate("O(factorial(n/2))", 3)
    assert result.status == "invalid"
    assert result.error_code == "factorial_domain"


def test_factorial_limit_is_enforced():
    result = evaluate(
        "O(factorial(n))",
        100,
        limits=EvaluationLimits(max_factorial_input=50),
    )
    assert result.status == "invalid"
    assert result.error_code == "factorial_limit"


def test_large_values_are_not_saturated_to_arbitrary_ceiling():
    result = evaluate("O(2^n)", 10000)
    assert result.status == "completed"
    assert result.value > 10**100
    assert result.log_value is not None


def test_log_value_is_available_for_positive_results():
    result = evaluate("O(n^2)", 10)
    assert result.log_value is not None


def test_negative_result_has_warning_and_no_log_value():
    result = evaluate("O(-n)", 10)
    assert result.status == "completed"
    assert result.log_value is None
    assert result.warnings


def test_zero_result_has_negative_infinite_log():
    result = evaluate("O(n-n)", 10)
    assert result.status == "completed"
    assert result.value == 0
    assert str(result.log_value) == "-inf"


def test_invalid_input_size_is_rejected():
    parsed = parse_complexity_expression("O(n)")
    assert evaluate_complexity_expression(parsed.expression, 0).error_code == "input_size_limit"
    assert evaluate_complexity_expression(parsed.expression, True).error_code == "invalid_input_size"


def test_invalid_expression_object_is_rejected():
    result = evaluate_complexity_expression(None, 10)
    assert result.status == "invalid"
    assert result.error_code == "invalid_expression"


def test_operation_limit_is_enforced():
    result = evaluate(
        "O((n+1)*(n+2))",
        10,
        limits=EvaluationLimits(max_operations=3),
    )
    assert result.status == "invalid"
    assert result.error_code == "operation_limit"


def test_json_friendly_result_preserves_large_number_as_text():
    result = evaluate("O(2^n)", 10000)
    serialized = result.to_dict()
    assert isinstance(serialized["value"], str)
    assert isinstance(serialized["log_value"], str)


def test_variable_exponent_can_grow_with_input_size():
    result = evaluate(
        "O(2^n)",
        1000000,
        limits=EvaluationLimits(max_absolute_exponent=10000),
    )
    assert result.status == "completed"
    assert result.log_value is not None
    assert result.log_value > 600000


def test_variable_exponent_still_obeys_global_input_limit():
    parsed = parse_complexity_expression("O(2^n)")
    result = evaluate_complexity_expression(
        parsed.expression,
        1000001,
        limits=EvaluationLimits(
            max_input_size=1000000,
            max_absolute_exponent=10000,
        ),
    )
    assert result.status == "invalid"
    assert result.error_code == "input_size_limit"


def test_fixed_large_exponent_remains_supported_within_parser_limit():
    result = evaluate("O(n^10000)", 2)
    assert result.status == "completed"
    assert result.log_value is not None


def test_result_reports_default_working_precision():
    result = evaluate("O(n^2)", 10)
    assert result.status == "completed"
    assert result.precision_digits == 50
    assert result.numerical_status == "numerical"
    assert result.is_approximation is False


def test_result_reports_custom_working_precision():
    result = evaluate("O(n^2)", 10, precision=80)
    assert result.status == "completed"
    assert result.precision_digits == 80
    assert result.numerical_status == "numerical"


@pytest.mark.parametrize("notation", ["O(log_star(n))", "O(alpha(n))"])
def test_approximate_functions_are_explicitly_labelled(notation):
    result = evaluate(notation, 16)
    assert result.status == "completed"
    assert result.numerical_status == "approximate"
    assert result.is_approximation is True
    assert result.approximations


def test_result_metadata_is_preserved_in_json_output():
    result = evaluate("O(n^2)", 10, precision=75)
    serialized = result.to_dict()
    assert serialized["precision_digits"] == 75
    assert serialized["numerical_status"] == "numerical"
    assert serialized["is_approximation"] is False


def test_failed_evaluation_does_not_claim_numerical_precision():
    result = evaluate("O(log(n))", 0)
    assert result.status == "invalid"
    assert result.precision_digits is None
    assert result.numerical_status == "not_evaluated"
    assert result.is_approximation is False
