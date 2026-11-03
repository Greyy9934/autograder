"""Safe graph generation using the shared Agent 4 mathematical engine.

Presets are reference metadata only. Every expression is parsed and evaluated
through complexity_math; no AI-provided expression is executed as Python.
"""
# It draws the general shape of a complexity formula, separately from measured program times.

from __future__ import annotations

import math
from typing import Any

import mpmath as mp

from analyzers.complexity_math import (
    EvaluationLimits,
    parse_complexity_expression,
    evaluate_complexity_expression,
)

MAX_EVALUATIONS = 2000
MAX_PLOT_POINTS = 300
MAX_RANGE_EXPANSIONS = 20
MAX_INPUT_SIZE = 10**12
MAX_ABS_VALUE = 1e300

# Reference metadata only. These patterns are not an expression whitelist.
PRESET_NOTATIONS = (
    "1", "log(log(n))", "log(n)", "log(n)**2", "log(n)**3",
    "sqrt(log(n))", "n**(1/4)", "n**(1/3)", "n**(1/2)",
    "n**(2/3)", "n**(3/4)", "n**(4/5)", "n**(9/10)",
    "n", "n/log(n)", "n*log(log(n))", "n*log(n)",
    "n*log(n)**2", "n*log(n)**3", "n**(11/10)",
    "n**(6/5)", "n**(3/2)", "n**(9/5)", "n**2",
    "n**2/log(n)", "n**2/log(n)**2", "n**2*log(log(n))",
    "n**2*log(n)", "n**2*log(n)**2", "n**(21/10)",
    "n**(5/2)", "n**(14/5)", "n**(29/10)", "n**3",
    "n**3*log(log(n))", "n**3*log(n)", "n**3*log(n)**2",
    "n**4", "n**4*log(n)", "n**5", "n**6", "n**k",
    "n**log(n)", "n**sqrt(n)", "2**sqrt(n)", "2**(n/2)",
    "2**n", "2**(2*n)", "3**n", "4**n", "5**n", "c**n",
    "2**(n*log(n))", "factorial(n)", "factorial(n/2)",
    "factorial(2*n)", "n**n", "n**(n/2)", "2**(n**2)",
    "2**(n**3)", "2**(2**n)", "2**(2**(2**n))",
    "alpha(n)", "log_star(n)", "log(n)/log(log(n))",
    "n**(3/2)*log(n)", "n**(5/2)*log(n)", "2**n/sqrt(n)",
)


def _candidate_sizes(max_input_size: int) -> list[int]:
    """Create dense small-input samples followed by bounded geometric samples."""
    # Handles candidate sizes as a supporting part of complexity graph .
    # What the inputs mean:
    # - max_input_size: the largest input size to include in the formula chart.
    # What it gives back: It returns a list of the items it found or made.
    dense_end = min(16, max_input_size)
    values = list(range(1, dense_end + 1))

    n = 32
    while n <= max_input_size and len(values) < MAX_PLOT_POINTS:
        values.append(n)
        n *= 2

    return values


def _preset_match(normalized_expression: str) -> bool:
    """Check metadata equivalence without restricting accepted expressions."""
    # Handles preset match as a supporting part of complexity graph .
    # What the inputs mean:
    # - normalized_expression: the normalized expression used for this step.
    # What it gives back: It returns yes or no.
    for notation in PRESET_NOTATIONS:
        parsed = parse_complexity_expression(notation)
        if (
            parsed.status == "completed"
            and parsed.expression is not None
            and parsed.expression.normalized_expression == normalized_expression
        ):
            return True
    return False


def _failure(
    notation: Any,
    status: str = "invalid_expression",
    message: str = "A valid supported asymptotic expression is required.",
    **extra: Any,
) -> dict[str, Any]:
    # Helps with preset match inside preset match.
    # What the inputs mean:
    # - notation: the complexity formula written as text.
    # - status: the current result label.
    # - message: the message used for this step.
    # - extra: the extra used for this step.
    # What it gives back: It returns a set of named results for the next step.
    return {
        "status": status,
        "original_notation": notation if isinstance(notation, str) else None,
        "points": [],
        "axis": {},
        "message": message,
        **extra,
    }


