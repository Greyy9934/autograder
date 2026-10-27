"""Compare candidate programs on identical inputs."""

import random
from typing import Any

from app.runner import run_c_program


def compare_programs(
    first_source: str,
    second_source: str,
    inputs: list[str],
) -> dict[str, Any]:
    """Compare two programs; disagreements are evidence, not a verdict."""
    if (
        not isinstance(first_source, str)
        or not first_source.strip()
        or not isinstance(second_source, str)
        or not second_source.strip()
    ):
        return {
            "status": "invalid_request",
            "comparisons": [],
            "agreement_count": 0,
            "disagreement_count": 0,
            "failure_count": 0,
            "references_trusted": False,
        }

    if not isinstance(inputs, list) or not inputs:
        return {
            "status": "invalid_request",
            "comparisons": [],
            "agreement_count": 0,
            "disagreement_count": 0,
            "failure_count": 0,
            "references_trusted": False,
        }

    comparisons = []
    for index, stdin in enumerate(inputs):
        if not isinstance(stdin, str):
            return {
                "status": "invalid_request",
                "comparisons": comparisons,
                "agreement_count": 0,
                "disagreement_count": 0,
                "failure_count": 0,
                "references_trusted": False,
                "message": f"Input {index} must be a string.",
            }

        first = run_c_program(first_source, stdin)
        second = run_c_program(second_source, stdin)

        first_ok = (
            first.get("status") == "completed"
            and first.get("exit_code") == 0
            and not first.get("stdout_truncated", False)
            and not first.get("stderr_truncated", False)
        )
        second_ok = (
            second.get("status") == "completed"
            and second.get("exit_code") == 0
            and not second.get("stdout_truncated", False)
            and not second.get("stderr_truncated", False)
        )

        if not first_ok or not second_ok:
            outcome = "execution_failure"
        elif first.get("stdout") != second.get("stdout"):
            outcome = "disagreement"
        else:
            outcome = "agreement"

        comparisons.append({
            "case_index": index,
            "input": stdin,
            "outcome": outcome,
            "first": {
                "status": first.get("status"),
                "exit_code": first.get("exit_code"),
                "stdout": first.get("stdout", ""),
                "stderr": first.get("stderr", ""),
            },
            "second": {
                "status": second.get("status"),
                "exit_code": second.get("exit_code"),
                "stdout": second.get("stdout", ""),
                "stderr": second.get("stderr", ""),
            },
        })

    agreements = sum(x["outcome"] == "agreement" for x in comparisons)
    disagreements = sum(x["outcome"] == "disagreement" for x in comparisons)
    failures = sum(x["outcome"] == "execution_failure" for x in comparisons)

    if disagreements:
        status = "counterexample_found"
    elif failures:
        status = "execution_failure"
    else:
        status = "agreement_on_tested_inputs"

    return {
        "status": status,
        "comparisons": comparisons,
        "agreement_count": agreements,
        "disagreement_count": disagreements,
        "failure_count": failures,
        "references_trusted": False,
        "message": (
            "Agreement on tested inputs does not prove correctness."
        ),
    }


def generate_integer_list_inputs(
    *,
    seed: int,
    count: int,
    min_length: int = 1,
    max_length: int = 20,
    min_value: int = -100,
    max_value: int = 100,
) -> dict[str, Any]:
    """Generate reproducible inputs formatted as n followed by n integers."""
    integer_arguments = (
        seed, count, min_length, max_length, min_value, max_value
    )
    if (
        any(isinstance(value, bool) or not isinstance(value, int)
            for value in integer_arguments)
        or count < 1 or count > 1000
        or min_length < 1 or max_length < min_length or max_length > 10000
        or min_value > max_value
    ):
        return {
            "status": "invalid_request",
            "seed": seed,
            "inputs": [],
        }

    rng = random.Random(seed)
    inputs = []
    for _ in range(count):
        length = rng.randint(min_length, max_length)
        values = [rng.randint(min_value, max_value) for _ in range(length)]
        inputs.append(f"{length}\n{' '.join(map(str, values))}\n")

    return {
        "status": "generated",
        "seed": seed,
        "count": len(inputs),
        "inputs": inputs,
        "format": "n followed by n space-separated integers",
    }


def generate_integer_list_edge_cases(
    *,
    min_length: int = 1,
    max_length: int = 20,
    min_value: int = -100,
    max_value: int = 100,
) -> dict[str, Any]:
    """Generate deterministic boundary cases for n followed by n integers."""
    arguments = (min_length, max_length, min_value, max_value)
    if (
        any(isinstance(value, bool) or not isinstance(value, int)
            for value in arguments)
        or min_length < 1
        or max_length < min_length
        or max_length > 10000
        or min_value > max_value
    ):
        return {"status": "invalid_request", "inputs": []}

    candidates = [
        [min_value] * min_length,
        [max_value] * min_length,
        [0] * min_length if min_value <= 0 <= max_value else None,
        [min_value] * max_length,
        [max_value] * max_length,
        [min_value, max_value] if min_length <= 2 <= max_length else None,
        list(range(min_value, min_value + min_length))
        if min_value + min_length - 1 <= max_value else None,
        list(range(min_value, min_value + max_length))
        if min_value + max_length - 1 <= max_value else None,
        list(range(max_value, max_value - max_length, -1))
        if max_value - max_length + 1 >= min_value else None,
    ]

    inputs = []
    seen = set()
    for values in candidates:
        if values is None:
            continue
        encoded = f"{len(values)}\n{' '.join(map(str, values))}\n"
        if encoded not in seen:
            seen.add(encoded)
            inputs.append(encoded)

    return {
        "status": "generated",
        "count": len(inputs),
        "inputs": inputs,
        "format": "n followed by n space-separated integers",
        "message": (
            "These are structural boundary candidates, not guaranteed "
            "edge cases for every problem."
        ),
    }
