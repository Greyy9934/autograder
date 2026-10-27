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

    memory = evidence.get("memory_safety")
    if isinstance(memory, dict) and memory.get("status") == "completed":
        # Do not infer a safety score until diagnostic findings have a validated
        # and consistent schema. Availability alone is not evidence of safety.
        scores["memory_safety"] = None

    return scores
