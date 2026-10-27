"""Application-level coordination for AutoGrader."""

from typing import Any

from analyzers.preflight import preflight
from analyzers.edge_cases import analyze_edge_cases
from analyzers.problem_reconstruction import reconstruct_problem
from analyzers.source_risks import analyze_source_risks
from app.ai.base import AIProviderError
from app.ai.config import create_ai_provider


def evaluate_submission(
    source: str,
    problem_statement: str | None = None,
    test_cases: list[dict[str, Any]] | None = None,
    *,
    provider: Any = None,
    rules_path: str | None = None,
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
        "preflight": preflight_result,
        "source_risks": source_risks,
        "reconstruction": None,
        "edge_cases": None,
        "correctness_assessed": False,
        "message": None,
    }

    if preflight_result.get("decision") != "continue":
        result["message"] = (
            "Preflight did not allow further analysis. "
            "Correctness has not been assessed."
        )
        return result

    if provider is None:
        try:
            provider = create_ai_provider()
        except AIProviderError as exc:
            result["status"] = "ai_configuration_error"
            result["message"] = str(exc)
            return result

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
        return result

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
        result["status"] = "reconstruction_ready"
        result["message"] = (
            "Problem reconstruction completed. Correctness still requires "
            "validated references and test-based evaluation."
        )

    return result
