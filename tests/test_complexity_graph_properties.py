"""Generated tests for adaptive complexity graph sampling."""

import math

from hypothesis import given, settings, strategies as st

from analyzers.complexity_graph import (
    MAX_EVALUATIONS,
    generate_complexity_graph,
)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    exponent=st.integers(min_value=1, max_value=12),
    point_budget=st.integers(min_value=2, max_value=80),
    input_limit=st.integers(min_value=32, max_value=10**8),
)
def test_generated_polynomial_graphs_obey_sampling_budgets(
    exponent, point_budget, input_limit
):
    result = generate_complexity_graph(
        "O(n^k)",
        parameters={"k": float(exponent)},
        max_points=point_budget,
        max_input_size=input_limit,
    )

    assert result["status"] == "completed", result.get("message")
    points = result["points"]
    sampling = result["sampling"]

    assert 2 <= len(points) <= point_budget
    assert sampling["evaluations"] <= MAX_EVALUATIONS
    assert sampling["evaluations"] <= sampling["max_evaluations"]
    assert all(1 <= point["x"] <= input_limit for point in points)
    assert all(
        left["x"] < right["x"]
        for left, right in zip(points, points[1:])
    )
    assert all(math.isfinite(point["y"]) for point in points)
    assert all(math.isfinite(point["log10_y"]) for point in points)


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    base_milli=st.integers(min_value=1050, max_value=5000),
    input_limit=st.integers(min_value=64, max_value=10000),
)
def test_generated_exponential_graphs_remain_bounded_and_ordered(
    base_milli, input_limit
):
    base = base_milli / 1000

    result = generate_complexity_graph(
        "O(c^n)",
        parameters={"c": base},
        max_input_size=input_limit,
    )

    assert result["status"] == "completed", result.get("message")
    points = result["points"]
    sampling = result["sampling"]

    assert len(points) >= 2
    assert len(points) <= sampling["max_points"]
    assert sampling["evaluations"] <= sampling["max_evaluations"]
    assert all(point["x"] <= input_limit for point in points)
    assert all(
        left["x"] < right["x"]
        for left, right in zip(points, points[1:])
    )
    assert all(math.isfinite(point["y"]) for point in points)
    assert result["axis"]["y_scale"] in {"linear", "logarithmic"}
    assert sampling["method"] == (
        "adaptive_geometric_range_and_curvature_refinement"
    )
