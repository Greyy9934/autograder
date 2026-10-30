"""Deterministic input/output test-case analyzer."""

from typing import Any

from analyzers.batch_execution import run_c_batch


def normalize_output(value: str) -> str:
    """Normalize CRLF and trailing whitespace on each output line."""
    return "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).rstrip("\n")


def analyze_test_cases(
    source: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run explicit input/output cases using one compilation per batch."""
    if not isinstance(test_cases, list) or not test_cases:
        return {
            "status": "invalid_request",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "results": [],
            "message": "Provide at least one explicit test case.",
        }

    for index, case in enumerate(test_cases, start=1):
        if not isinstance(case, dict):
            return {
                "status": "invalid_request",
                "passed": 0,
                "failed": 0,
                "total": len(test_cases),
                "results": [],
                "message": f"Test case {index} must be an object.",
            }
        if (
            not isinstance(case.get("input", ""), str)
            or not isinstance(case.get("expected_output"), str)
        ):
            return {
                "status": "invalid_request",
                "passed": 0,
                "failed": 0,
                "total": len(test_cases),
                "results": [],
                "message": (
                    f"Test case {index} requires string fields "
                    "'input' and 'expected_output'."
                ),
            }

    batch = run_c_batch(source, [case.get("input", "") for case in test_cases])

    if batch["status"] not in {
        "completed", "completed_with_inconclusive_cases"
    }:
        return {
            "status": batch["status"],
            "passed": 0,
            "failed": 0,
            "total": len(test_cases),
            "results": [],
            "execution_status": batch["status"],
            "message": "The test batch could not be completed reliably.",
        }

    results = []
    for index, (case, run) in enumerate(
        zip(test_cases, batch["results"]), start=1
    ):
        status = run.get("status", "unknown")
        actual = run.get("stdout", "")
        expected = case["expected_output"]
        exit_code = run.get("exit_code")
        comparable = (
            status == "completed"
            and exit_code == 0
            and not run.get("stdout_truncated", False)
            and not run.get("stderr_truncated", False)
        )
        passed = comparable and (
            normalize_output(actual) == normalize_output(expected)
        )

        if passed:
            explanation = "Output matches the expected output and exit code is zero."
        elif status == "completed" and exit_code != 0:
            explanation = f"Program exited with nonzero exit code: {exit_code}."
        elif not comparable:
            explanation = (
                f"Execution is inconclusive: {run.get('execution_class', status)}."
            )
        else:
            explanation = "Actual output differs from expected output."

        results.append({
            "case": index,
            "passed": passed,
            "status": status,
            "execution_class": run.get("execution_class"),
            "input": case.get("input", ""),
            "expected_output": expected,
            "actual_output": actual,
            "stderr": run.get("stderr", ""),
            "exit_code": exit_code,
            "stdout_truncated": run.get("stdout_truncated", False),
            "stderr_truncated": run.get("stderr_truncated", False),
            "explanation": explanation,
        })

    passed_count = sum(item["passed"] for item in results)
    failed_count = len(results) - passed_count

    return {
        "status": batch["status"],
        "passed": passed_count,
        "failed": failed_count,
        "total": len(results),
        "compile_seconds": batch.get("compile_seconds"),
        "compiled_once": batch.get("compiled_once", False),
        "results": results,
        "message": (
            "All supplied test cases passed."
            if failed_count == 0
            else f"{failed_count} supplied test case(s) failed or were inconclusive."
        ),
    }
