"""Map deterministic analyzer evidence to conservative metric scores."""

from typing import Any


def derive_metric_scores(evidence: dict[str, Any]) -> dict[str, float | None]:
    """Derive scores only where current analyzer evidence supports them."""
    scores: dict[str, float | None] = {
        "correctness": None,
        "edge_cases": None,
        "code_quality": None,
        "complexity": None,
        "memory_safety": None,
        "readability": None,
        "originality_review": None,
    }

    tests = evidence.get("test_evaluation")
    if isinstance(tests, dict) and tests.get("status") == "completed":
        total = tests.get("total")
        passed = tests.get("passed")
        failed = tests.get("failed")

        if (
            isinstance(total, int)
            and not isinstance(total, bool)
            and total > 0
            and isinstance(passed, int)
            and not isinstance(passed, bool)
            and isinstance(failed, int)
            and not isinstance(failed, bool)
            and passed >= 0
            and failed >= 0
            and passed + failed == total
        ):
            scores["correctness"] = 100.0 * passed / total

    complexity = evidence.get("complexity_estimate")
    if isinstance(complexity, dict) and complexity.get("status") == "completed":
        required_fields = (
            "time_complexity",
            "space_complexity",
            "loop_count",
            "max_loop_depth_estimate",
            "recursive_functions",
            "dynamic_allocation_count",
            "findings",
            "limitations",
            "message",
        )
        valid_report = (
            all(field in complexity for field in required_fields)
            and isinstance(complexity["time_complexity"], str)
            and bool(complexity["time_complexity"].strip())
            and isinstance(complexity["space_complexity"], str)
            and bool(complexity["space_complexity"].strip())
            and isinstance(complexity["loop_count"], int)
            and not isinstance(complexity["loop_count"], bool)
            and complexity["loop_count"] >= 0
            and isinstance(complexity["max_loop_depth_estimate"], int)
            and not isinstance(complexity["max_loop_depth_estimate"], bool)
            and complexity["max_loop_depth_estimate"] >= 0
            and isinstance(complexity["recursive_functions"], list)
            and isinstance(complexity["dynamic_allocation_count"], int)
            and not isinstance(complexity["dynamic_allocation_count"], bool)
            and complexity["dynamic_allocation_count"] >= 0
            and isinstance(complexity["findings"], list)
            and isinstance(complexity["limitations"], list)
            and isinstance(complexity["message"], str)
            and bool(complexity["message"].strip())
        )
        if valid_report:
            scores["complexity"] = 100.0

    # A completed memory diagnostic alone is not proof of memory safety.
    # Keep this metric unavailable until its findings have a validated schema.
    return scores
