from copy import deepcopy

from analyzers.complexity_reconciliation import reconcile_complexity_evidence
from app.ai.mock_scenarios import get_scenario


def ai_result(name="linear_scan"):
    scenario = get_scenario("agent4", name)
    return {
        "status": scenario["status"],
        "analysis_type": "ai_primary",
        "ai_analysis": scenario,
        "proof_status": "not_proven",
    }


def test_reconciliation_preserves_ai_conclusion():
    original = ai_result()
    result = reconcile_complexity_evidence(original)
    assert result["status"] == "reconciled"
    assert result["ai_result"] == original
    assert result["ai_conclusion_preserved"] is True


def test_static_loop_signal_flags_constant_time_ai_claim():
    original = ai_result("plausible_but_wrong")
    static = {
        "status": "completed",
        "loop_count": 1,
        "max_loop_depth_estimate": 1,
        "recursive_functions": [],
        "dynamic_allocation_count": 0,
    }
    result = reconcile_complexity_evidence(
        original, static_analysis=static
    )
    assert result["status"] == "review_required"
    assert any(
        flag["code"] == "constant_time_with_input_dependent_structure"
        for flag in result["review_flags"]
    )
    assert result["ai_result"]["ai_analysis"]["time_complexity"]["worst_case"] == "O(1)"


def test_nested_loop_signal_is_reported_without_claiming_proof():
    static = {
        "loop_count": 2,
        "max_loop_depth_estimate": 2,
        "recursive_functions": [],
        "dynamic_allocation_count": 0,
    }
    result = reconcile_complexity_evidence(
        ai_result("plausible_but_wrong"), static_analysis=static
    )
    assert any(
        flag["code"] == "constant_time_with_nested_loop_signal"
        for flag in result["review_flags"]
    )
    assert result["proof_status"] == "not_proven"


def test_dynamic_allocation_signal_flags_constant_auxiliary_space():
    original = ai_result()
    original["ai_analysis"]["space_complexity"]["auxiliary"] = "O(1)"
    static = {
        "loop_count": 0,
        "max_loop_depth_estimate": 0,
        "recursive_functions": [],
        "dynamic_allocation_count": 1,
    }
    result = reconcile_complexity_evidence(
        original, static_analysis=static
    )
    assert any(
        flag["code"] == "constant_auxiliary_space_with_allocation"
        for flag in result["review_flags"]
    )


def test_benchmark_observations_are_attached_but_not_treated_as_proof():
    benchmark = {
        "status": "completed",
        "results": [
            {"input_size": 100, "failed_runs": 0},
            {"input_size": 200, "failed_runs": 0},
        ],
        "chart_data": [
            {"input_size": 100, "median_runtime_seconds": 0.01},
            {"input_size": 200, "median_runtime_seconds": 0.02},
        ],
        "growth_observations": [
            {
                "from_input_size": 100,
                "to_input_size": 200,
                "input_size_ratio": 2.0,
                "runtime_ratio": 2.0,
                "interpretation": "Observed ratio only; not an asymptotic complexity proof.",
            }
        ],
    }
    result = reconcile_complexity_evidence(ai_result(), benchmark=benchmark)
    summary = result["benchmark_summary"]
    assert summary["measurement_quality"] == "observational"
    assert summary["successful_input_sizes"] == 2
    assert result["benchmark_role"] == "empirical_observation_only"
    assert result["proof_status"] == "not_proven"


def test_incomplete_benchmark_is_marked_insufficient():
    benchmark = {
        "status": "completed_with_execution_issues",
        "results": [{"input_size": 100, "failed_runs": 2}],
        "chart_data": [{"input_size": 100, "median_runtime_seconds": 0.01}],
        "growth_observations": [],
    }
    result = reconcile_complexity_evidence(ai_result(), benchmark=benchmark)
    assert result["benchmark_summary"]["measurement_quality"] == "insufficient"


def test_partial_benchmark_is_marked_partial():
    benchmark = {
        "status": "completed_with_execution_issues",
        "results": [
            {"input_size": 100, "failed_runs": 1},
            {"input_size": 200, "failed_runs": 0},
        ],
        "chart_data": [
            {"input_size": 100, "median_runtime_seconds": 0.01},
            {"input_size": 200, "median_runtime_seconds": 0.02},
        ],
        "growth_observations": [],
    }
    result = reconcile_complexity_evidence(ai_result(), benchmark=benchmark)
    assert result["benchmark_summary"]["measurement_quality"] == "partial"


def test_no_benchmark_is_explicitly_unavailable():
    result = reconcile_complexity_evidence(ai_result())
    assert result["benchmark_summary"]["measurement_quality"] == "unavailable"


def test_inconclusive_ai_requires_review_and_is_preserved():
    original = ai_result("inconclusive")
    result = reconcile_complexity_evidence(original)
    assert result["status"] == "review_required"
    assert result["ai_result"] == original


def test_missing_ai_analysis_does_not_crash():
    result = reconcile_complexity_evidence({"status": "provider_error"})
    assert result["status"] == "not_reconciled"
    assert result["review_required"] is True


def test_invalid_inputs_are_rejected():
    assert reconcile_complexity_evidence(None)["status"] == "invalid_request"
    assert reconcile_complexity_evidence(
        ai_result(), static_analysis="bad"
    )["status"] == "invalid_request"
    assert reconcile_complexity_evidence(
        ai_result(), benchmark="bad"
    )["status"] == "invalid_request"


def test_reconciliation_does_not_mutate_ai_result():
    original = ai_result("plausible_but_wrong")
    before = deepcopy(original)
    reconcile_complexity_evidence(
        original,
        static_analysis={
            "loop_count": 1,
            "max_loop_depth_estimate": 1,
            "recursive_functions": [],
            "dynamic_allocation_count": 0,
        },
    )
    assert original == before
