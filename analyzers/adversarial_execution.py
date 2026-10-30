"""Execute adversarial candidates using one compilation per batch."""

import hashlib
from typing import Any

from analyzers.batch_execution import run_c_batch


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

    if any(not isinstance(case, dict) or not isinstance(case.get("input"), str)
           for case in cases):
        return {"status": "invalid_plan", "results": []}

    batch = run_c_batch(source, [case["input"] for case in cases])
    if batch["status"] != "completed":
        return {"status": batch["status"], "results": [],
                "execution_details": batch}

    results = []
    for case, run in zip(cases, batch["results"]):
        results.append({
            "case": run["case"],
            "input": case["input"],
            "reason": case.get("reason"),
            "priority": case.get("priority"),
            "source_trigger": case.get("source_trigger"),
            "execution_status": run["status"],
            "stdout": run["stdout"],
            "stderr": run["stderr"],
            "exit_code": run["exit_code"],
            "timed_out": run["status"] == "timeout",
            "verdict": "unclassified",
        })

    return {
        "status": "completed",
        "compile_seconds": batch["compile_seconds"],
        "compiled_once": True,
        "executed": len(results),
        "results": results,
        "interpretation": (
            "Execution observations only. No correctness verdict is assigned "
            "because these cases do not contain trusted expected outputs."
        ),
    }