def generate_complexity_graph(
    notation: str,
    *,
    parameters: dict[str, float] | None = None,
    max_points: int = 120,
    max_input_size: int = MAX_INPUT_SIZE,
    max_evaluations: int = MAX_EVALUATIONS,
) -> dict[str, Any]:
    """Generate graph coordinates from the shared validated math engine.

    Parameters must be supplied explicitly. For example:
        generate_complexity_graph("O(n^k)", parameters={"k": 2.5})
    """
    # Creates chart points for a complexity formula, adding more points where the curve bends noticeably.
    # What the inputs mean:
    # - notation: the complexity formula written as text.
    # - parameters: the named number values used in a formula.
    # - max_points: the most chart dots to draw.
    # - max_input_size: the largest input size to include in the formula chart.
    # - max_evaluations: the limit on formula calculations.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(notation, str) or not notation.strip():
        return _failure(notation)

    if len(notation) > 512:
        return _failure(
            notation,
            message="Notation exceeds the mathematical parser's character limit.",
        )

    if (
        not isinstance(max_points, int)
        or isinstance(max_points, bool)
        or not 2 <= max_points <= MAX_PLOT_POINTS
        or not isinstance(max_input_size, int)
        or isinstance(max_input_size, bool)
        or not 2 <= max_input_size <= MAX_INPUT_SIZE
        or not isinstance(max_evaluations, int)
        or isinstance(max_evaluations, bool)
        or not 2 <= max_evaluations <= MAX_EVALUATIONS
    ):
        return _failure(
            notation,
            status="invalid_limits",
            message="Graph-generation limits are outside the permitted bounds.",
        )

    parsed = parse_complexity_expression(notation, parameters=parameters)

    if parsed.status != "completed" or parsed.expression is None:
        return _failure(
            notation,
            message=parsed.message,
            error_code=parsed.error_code,
            parser_details=parsed.details,
            parameters_supplied=parameters or {},
        )

    expression = parsed.expression
    candidates = _candidate_sizes(max_input_size)
    candidates = candidates[:max_points]
    candidates = candidates[:max_evaluations]

    evaluation_limits = EvaluationLimits(max_input_size=max_input_size)

    evaluated: list[dict[str, Any]] = []
    approximation_labels: set[str] = set()
    evaluation_warnings: set[str] = set()
    evaluation_errors: list[dict[str, Any]] = []
    evaluation_count = 0
    range_expansions = 0

    for n in candidates:
        if evaluation_count >= max_evaluations:
            break
        evaluation_count += 1
        if n > 16:
            range_expansions += 1
        result = evaluate_complexity_expression(
            expression,
            n,
            limits=evaluation_limits,
        )

        if result.status != "completed" or result.value is None:
            evaluation_errors.append({
                "input_size": n,
                "error_code": result.error_code,
                "message": result.message,
            })
            continue

        if result.log_value is None:
            evaluation_errors.append({
                "input_size": n,
                "error_code": "missing_log_value",
                "message": "The evaluator did not return logarithmic value information.",
            })
            continue

        if not mp.isfinite(result.value) or result.value <= 0:
            evaluation_errors.append({
                "input_size": n,
                "error_code": "non_positive_growth",
                "message": "Graph points require finite positive growth values.",
            })
            continue

        log10_value = result.log_value / mp.log(10)

        if not mp.isfinite(log10_value):
            evaluation_errors.append({
                "input_size": n,
                "error_code": "invalid_log_value",
                "message": "The logarithmic growth value is not finite.",
            })
            continue

        log10_float = float(log10_value)
        raw_y = None

        # Keep a numeric raw value only when it is safely representable.
        if abs(log10_float) <= 300:
            try:
                candidate_raw = float(result.value)
                if math.isfinite(candidate_raw) and abs(candidate_raw) <= MAX_ABS_VALUE:
                    raw_y = candidate_raw
            except (OverflowError, ValueError):
                pass

        evaluated.append({
            "x": n,
            "raw_y": raw_y,
            "raw_y_text": mp.nstr(result.value, 18),
            "log10_y": log10_float,
            "numerical_status": result.numerical_status,
            "precision_digits": result.precision_digits,
            "is_approximation": result.is_approximation,
        })

        approximation_labels.update(result.approximations)
        evaluation_warnings.update(result.warnings)

        if len(evaluated) >= 5:
            observed_logs = [item["log10_y"] for item in evaluated]
            if max(observed_logs) - min(observed_logs) >= 36:
                break

    # Adaptive refinement: test geometric midpoints in log-input space.
    # Only retain a midpoint when it reveals meaningful curvature.
    attempted_midpoints: set[int] = set()
    adaptive_refinements = 0
    curvature_tolerance = 0.15

    for _ in range(8):
        if evaluation_count >= max_evaluations or len(evaluated) >= max_points:
            break

        ordered = sorted(evaluated, key=lambda item: item["x"])
        additions: list[dict[str, Any]] = []

        for left, right in zip(ordered, ordered[1:]):
            if evaluation_count >= max_evaluations:
                break
            if len(evaluated) + len(additions) >= max_points:
                break

            midpoint = int(mp.sqrt(left["x"] * right["x"]))
            if midpoint <= left["x"] or midpoint >= right["x"]:
                continue
            if midpoint in attempted_midpoints:
                continue

            attempted_midpoints.add(midpoint)
            evaluation_count += 1

            result = evaluate_complexity_expression(
                expression,
                midpoint,
                limits=evaluation_limits,
            )

            if (
                result.status != "completed"
                or result.value is None
                or result.log_value is None
                or not mp.isfinite(result.value)
                or result.value <= 0
            ):
                evaluation_errors.append({
                    "input_size": midpoint,
                    "error_code": result.error_code or "invalid_midpoint",
                    "message": result.message or "Adaptive midpoint was not evaluable.",
                })
                continue

            log10_value = result.log_value / mp.log(10)
            if not mp.isfinite(log10_value):
                continue

            midpoint_log = float(log10_value)
            left_t = math.log2(left["x"])
            right_t = math.log2(right["x"])
            midpoint_t = math.log2(midpoint)
            fraction = (midpoint_t - left_t) / (right_t - left_t)
            linear_estimate = (
                left["log10_y"]
                + fraction * (right["log10_y"] - left["log10_y"])
            )
            curvature_error = abs(midpoint_log - linear_estimate)

            if curvature_error <= curvature_tolerance:
                continue

            raw_y = None
            if abs(midpoint_log) <= 300:
                try:
                    candidate_raw = float(result.value)
                    if math.isfinite(candidate_raw) and abs(candidate_raw) <= MAX_ABS_VALUE:
                        raw_y = candidate_raw
                except (OverflowError, ValueError):
                    pass

            additions.append({
                "x": midpoint,
                "raw_y": raw_y,
                "raw_y_text": mp.nstr(result.value, 18),
                "log10_y": midpoint_log,
                "numerical_status": result.numerical_status,
                "precision_digits": result.precision_digits,
                "is_approximation": result.is_approximation,
            })

            approximation_labels.update(result.approximations)
            evaluation_warnings.update(result.warnings)

        if not additions:
            break

        evaluated.extend(additions)
        adaptive_refinements += len(additions)

    evaluated.sort(key=lambda item: item["x"])

    if len(evaluated) < 2:
        return _failure(
            notation,
            message=(
                "The expression did not produce at least two valid positive "
                "growth values in the permitted input range."
            ),
            normalized_expression=expression.normalized_expression,
            parameters=expression.parameter_values,
            evaluation_errors=evaluation_errors[:20],
        )

    log_values = [point["log10_y"] for point in evaluated]
    log_span = max(log_values) - min(log_values)
    use_log_y = (
        log_span > 4
        or max(log_values) > 100
        or any(item["raw_y"] is None for item in evaluated)
    )

    points = []
    for item in evaluated:
        plotted_y = item["log10_y"] if use_log_y else item["raw_y"]

        # If the raw value cannot be represented, logarithmic plotting is
        # mandatory; never substitute a clipped or fabricated coordinate.
        if plotted_y is None:
            use_log_y = True
            plotted_y = item["log10_y"]

        points.append({
            "x": item["x"],
            "y": plotted_y,
            "raw_y": item["raw_y"],
            "raw_y_text": item["raw_y_text"],
            "log10_y": item["log10_y"],
        })

    if use_log_y:
        for point in points:
            point["y"] = point["log10_y"]

    preset = _preset_match(expression.normalized_expression)

    curve_is_approximation = bool(approximation_labels)

    limitations = [
        "The curve represents the supplied asymptotic expression, not measured runtime.",
        "Big-O omits constants and lower-order terms.",
        "Parameterized expressions require explicit parameter values; no defaults are assumed.",
        "The mathematical expression grammar is restricted for safety.",
        "Numerical evaluation is finite-precision and is not a proof of asymptotic complexity.",
        "Sampling uses bounded range discovery and curvature-based refinement.",
    ]

    if curve_is_approximation:
        limitations.append(
            "Some mathematical functions use documented representative approximations: "
            + ", ".join(sorted(approximation_labels))
        )

    return {
        "status": "completed",
        "original_notation": notation.strip(),
        "normalized_expression": expression.normalized_expression,
        "preset_match": preset,
        "curve_type": "exact_expression_evaluation",
        "curve_is_approximation": curve_is_approximation,
        "parameters": dict(expression.parameter_values),
        # Kept for compatibility, but intentionally empty: there are no defaults.
        "parameter_defaults": {},
        "approximations": sorted(approximation_labels),
        "warnings": sorted(evaluation_warnings),
        "evaluation_errors": evaluation_errors[:20],
        "points": points,
        "axis": {
            "x_scale": "logarithmic",
            "y_scale": "logarithmic" if use_log_y else "linear",
            "y_transform": "log10(value)" if use_log_y else "identity",
            "x_label": "Input size n",
            "y_label": "log10(growth function)" if use_log_y else "Representative growth",
        },
        "sampling": {
            "method": "adaptive_geometric_range_and_curvature_refinement",
            "evaluations": evaluation_count,
            "successful_evaluations": len(evaluated),
            "failed_evaluations": len(evaluation_errors),
            "points_returned": len(points),
            "adaptive_refinements": adaptive_refinements,
            "max_evaluations": max_evaluations,
            "max_points": max_points,
            "max_input_size": max_input_size,
            "range_expansions": range_expansions,
            "range_strategy": (
                "Dense initial samples followed by geometric range expansion; "
                "expansion stops after a bounded growth span is observed. "
                "Geometric midpoints are added when curvature exceeds the "
                "configured tolerance."
            ),
            "curvature_tolerance_log10": curvature_tolerance,
        },
        "limitations": limitations,
        "message": (
            "Coordinates were generated by the shared validated mathematical "
            "parser and evaluator."
        ),
    }


def list_preset_notations() -> list[str]:
    """Return the reference notation-pattern library."""
    # Lists preset notations.
    # This function takes no named inputs.
    # What it gives back: It returns a list of the items it found or made.
    return list(PRESET_NOTATIONS)
