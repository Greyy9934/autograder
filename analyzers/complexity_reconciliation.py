"""Evidence reconciliation for AI-primary complexity analysis.

Static analysis and empirical measurements are supporting evidence only.
They can trigger review, but never silently replace the AI assessment.
"""
# In plain terms: This file handles complexity reconciliation, one part of the AutoGrader’s workflow.

import math
from typing import Any


def _is_constant_complexity(expression: Any) -> bool:
    # In simple terms: Helps with is constant complexity.
    # What the inputs mean:
    # - expression: the math formula the graph is asked to draw.
    # What it gives back: It returns yes or no.
    if not isinstance(expression, str):
        return False
    normalized = expression.strip().replace(" ", "").lower()
    return normalized in {"o(1)", "theta(1)", "Θ(1)"}


def _static_review_flags(
    ai_analysis: dict, static_analysis: dict | None
) -> list[dict[str, str]]:
    # In simple terms: Helps with static review flags.
    # What the inputs mean:
    # - ai_analysis: the ai analysis used for this step.
    # - static_analysis: the static analysis used for this step.
    # What it gives back: It returns a list of the items it found or made.
    flags: list[dict[str, str]] = []
    if not isinstance(static_analysis, dict):
        return flags

    time = ai_analysis.get("time_complexity") or {}
    space = ai_analysis.get("space_complexity") or {}
    worst = time.get("worst_case")

    loop_count = static_analysis.get("loop_count", 0)
    loop_depth = static_analysis.get("max_loop_depth_estimate", 0)
    recursive = static_analysis.get("recursive_functions") or []
    allocations = static_analysis.get("dynamic_allocation_count", 0)

    if _is_constant_complexity(worst) and (
        (isinstance(loop_count, int) and loop_count > 0)
        or bool(recursive)
    ):
        flags.append({
            "code": "constant_time_with_input_dependent_structure",
            "severity": "review",
            "message": (
                "AI reports constant worst-case time, while static analysis "
                "detected loop or recursive structure. Inspect bounds and "
                "input dependence; the heuristic does not establish a contradiction."
            ),
        })

    if (
        _is_constant_complexity(worst)
        and isinstance(loop_depth, int)
        and loop_depth >= 2
    ):
        flags.append({
            "code": "constant_time_with_nested_loop_signal",
            "severity": "review",
            "message": (
                "AI reports constant worst-case time, while static analysis "
                "detected nested loop scopes. Verify actual loop bounds and nesting."
            ),
        })

    auxiliary = space.get("auxiliary")
    if _is_constant_complexity(auxiliary) and (
        isinstance(allocations, int) and allocations > 0
    ):
        flags.append({
            "code": "constant_auxiliary_space_with_allocation",
            "severity": "review",
            "message": (
                "AI reports constant auxiliary space, while static analysis "
                "detected dynamic allocation. Inspect allocation sizes and lifetimes."
            ),
        })

    return flags


