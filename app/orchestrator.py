"""Application-level coordination for AutoGrader."""

from typing import Any

from analyzers.preflight import preflight
from analyzers.reference_solutions import generate_reference_solutions
from analyzers.reference_validation import validate_reference_pair
from analyzers.mathematical_verification import verify_algorithm
from analyzers.edge_cases import analyze_edge_cases
from analyzers.complexity_estimator import estimate_complexity
from analyzers.problem_reconstruction import reconstruct_problem
from analyzers.source_risks import analyze_source_risks
from analyzers.test_cases import analyze_test_cases
from analyzers.memory_safety import analyze_memory_safety
from app.ai.base import AIProviderError
from app.ai.config import create_ai_provider
from app.grading import grade_submission
from app.metric_scoring import derive_metric_scores


def _attach_grading(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a conservative, rule-driven grade to any evaluation result."""
    try:
        scores = derive_metric_scores(result)
        result["metric_scores"] = scores
        result["grading"] = grade_submission(result, scores)
    except (ValueError, OSError) as exc:
        result["metric_scores"] = {}
        result["grading"] = {
            "status": "grading_error",
            "score": None,
            "message": str(exc),
        }
    return result


def evaluate_submission(
    source: str,
    problem_statement: str | None = None,
    test_cases: list[dict[str, Any]] | None = None,
    *,
    provider: Any = None,
    rules_path: str | None = None,
    run_memory_diagnostics: bool = False,
) -> dict[str, Any]:
    """
    Run preflight and heuristic source-risk analysis, then optional
    problem reconstruction. Source-risk findings are not confirmed bugs.
    """
    source_risks = analyze_source_risks(source)

    preflight_result = (
        preflight(source, rules_path=rules_path)
        if rules_path is not None
        else preflight(source)
    )

    result: dict[str, Any] = {
        "status": "preflight_blocked",
        "grading": None,
        "metric_scores": {},
        "preflight": preflight_result,
        "source_risks": source_risks,
        "complexity_estimate": estimate_complexity(source),
        "memory_safety": None,
        "reconstruction": None,
        "edge_cases": None,
        "test_evaluation": None,
        "reference_solutions": None,
        "reference_validation": None,
        "mathematical_verification": None,
        "correctness_assessed": False,
        "message": None,
    }

    if run_memory_diagnostics and preflight_result.get("decision") == "continue":
        result["memory_safety"] = analyze_memory_safety(source)

    if preflight_result.get("decision") != "continue":
        result["message"] = (
            "Preflight did not allow further analysis. "
            "Correctness has not been assessed."
        )
        return _attach_grading(result)

    if test_cases is not None:
        result["test_evaluation"] = analyze_test_cases(source, test_cases)

    if provider is None:
        try:
            provider = create_ai_provider()
        except AIProviderError as exc:
            result["status"] = "ai_configuration_error"
            result["message"] = str(exc)
            return _attach_grading(result)

    try:
        reconstruction = reconstruct_problem(
            source=source,
            problem_statement=problem_statement,
            test_cases=test_cases,
            provider=provider,
        )
    except AIProviderError as exc:
        result["status"] = "ai_provider_error"
        result["message"] = str(exc)
        return _attach_grading(result)

    result["reconstruction"] = reconstruction

    if reconstruction.get("status") == "provider_error":
        result["status"] = "ai_unavailable"
        result["message"] = (
            "Preflight passed, but problem reconstruction was unavailable. "
            "No correctness conclusion has been made."
        )
    elif reconstruction.get("status") == "needs_clarification":
        result["status"] = "needs_clarification"
        result["message"] = (
            "Please clarify the intended problem before correctness grading."
        )
    elif reconstruction.get("status") == "ready" and len(
        reconstruction.get("candidates", [])
    ) > 1:
        result["status"] = "needs_clarification"
        result["message"] = (
            "Multiple problem interpretations remain possible. "
            "Select or clarify the intended problem before correctness grading."
        )
    elif reconstruction.get("status") == "invalid_request":
        result["status"] = "invalid_request"
        result["message"] = reconstruction.get("message")
    else:
        candidates = reconstruction.get("candidates", [])
        if reconstruction.get("status") == "ready" and len(candidates) == 1:
            selected_problem = dict(candidates[0])
            selected_problem["constraints"] = reconstruction.get("constraints", [])
            result["edge_cases"] = analyze_edge_cases(selected_problem)
            if provider is not None:
                references = generate_reference_solutions(selected_problem, provider)
                result["reference_solutions"] = references

                if references.get("status") == "generated_unverified":
                    result["mathematical_verification"] = verify_algorithm(
                        selected_problem,
                        references.get("efficient", {}),
                        provider,
                    )

                if (
                    references.get("status") == "generated_unverified"
                    and isinstance(test_cases, list)
                    and test_cases
                ):
                    brute = references.get("brute_force", {})
                    efficient = references.get("efficient", {})
                    result["reference_validation"] = validate_reference_pair(
                        brute.get("code", ""),
                        efficient.get("code", ""),
                        test_cases,
                    )
                    references["validation"] = {
                        **references.get("validation", {}),
                        "supplied_cases_checked": True,
                        "compiled_and_passed_supplied_cases": (
                            result["reference_validation"]["brute_force"]["passed"]
                            and result["reference_validation"]["efficient"]["passed"]
                        ),
                        "differentially_tested": bool(
                            result["reference_validation"]["comparisons"]
                        )
                        and all(
                            item["outputs_agree"]
                            for item in result["reference_validation"]["comparisons"]
                        ),
                    }
        result["status"] = "reconstruction_ready"
        result["message"] = (
            "Problem reconstruction completed. Correctness still requires "
            "validated references and test-based evaluation."
        )

    return _attach_grading(result)
