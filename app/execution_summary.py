"""Summarize execution observations without assigning correctness scores."""
# Module role: Implements the execution summary subsystem used by the AutoGrader workflow.

from typing import Any

OUTCOME_KEYS = (
    "program_success",
    "runtime_error",
    "runtime_crash",
    "time_limit_exceeded",
    "output_limit_exceeded",
    "resource_limit_exceeded",
    "infrastructure_error",
    "execution_unknown",
)


# Function role: Normalizes one execution result into the compact status/count fields used in summaries.
# Same-file callers: summarize_execution_evidence.
def _summarize_one(result: Any) -> dict[str, Any]:
    # In-function documentation:
    # Parameters:
    #   - result: the result value used by this operation (type annotation: Any).
    # Returns: a value of declared type dict[str, Any].
    # Flow: branch on validation or workflow conditions; derive or store intermediate values; iterate through input or evidence items.
    if not isinstance(result, dict):
        result = {}

    raw = result.get("summary")
    counts = {}
    for key in OUTCOME_KEYS:
        value = raw.get(key, 0) if isinstance(raw, dict) else 0
        counts[key] = (
            value if isinstance(value, int)
            and not isinstance(value, bool) and value >= 0 else 0
        )

    results = result.get("results")
    executed = result.get("executed")
    if not isinstance(executed, int) or isinstance(executed, bool) or executed < 0:
        executed = len(results) if isinstance(results, list) else 0

    return {
        "status": result.get("status", "not_run"),
        "executed": executed,
        "outcome_counts": counts,
        "verdict_authority": "none",
    }


# Function role: Combine random/adversarial observations; never derive correctness.
# Direct call references (conditional/branch-dependent): _summarize_one.
def summarize_execution_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Combine random/adversarial observations; never derive correctness."""
    # In-function documentation:
    # Parameters:
    #   - evidence: validated execution or analysis facts used downstream (type annotation: dict[str, Any]).
    # Returns: a value of declared type dict[str, Any].
    # Flow: derive or store intermediate values; return the stage result.
    random_result = evidence.get("random_test_execution")
    adversarial_result = evidence.get("adversarial_execution")

    return {
        "random_tests": _summarize_one(random_result),
        "adversarial_tests": _summarize_one(adversarial_result),
        "correctness_score_contribution": None,
        "interpretation": (
            "Execution observations only. Random and adversarial cases without "
            "trusted expected outputs do not contribute to correctness scoring."
        ),
    }
