"""Broad notation and independent-coordinate checks for the complexity plotter."""

import math

import pytest

from analyzers.complexity_graph import (
    PRESET_NOTATIONS,
    generate_complexity_graph,
)


def _family_reference(name, n):
    if name == "constant":
        return 1.0
    if name == "log":
        return math.log(n)
    if name == "log2":
        return math.log2(n)
    if name == "loglog":
        return math.log(math.log(n))
    if name == "log2log10":
        return math.log2(math.log10(n))
    if name == "log_squared":
        return math.log(n) ** 2
    if name == "sqrt":
        return math.sqrt(n)
    if name == "linear":
        return n
    if name == "linear_log":
        return n * math.log(n)
    if name == "linear_loglog":
        return n * math.log(math.log(n))
    if name == "linear_over_log":
        return n / math.log(n)
    if name == "quadratic":
        return n**2
    if name == "quadratic_log":
        return n**2 * math.log(n)
    if name == "quadratic_over_log":
        return n**2 / math.log(n)
    if name == "cubic":
        return n**3
    if name == "exponential_2":
        return 2**n
    if name == "exponential_3":
        return 3**n
    if name == "factorial":
        return math.factorial(int(n))
    if name == "n_to_n":
        return n**n
    if name == "n_to_sqrt_n":
        return n ** math.sqrt(n)
    if name == "two_to_sqrt_n":
        return 2 ** math.sqrt(n)
    if name == "log_star":
        count = 0
        value = n
        while value > 1:
            value = math.log2(value)
            count += 1
        return float(count)
    if name == "inverse_ackermann_approx":
        thresholds = (1, 2, 4, 16, 65536, 2**65536)
        return float(next((level for level, threshold in enumerate(thresholds, 1)
                           if n <= threshold), len(thresholds) + 1))
    raise AssertionError(f"Unknown independent reference family: {name}")


POPULAR_FAMILIES = (
    ("O(1)", "constant", None),
    ("O(log n)", "log", None),
    ("O(log_2 n)", "log2", None),
    ("O(log log n)", "loglog", None),
    ("O(log_2(log_10(n)))", "log2log10", None),
    ("O((log n)^2)", "log_squared", None),
    ("O(sqrt(n))", "sqrt", None),
    ("O(n)", "linear", None),
    ("O(n log n)", "linear_log", None),
    ("O(n log log n)", "linear_loglog", None),
    ("O(n/log n)", "linear_over_log", None),
    ("O(n^2)", "quadratic", None),
    ("O(n^2 log n)", "quadratic_log", None),
    ("O(n^2/log n)", "quadratic_over_log", None),
    ("O(n^3)", "cubic", None),
    ("O(2^n)", "exponential_2", None),
    ("O(3^n)", "exponential_3", None),
    ("O(n!)", "factorial", None),
    ("O(n^n)", "n_to_n", None),
    ("O(n^sqrt(n))", "n_to_sqrt_n", None),
    ("O(2^sqrt(n))", "two_to_sqrt_n", None),
    ("O(log_star(n))", "log_star", None),
    ("O(alpha(n))", "inverse_ackermann_approx", None),
    ("O(n^k)", "parameterized", {"k": 2.5}),
    ("O(c^n)", "parameterized", {"c": 1.5}),
)


@pytest.mark.parametrize("notation", PRESET_NOTATIONS)
def test_every_reference_preset_plots_with_explicit_parameters(notation):
    parameters = {"k": 2.5} if notation == "n**k" else None
    if notation == "c**n":
        parameters = {"c": 1.5}
    result = generate_complexity_graph(
        notation, parameters=parameters, max_points=300
    )
    assert result["status"] == "completed", (notation, result.get("message"))
    assert len(result["points"]) >= 2, notation
    assert len(result["points"]) <= 300, notation
    assert result["sampling"]["evaluations"] <= result["sampling"]["max_evaluations"]


@pytest.mark.parametrize("notation,family,parameters", POPULAR_FAMILIES)
def test_popular_complexity_curves_match_independent_function_values(
    notation, family, parameters
):
    result = generate_complexity_graph(
        notation, parameters=parameters, max_points=300
    )
    assert result["status"] == "completed", (notation, result.get("message"))
    assert len(result["points"]) >= 4, notation
    assert result["axis"]["x_scale"] == "logarithmic", notation
    xs = [point["x"] for point in result["points"]]
    assert xs == sorted(set(xs)), notation

    for point in result["points"]:
        expected = (
            point["x"] ** parameters["k"]
            if family == "parameterized" and "k" in parameters
            else parameters["c"] ** point["x"]
            if family == "parameterized"
            else _family_reference(family, point["x"])
        )
        expected_log10 = math.log10(expected)
        assert math.isclose(
            point["log10_y"], expected_log10,
            rel_tol=2e-9, abs_tol=2e-9,
        ), (notation, point, expected_log10)

        expected_plotted = (
            expected_log10
            if result["axis"]["y_scale"] == "logarithmic"
            else expected
        )
        assert math.isclose(
            point["y"], expected_plotted,
            rel_tol=2e-9, abs_tol=2e-9,
        ), (notation, point, expected_plotted)


@pytest.mark.parametrize(
    "left,right",
    [
        ("O(n²)", "O(n^2)"),
        ("O(√n)", "O(sqrt(n))"),
        ("O(log₂(n))", "O(log_2 n)"),
        ("O(log log n)", "O(log(log(n)))"),
    ],
)
def test_common_notation_variants_normalize_to_equivalent_curves(left, right):
    left_result = generate_complexity_graph(left)
    right_result = generate_complexity_graph(right)
    assert left_result["status"] == "completed", left_result
    assert right_result["status"] == "completed", right_result
    assert left_result["normalized_expression"] == right_result["normalized_expression"]


def test_inverse_ackermann_curve_is_labeled_as_an_approximation():
    result = generate_complexity_graph("O(alpha(n))")
    assert result["status"] == "completed"
    assert result["curve_is_approximation"] is True
    assert any("inverse-Ackermann" in item for item in result["approximations"])
