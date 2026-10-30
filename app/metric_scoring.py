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
        inconclusive = tests.get("inconclusive", 0)

        counts = (total, passed, failed, inconclusive)
        if (
            all(isinstance(value, int) and not isinstance(value, bool)
                for value in counts)
            and total > 0
            and passed >= 0
            and failed >= 0
            and inconclusive >= 0
            and passed + failed + inconclusive == total
            and passed + failed > 0
        ):
            scores["correctness"] = (
                100.0 * passed / (passed + failed)
            )

    # A completed memory diagnostic alone is not proof of memory safety.
    # Keep this metric unavailable until its findings have a validated schema.
    return scores
