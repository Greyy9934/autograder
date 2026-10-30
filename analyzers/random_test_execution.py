"""Execute generated random inputs and collect observations, not correctness verdicts."""

import hashlib
from typing import Any

from app.runner import run_c_program


def execute_random_test_inputs(source: str, inputs: list[str]) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "results": []}

    if not isinstance(inputs, list) or not inputs or len(inputs) > 1000:
        return {"status": "invalid_request", "results": []}

    if any(not isinstance(value, str) for value in inputs):
        return {"status": "invalid_request", "results": []}

    results = []
    for index, value in enumerate(inputs, start=1):
        run = run_c_program(source, value)
        results.append({
            "case": index,
            "input": value,
            "execution_status": run.get("status", "unknown"),
            "stdout": run.get("stdout", ""),
            "stderr": run.get("stderr", ""),
            "exit_code": run.get("exit_code"),
            "verdict": "unclassified",
        })

    return {
        "status": "completed",
        "executed": len(results),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "results": results,
        "interpretation": "No correctness verdict: generated inputs have no trusted expected outputs.",
    }
