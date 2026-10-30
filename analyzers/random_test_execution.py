"""Execute generated random inputs using one compilation per batch."""

import hashlib
from typing import Any

from analyzers.batch_execution import run_c_batch


def execute_random_test_inputs(source: str, inputs: list[str]) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "results": []}

    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 1000:
        return {"status": "invalid_request", "results": []}

    if any(not isinstance(value, str) for value in inputs):
        return {"status": "invalid_request", "results": []}

    batch = run_c_batch(source, inputs)
    if batch["status"] not in {
        "completed",
        "completed_with_execution_issues",
    } or not isinstance(batch.get("results"), list):
        return {
            "status": batch["status"],
            "results": [],
            "execution_details": batch,
        }

    return {
        "status": batch["status"],
        "summary": batch.get("summary", {}),
        "compile_seconds": batch["compile_seconds"],
        "compiled_once": True,
        "executed": len(batch["results"]),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "results": [
            {
                "case": run["case"],
                "input": run["input"],
                "execution_status": run["status"],
                "stdout": run["stdout"],
                "stderr": run["stderr"],
                "exit_code": run["exit_code"],
                "verdict": "unclassified",
            }
            for run in batch["results"]
        ],
        "interpretation": (
            "No correctness verdict: generated inputs have no trusted expected outputs."
        ),
    }
