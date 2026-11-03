"""AI-led mathematical correctness analysis for student algorithms.

The result is an AI-generated mathematical argument, not a mechanically
verified formal proof.
"""
# Module role: Implements the mathematical verification subsystem used by the AutoGrader workflow.

from typing import Any

from app.ai.base import AIProvider, AIProviderError
from app.ai.output_budget import TASK_MATHEMATICAL_PROOF


VERIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["counterexample_found", "proof_sketch", "inconclusive"],
        },
        "theorem": {"type": "string", "maxLength": 400},
        "preconditions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 220}},
        "postconditions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 220}},
        "assumptions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 220}},
        "proof_strategy": {"type": "string", "maxLength": 300},
        "proof_steps": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "maxLength": 220},
                    "justification": {"type": "string", "maxLength": 320},
                    "equation": {"type": "string", "maxLength": 180},
                },
                "required": ["claim", "justification", "equation"],
            },
        },
        "conclusion": {"type": "string", "maxLength": 400},
        "counterexample": {
            "type": ["object", "null"],
            "properties": {
                "input": {"type": "string", "maxLength": 4096},
                "expected_behavior": {"type": "string", "maxLength": 240},
                "observed_or_predicted_behavior": {"type": "string", "maxLength": 240},
                "explanation": {"type": "string", "maxLength": 400},
            },
            "required": [
                "input",
                "expected_behavior",
                "observed_or_predicted_behavior",
                "explanation",
            ],
        },
        "limitations": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
    },
    "required": [
        "outcome", "theorem", "preconditions", "postconditions",
        "assumptions", "proof_strategy", "proof_steps", "conclusion",
        "counterexample", "limitations",
    ],
}


# Function role: Returns the module's standard invalid-input result without running analysis.
# Same-file callers: verify_algorithm.
def _invalid(message: str) -> dict[str, Any]:
    return {
        "status": "invalid_request",
        "formally_verified": False,
        "message": message,
    }


