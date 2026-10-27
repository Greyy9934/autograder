"""Deterministic checks for generated reference programs."""

from typing import Any

from app.runner import run_c_program


def validate_reference_program(
    source: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run a candidate reference against cases; never infer a proof."""
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "passed": False,
            "trusted": False,
            "message": "Reference source must be non-empty text.",
            "cases": [],
        }

    if not isinstance(test_cases, list) or not test_cases:
        return {
            "status": "insufficient_tests",
            "passed": False,
            "trusted": False,
            "message": "At least one validation case is required.",
            "cases": [],
        }

    results = []
    for index, case in enumerate(test_cases):
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("input", ""), str)
            or not isinstance(case.get("expected_output"), str)
        ):
            results.append({
                "case_index": index,
                "status": "invalid_case",
                "passed": False,
            })
            continue

        actual = run_c_program(source, case.get("input", ""))
        passed = (
            actual.get("status") == "completed"
            and actual.get("exit_code") == 0
            and actual.get("stdout") == case["expected_output"]
            and not actual.get("stdout_truncated", False)
            and not actual.get("stderr_truncated", False)
        )
        results.append({
            "case_index": index,
            "status": actual.get("status", "unknown"),
            "exit_code": actual.get("exit_code"),
            "passed": passed,
            "expected_output": case["expected_output"],
            "actual_output": actual.get("stdout", ""),
            "stderr": actual.get("stderr", ""),
            "seconds": actual.get("seconds"),
        })

    all_passed = bool(results) and all(
        item.get("passed", False) for item in results
    )
    return {
        "status": "passed_all_cases" if all_passed else "validation_failed",
        "passed": all_passed,
        "trusted": False,
        "message": (
            "All supplied cases passed; correctness is not proven."
            if all_passed
            else "One or more validation cases failed or were invalid."
        ),
        "cases": results,
    }


def validate_reference_pair(
    brute_force_source: str,
    efficient_source: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare two candidate references on the same supplied cases."""
    brute = validate_reference_program(brute_force_source, test_cases)
    efficient = validate_reference_program(efficient_source, test_cases)

    comparisons = []
    if isinstance(test_cases, list):
        for index, case in enumerate(test_cases):
            if not isinstance(case, dict) or not isinstance(
                case.get("input", ""), str
            ):
                continue

            if (
                index < len(brute["cases"])
                and index < len(efficient["cases"])
            ):
                left = brute["cases"][index]
                right = efficient["cases"][index]
                if left.get("passed") and right.get("passed"):
                    comparisons.append({
                        "case_index": index,
                        "outputs_agree": (
                            left["actual_output"] == right["actual_output"]
                        ),
                    })

    agree = bool(comparisons) and all(
        item["outputs_agree"] for item in comparisons
    )
    return {
        "status": (
            "references_agree_on_tested_cases"
            if agree else "reference_agreement_inconclusive_or_failed"
        ),
        "brute_force": brute,
        "efficient": efficient,
        "comparisons": comparisons,
        "references_trusted": False,
        "note": (
            "Agreement on supplied cases does not establish that either "
            "reference implements the intended problem correctly."
        ),
    }
