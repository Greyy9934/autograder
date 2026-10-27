"""Deterministic input/output test-case analyzer."""

from typing import Any

from app.runner import run_c_program


def normalize_output(value: str) -> str:
    """Normalize CRLF and trailing whitespace on each output line."""
    return "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).rstrip("\n")


def analyze_test_cases(
    source: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run explicit input/expected-output cases; never invent an oracle."""
    if not isinstance(test_cases, list) or not test_cases:
        return {
            "status": "invalid_request",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "results": [],
            "message": "Provide at least one explicit test case.",
        }

    results = []

    for index, case in enumerate(test_cases, start=1):
        if not isinstance(case, dict):
            return {
                "status": "invalid_request",
                "passed": 0,
                "failed": 0,
                "total": len(test_cases),
                "results": results,
                "message": f"Test case {index} must be an object.",
            }

        stdin = case.get("input", "")
        expected = case.get("expected_output")

        if not isinstance(stdin, str) or not isinstance(expected, str):
            return {
                "status": "invalid_request",
                "passed": 0,
                "failed": 0,
                "total": len(test_cases),
                "results": results,
                "message": (
                    f"Test case {index} requires string fields "
                    "'input' and 'expected_output'."
                ),
            }

        run = run_c_program(source, stdin)
        status = run.get("status", "unknown")
        actual = run.get("stdout", "")
        comparable = status == "completed"
        passed = (
            comparable
            and normalize_output(actual) == normalize_output(expected)
        )

        if passed:
            explanation = "Output matches the expected output."
        elif not comparable:
            explanation = f"Execution did not complete normally: {status}."
        else:
            explanation = "Actual output differs from expected output."

        results.append({
            "case": index,
            "passed": passed,
            "status": status,
            "input": stdin,
            "expected_output": expected,
            "actual_output": actual,
            "stderr": run.get("stderr", ""),
            "exit_code": run.get("exit_code"),
            "explanation": explanation,
        })

    passed_count = sum(item["passed"] for item in results)
    failed_count = len(results) - passed_count

    return {
        "status": "completed",
        "passed": passed_count,
        "failed": failed_count,
        "total": len(results),
        "results": results,
        "message": (
            "All supplied test cases passed."
            if failed_count == 0
            else f"{failed_count} supplied test case(s) failed."
        ),
    }