# Function role: Ask an AI reviewer for a rigorous, problem-specific correctness proof.
# Numbered workflow order: 06.2b - Agent 5 advisory proof sketch/counterexample request.
# Direct call references (conditional/branch-dependent): _invalid.
def verify_algorithm(
    problem: dict[str, Any],
    algorithm: dict[str, Any],
    provider: AIProvider,
) -> dict[str, Any]:
    """Ask an AI reviewer for a rigorous, problem-specific correctness proof."""
    if not isinstance(problem, dict) or not isinstance(algorithm, dict):
        return _invalid("Problem and algorithm must be structured objects.")

    statement = problem.get("problem_statement")
    code = algorithm.get("code")
    description = algorithm.get("algorithm")

    if not isinstance(statement, str) or not statement.strip():
        return _invalid("A selected problem statement is required.")
    if not isinstance(code, str) or not code.strip():
        return _invalid("Algorithm source code is required.")
    if not isinstance(description, str) or not description.strip():
        return _invalid("An algorithm description is required.")

    raw_input_schema = problem.get("input_schema")
    if not isinstance(raw_input_schema, dict):
        return _invalid("The approved input schema is required for mathematical verification.")
    try:
        from analyzers.structured_input_schema import StructuredIntegerInputSchema
        raw_input_schema = StructuredIntegerInputSchema.from_dict(raw_input_schema).to_dict()
    except (TypeError, ValueError) as exc:
        return _invalid(f"The approved input schema is invalid: {exc}")
    for field in ("input_format", "output_format"):
        if not isinstance(problem.get(field), str) or not problem[field].strip():
            return _invalid(f"The approved {field} is required for mathematical verification.")

    from analyzers.output_contract import output_contract
    try:
        approved_output_contract = output_contract(problem["output_format"])
    except (KeyError, ValueError) as exc:
        return _invalid(f"The approved output contract is invalid: {exc}")
    payload = {
        "problem_statement": statement,
        "approved_io_contract": {
            "input_format": problem.get("input_format"),
            "output_format": problem.get("output_format"),
            "output_contract": approved_output_contract,
            "input_schema": raw_input_schema,
            "constraints": problem.get("constraints", []),
            "authority": "The approved input_schema and output_contract define the task contract.",
        },
        "constraints": problem.get("constraints", []),
        "algorithm_description": description,
        "candidate_code": code,
        "supporting_evidence": algorithm.get("supporting_evidence", {}),
        "instructions": (
            "Independently compare the C implementation with the approved problem and approved_io_contract. Reason only over valid inputs described by the schema; check that output satisfies output_format. "
            "Return a precise theorem, pre/postconditions, necessary assumptions, "
            "and a concise proof using the right technique. Give 3-8 short steps; "
            "each step needs a claim, reason, and useful equation. Address boundary "
            "cases. Choose proof_sketch only if the argument covers every valid input. "
            "Choose counterexample_found only for an exact constraint-valid input that "
            "demonstrably fails; otherwise use inconclusive and name the gap. Never "
            "claim machine verification, execution, or assign a score. Do not repeat "
            "the problem, test evidence, or conclusions. Keep all fields compact."
        ),
    }

    try:
        response = provider.generate_json(
            task=TASK_MATHEMATICAL_PROOF,
            payload=payload,
            schema=VERIFICATION_SCHEMA,
        )
    except AIProviderError as exc:
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": str(exc),
        }

    if not isinstance(response, dict):
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier response must be a JSON object.",
        }

    outcome = response.get("outcome")
    text_fields = (
        "theorem", "proof_strategy", "conclusion",
    )
    list_fields = (
        "preconditions", "postconditions", "assumptions", "proof_steps",
        "limitations",
    )

    if outcome not in {"counterexample_found", "proof_sketch", "inconclusive"}:
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier returned an unsupported outcome.",
        }

    if any(
        not isinstance(response.get(key), str) or not response[key].strip()
        for key in text_fields
    ):
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier response is missing theorem, strategy, or conclusion.",
        }

    if any(not isinstance(response.get(key), list) for key in list_fields):
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier response contains invalid proof collections.",
        }

    if any(
        not isinstance(item, str)
        for key in ("preconditions", "postconditions", "assumptions", "limitations")
        for item in response[key]
    ):
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier proof conditions and limitations must be strings.",
        }

    steps = response["proof_steps"]
    if any(
        not isinstance(step, dict)
        or any(
            not isinstance(step.get(field), str)
            for field in ("claim", "justification", "equation")
        )
        or not step["claim"].strip()
        or not step["justification"].strip()
        for step in steps
    ):
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Verifier returned an invalid mathematical proof step.",
        }

    counterexample = response.get("counterexample")
    if outcome == "counterexample_found":
        required = (
            "input", "expected_behavior",
            "observed_or_predicted_behavior", "explanation",
        )
        if not isinstance(counterexample, dict) or any(
            not isinstance(counterexample.get(key), str)
            or not counterexample[key].strip()
            for key in required
        ):
            return {
                "status": "provider_error",
                "formally_verified": False,
                "message": "A counterexample requires concrete input and behavior.",
            }
    elif counterexample is not None:
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "Counterexample must be null when none is established.",
        }

    if outcome == "proof_sketch" and not steps:
        return {
            "status": "provider_error",
            "formally_verified": False,
            "message": "A proof result must contain at least one proof step.",
        }

    return {
        "status": outcome,
        "theorem": response["theorem"],
        "preconditions": response["preconditions"],
        "postconditions": response["postconditions"],
        "assumptions": response["assumptions"],
        "proof_strategy": response["proof_strategy"],
        "proof_steps": steps,
        "conclusion": response["conclusion"],
        "counterexample": counterexample,
        "limitations": response["limitations"],
        "formally_verified": False,
        "note": (
            "AI-generated mathematical analysis. It has not been "
            "mechanically checked or formally verified."
        ),
    }
