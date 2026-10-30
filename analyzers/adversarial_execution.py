"""Execute adversarial candidates and collect evidence without grading them."""

import hashlib
from typing import Any

from app.runner import run_c_program


def execute_adversarial_candidates(
    source: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "results": []}

    if not isinstance(plan, dict) or plan.get("status") != "planned":
        return {"status": "invalid_plan", "results": []}

    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if plan.get("source_sha256") != source_hash:
        return {"status": "source_mismatch", "results": []}

    cases = plan.get("cases")
    if not isinstance(cases, list) or not cases:
        return {"status": "invalid_plan", "results": []}

    results = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or not isinstance(case.get("input"), str):
            return {
                "status": "invalid_plan",
                "results": results,
                "message": f"Invalid adversarial case at position {index}.",
            }

        run = run_c_program(source, case["input"])
        results.append({
            "case": index,
            "input": case["input"],
            "reason": case.get("reason"),
            "priority": case.get("priority"),
            "source_trigger": case.get("source_trigger"),
            "execution_status": run.get("status", "unknown"),
            "stdout": run.get("stdout", ""),
            "stderr": run.get("stderr", ""),
            "exit_code": run.get("exit_code"),
            "timed_out": run.get("timed_out", False),
            "verdict": "unclassified",
        })

    return {
        "status": "completed",
        "executed": len(results),
        "results": results,
        "interpretation": (
            "Execution observations only. No correctness verdict is assigned "
            "because these cases do not contain trusted expected outputs."
        ),
    }
