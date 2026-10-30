"""Deterministic checks for generated reference programs."""

from typing import Any

from analyzers.batch_execution import run_c_batch


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

    valid_cases = []
    for index, case in enumerate(test_cases):
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("input", ""), str)
            or not isinstance(case.get("expected_output"), str)
        ):
            valid_cases.append(None)
        else:
            valid_cases.append(case)

    executable_cases = [case for case in valid_cases if case is not None]
    if not executable_cases:
        return {
            "status": "validation_failed",
            "passed": False,
            "trusted": False,
            "message": "No valid test cases were supplied.",
            "cases": [
                {
                    "case_index": index,
                    "status": "invalid_case",
                    "passed": False,
                }
                for index in range(len(test_cases))
            ],
        }

    batch = run_c_batch(
        source,
        [case.get("input", "") for case in executable_cases],
    )

    if batch["status"] not in {
        "completed", "completed_with_inconclusive_cases"
    }:
        return {
            "status": batch["status"],
            "passed": False,
            "trusted": False,
            "message": "Reference execution could not be completed reliably.",
            "cases": [],
        }

    results = []
    run_index = 0
    for index, case in enumerate(valid_cases):
        if case is None:
            results.append({
                "case_index": index,
                "status": "invalid_case",
                "passed": False,
            })
            continue

        actual = batch["results"][run_index]
        run_index += 1
        comparable = (
            actual.get("status") == "completed"
            and actual.get("exit_code") == 0
            and not actual.get("stdout_truncated", False)
            and not actual.get("stderr_truncated", False)
        )
        passed = comparable and (
            actual.get("stdout") == case["expected_output"]
        )
        results.append({
            "case_index": index,
            "status": actual.get("status", "unknown"),
            "execution_class": actual.get("execution_class"),
            "exit_code": actual.get("exit_code"),
            "passed": passed,
            "expected_output": case["expected_output"],
            "actual_output": actual.get("stdout", ""),
            "stderr": actual.get("stderr", ""),
            "seconds": actual.get("run_seconds"),
            "stdout_truncated": actual.get("stdout_truncated", False),
            "stderr_truncated": actual.get("stderr_truncated", False),
        })

    all_passed = bool(results) and all(
        item.get("passed", False) for item in results
    )
    return {
        "status": "passed_all_cases" if all_passed else "validation_failed",
        "passed": all_passed,
        "trusted": False,
        "compiled_once": batch.get("compiled_once", False),
        "compile_seconds": batch.get("compile_seconds"),
        "message": (
            "All supplied cases passed; correctness is not proven."
            if all_passed
            else "One or more supplied cases failed, were invalid, or were inconclusive."
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