def _benchmark_summary(benchmark: dict | None) -> dict[str, Any]:
    # In simple terms: Helps with benchmark summary.
    # What the inputs mean:
    # - benchmark: the benchmark used for this step.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(benchmark, dict):
        return {
            "status": "not_supplied",
            "measurement_quality": "unavailable",
            "successful_input_sizes": 0,
            "observations": [],
            "limitations": ["No empirical benchmark was supplied."],
        }

    status = benchmark.get("status")
    results = benchmark.get("results")
    chart_data = benchmark.get("chart_data")
    growth = benchmark.get("growth_observations")

    if not isinstance(results, list):
        results = []
    if not isinstance(chart_data, list):
        chart_data = []
    if not isinstance(growth, list):
        growth = []

    successful_points = []
    for point in chart_data:
        if not isinstance(point, dict):
            continue
        size = point.get("input_size")
        runtime = point.get("median_runtime_seconds")
        measurement_kind = "median"
        if (
            isinstance(size, int) and not isinstance(size, bool) and size > 0
            and isinstance(runtime, (int, float))
            and not isinstance(runtime, bool)
            and math.isfinite(runtime) and runtime >= 0
        ):
            observation = {"input_size": size, "measurement_kind": measurement_kind}
            if isinstance(point.get("median_runtime_seconds"), (int, float)) and not isinstance(point.get("median_runtime_seconds"), bool):
                observation["median_runtime_seconds"] = float(runtime)
            else:
                observation["runtime_seconds"] = float(runtime)
                observation["measurement_kind"] = "single_run"
            successful_points.append(observation)

    failed_runs = sum(
        item.get("failed_runs", 0)
        for item in results
        if isinstance(item, dict)
        and isinstance(item.get("failed_runs", 0), int)
        and not isinstance(item.get("failed_runs", 0), bool)
        and item.get("failed_runs", 0) >= 0
    )

    if status not in {"completed", "completed_with_execution_issues"}:
        quality = "unavailable"
    elif len(successful_points) < 2:
        quality = "insufficient"
    elif failed_runs:
        quality = "partial"
    else:
        quality = "observational"

    limitations = [
        "Runtime ratios are observations, not asymptotic complexity proofs.",
        "Wall-clock measurements include process and sandbox overhead.",
        "Input sizes must meaningfully represent the workload being measured.",
    ]
    if quality in {"unavailable", "insufficient", "partial"}:
        limitations.append(
            "Available successful measurements are insufficient or incomplete "
            "for a reliable runtime-growth comparison."
        )

    return {
        "status": status or "unknown",
        "measurement_quality": quality,
        "successful_input_sizes": len(successful_points),
        "observations": successful_points,
        "growth_observations": growth,
        "failed_runs": failed_runs,
        "limitations": limitations,
    }


def reconcile_complexity_evidence(
    ai_result: dict,
    *,
    static_analysis: dict | None = None,
    benchmark: dict | None = None,
) -> dict[str, Any]:
    """Preserve AI conclusions and attach reviewable supporting evidence."""
    # In simple terms: Preserve AI conclusions and attach reviewable supporting evidence.
    # What the inputs mean:
    # - ai_result: the ai result used for this step.
    # - static_analysis: the static analysis used for this step.
    # - benchmark: the benchmark used for this step.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(ai_result, dict):
        return {
            "status": "invalid_request",
            "message": "ai_result must be an object.",
        }

    if not isinstance(static_analysis, (dict, type(None))):
        return {
            "status": "invalid_request",
            "message": "static_analysis must be an object when provided.",
        }

    if not isinstance(benchmark, (dict, type(None))):
        return {
            "status": "invalid_request",
            "message": "benchmark must be an object when provided.",
        }

    ai_analysis = ai_result.get("ai_analysis")
    if not isinstance(ai_analysis, dict):
        return {
            "status": "not_reconciled",
            "ai_result": ai_result,
            "review_required": True,
            "review_flags": [{
                "code": "ai_analysis_unavailable",
                "severity": "review",
                "message": "A validated AI analysis is required for reconciliation.",
            }],
            "benchmark_summary": _benchmark_summary(benchmark),
        }

    flags = _static_review_flags(ai_analysis, static_analysis)
    benchmark_summary = _benchmark_summary(benchmark)

    return {
        "status": (
            "review_required" if flags or ai_result.get("status") != "analyzed"
            else "reconciled"
        ),
        "analysis_type": "ai_primary_with_evidence_reconciliation",
        "ai_result": ai_result,
        "ai_conclusion_preserved": True,
        "static_analysis": static_analysis,
        "static_analysis_role": "supporting_heuristic_only",
        "benchmark_summary": benchmark_summary,
        "benchmark_role": "empirical_observation_only",
        "review_required": bool(flags) or ai_result.get("status") != "analyzed",
        "review_flags": flags,
        "proof_status": "not_proven",
        "limitations": [
            "Static pattern detection does not establish asymptotic bounds.",
            "Benchmark timings and growth ratios do not prove Big-O complexity.",
            "A review flag identifies evidence requiring inspection; it does not establish that the AI conclusion is false.",
            "Source-line references are structurally checked but their semantic accuracy is not independently proven.",
        ],
    }
