"""Problem reconstruction intake and optional AI-provider integration."""

from typing import Any

from app.ai.base import AIProvider, AIProviderError


RECONSTRUCTION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready", "needs_clarification"]},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "problem_statement": {"type": "string"},
                    "input_format": {"type": "string"},
                    "output_format": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "id", "title", "problem_statement", "input_format",
                    "output_format", "evidence", "assumptions", "confidence",
                ],
            },
        },
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status", "candidates", "clarifying_questions", "constraints", "limitations",
    ],
}


def _validate_response(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise AIProviderError("Reconstruction response must be an object.")
    if result.get("status") not in {"ready", "needs_clarification"}:
        raise AIProviderError("Invalid reconstruction status.")

    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 5:
        raise AIProviderError("Candidates must be a list of at most five items.")

    seen = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise AIProviderError("Each candidate must be an object.")
        for field in ("id", "title", "problem_statement", "input_format", "output_format"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise AIProviderError(f"Candidate field {field!r} is required.")
        if item["id"] in seen:
            raise AIProviderError("Candidate IDs must be unique.")
        seen.add(item["id"])

        for field in ("evidence", "assumptions"):
            value = item.get(field)
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise AIProviderError(f"{field} must be a string list.")

        confidence = item.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise AIProviderError("Confidence must be between 0 and 1.")

    for field in ("clarifying_questions", "constraints", "limitations"):
        value = result.get(field)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise AIProviderError(f"{field} must be a string list.")

    if result["status"] == "ready" and not candidates:
        raise AIProviderError("Ready status requires a candidate.")
    if result["status"] == "needs_clarification" and not result["clarifying_questions"]:
        raise AIProviderError("Clarification status requires a question.")
    return result


def reconstruct_problem(
    source: str,
    problem_statement: str | None = None,
    test_cases: list[dict[str, Any]] | None = None,
    provider: AIProvider | None = None,
) -> dict[str, Any]:
    """Accept source-only submissions and optionally invoke an AI provider."""
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "can_continue": False,
            "inferred_problem": None,
            "confidence": "none",
            "message": "Non-empty C source code is required.",
        }
    if problem_statement is not None and not isinstance(problem_statement, str):
        return {
            "status": "invalid_request",
            "can_continue": False,
            "message": "Problem statement must be text when provided.",
        }
    if test_cases is not None and not isinstance(test_cases, list):
        return {
            "status": "invalid_request",
            "can_continue": False,
            "message": "Test cases must be a list when provided.",
        }

    valid_cases = []
    invalid_count = 0
    for case in test_cases or []:
        if (
            isinstance(case, dict)
            and isinstance(case.get("input", ""), str)
            and isinstance(case.get("expected_output"), str)
        ):
            valid_cases.append(case)
        else:
            invalid_count += 1

    statement_provided = bool(
        isinstance(problem_statement, str) and problem_statement.strip()
    )
    payload = {
        "source_code": source,
        "problem_statement": problem_statement,
        "test_cases": valid_cases,
        "instructions": (
            "Infer the likely programming task from source and optional evidence. "
            "Return multiple candidates when materially different interpretations "
            "fit. Separate observed evidence from assumptions. Do not invent "
            "constraints. Missing tests or statement alone must not block analysis."
        ),
    }

    base = {
        "can_continue": True,
        "problem_statement_source": "provided" if statement_provided else "missing",
        "inferred_problem": None,
        "confidence": "not_assessed",
        "available_evidence": ["c_source"],
        "valid_test_case_count": len(valid_cases),
        "invalid_test_case_count": invalid_count,
        "reconstruction_provider": "not_connected",
        "ambiguity_note": (
            "Problem statement is missing; reconstruction is needed."
            if not statement_provided else None
        ),
    }
    if statement_provided:
        base["available_evidence"].append("user_supplied_problem_statement")
    if test_cases is not None:
        base["available_evidence"].append("user_supplied_test_cases")
    if invalid_count:
        base["ambiguity_note"] = (
            (base["ambiguity_note"] + " " if base["ambiguity_note"] else "")
            + f"{invalid_count} invalid test case(s) were ignored."
        )

    if provider is None:
        return {
            **base,
            "status": "ready_for_reconstruction",
            "payload": payload,
        }

    try:
        result = _validate_response(
            provider.generate_json(
                task="Reconstruct the intended programming problem.",
                payload=payload,
                schema=RECONSTRUCTION_SCHEMA,
            )
        )
    except AIProviderError as exc:
        return {
            **base,
            "status": "provider_error",
            "message": str(exc),
        }

    return {
        **base,
        **result,
        "status": result["status"],
        "inferred_problem": result["candidates"][0]["problem_statement"]
        if len(result["candidates"]) == 1 else None,
        "confidence": result["candidates"][0]["confidence"]
        if len(result["candidates"]) == 1 else "multiple_candidates",
        "reconstruction_provider": type(provider).__name__,
        "test_cases_available": bool(valid_cases),
    }
