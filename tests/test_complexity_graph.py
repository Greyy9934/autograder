import math

import pytest

from analyzers.complexity_graph import (
    MAX_EVALUATIONS,
    PRESET_NOTATIONS,
    generate_complexity_graph,
    list_preset_notations,
)


def test_at_least_fifty_presaved_notation_patterns():
    assert len(list_preset_notations()) >= 50
    assert len(set(PRESET_NOTATIONS)) == len(PRESET_NOTATIONS)


@pytest.mark.parametrize(
    "notation",
    [
        "O(1)",
        "O(log n)",
        "O(n)",
        "O(n log n)",
        "O(n^2)",
        "O(n^2 log n)",
        "O(2^n)",
        "O(n!)",
        "O(sqrt(n))",
        "Theta(n^3)",
        "O(n/log(n))",
    ],
)
def test_supported_notations_generate_dynamic_points(notation):
    result = generate_complexity_graph(notation)
    assert result["status"] == "completed"
    assert result["original_notation"] == notation
    assert len(result["points"]) >= 2
    assert result["curve_type"] == "exact_expression_evaluation"
    assert all(math.isfinite(point["x"]) for point in result["points"])
    assert all(math.isfinite(point["y"]) for point in result["points"])


def test_exponential_curve_uses_logarithmic_y_axis():
    result = generate_complexity_graph("O(2^n)")
    assert result["status"] == "completed"
    assert result["axis"]["y_scale"] == "logarithmic"
    assert result["points"][-1]["x"] < 1024


def test_slow_logarithmic_curve_uses_wide_geometric_input_range():
    result = generate_complexity_graph("O(log(n))")
    assert result["status"] == "completed"
    assert result["points"][-1]["x"] >= 1024
    assert result["axis"]["x_scale"] == "logarithmic"


def test_equivalent_notation_normalizes_to_same_expression():
    left = generate_complexity_graph("O(n*n)")
    right = generate_complexity_graph("O(n^2)")
    assert left["status"] == right["status"] == "completed"
    assert left["normalized_expression"] == right["normalized_expression"]


def test_factorial_uses_safe_log_gamma_evaluation():
    result = generate_complexity_graph("O(n!)")
    assert result["status"] == "completed"
    assert result["axis"]["y_scale"] == "logarithmic"
    assert all(math.isfinite(point["y"]) for point in result["points"])


@pytest.mark.parametrize(
    "notation",
    [
        "__import__('os').system('echo unsafe')",
        "open('/etc/passwd')",
        "n.__class__",
        "unknown_function(n)",
        "O(n / 0)",
        "",
    ],
)
def test_unsafe_or_invalid_expressions_are_rejected(notation):
    result = generate_complexity_graph(notation)
    assert result["status"] == "invalid_expression"
    assert result["points"] == []


def test_sampling_limits_are_enforced():
    result = generate_complexity_graph("O(n)", max_evaluations=MAX_EVALUATIONS + 1)
    assert result["status"] == "invalid_limits"


def test_output_point_limit_is_enforced():
    result = generate_complexity_graph("O(n)", max_points=10)
    assert result["status"] == "completed"
    assert len(result["points"]) <= 10


def test_original_ai_notation_is_preserved_for_heading():
    notation = "O(n^2 log n)"
    result = generate_complexity_graph(notation)
    assert result["original_notation"] == notation



def test_parameterized_expression_requires_explicit_parameters():
    missing = generate_complexity_graph("O(n^k)")
    supplied = generate_complexity_graph("O(n^k)", parameters={"k": 2.5})

    assert missing["status"] == "invalid_expression"
    assert supplied["status"] == "completed"
    assert supplied["parameters"] == {"k": 2.5}


def test_parameterized_exponential_uses_explicit_base():
    result = generate_complexity_graph("O(c^n)", parameters={"c": 1.5})

    assert result["status"] == "completed"
    assert result["parameters"] == {"c": 1.5}


def test_large_values_keep_logarithmic_coordinates_without_clipping():
    result = generate_complexity_graph("O(2^(2^n))")

    assert result["status"] == "completed"
    assert result["axis"]["y_scale"] == "logarithmic"
    assert len(result["points"]) >= 2
    assert all(math.isfinite(point["y"]) for point in result["points"])
    assert all(math.isfinite(point["log10_y"]) for point in result["points"])
    assert result["points"][-1]["log10_y"] > result["points"][0]["log10_y"]
    assert all(
        point["raw_y"] is None or math.isfinite(point["raw_y"])
        for point in result["points"]
    )
    assert all(isinstance(point["raw_y_text"], str) for point in result["points"])

def test_unseen_valid_expression_is_not_rejected_by_preset_library():
    result = generate_complexity_graph("O(n^7 + n^3)")

    assert result["status"] == "completed"
    assert result["preset_match"] is False
