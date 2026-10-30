"""Deterministic, rule-driven grading with explicit evidence eligibility."""

import json
from pathlib import Path
from typing import Any

DEFAULT_GRADING_RULES = (
    Path(__file__).resolve().parent.parent / "rules" / "grading.json"
)


class GradingRulesError(ValueError):
    """Raised when grading rules are invalid."""


def load_grading_rules(path: str | Path = DEFAULT_GRADING_RULES) -> dict[str, Any]:
    """Load and validate external grading rules."""
    try:
        rules = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GradingRulesError(f"Could not load grading rules: {exc}") from exc

    if not isinstance(rules, dict):
        raise GradingRulesError("Grading rules must be a JSON object.")

    weights = rules.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise GradingRulesError("'weights' must be a non-empty object.")

    for name, weight in weights.items():
        if (
            not isinstance(name, str)
            or not name
            or isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight < 0
        ):
            raise GradingRulesError(f"Invalid weight for metric {name!r}.")

    if sum(weights.values()) <= 0:
        raise GradingRulesError("At least one metric weight must be positive.")

    scale = rules.get("score_scale", {})
    if not isinstance(scale, dict):
        raise GradingRulesError("'score_scale' must be an object.")

    minimum = scale.get("minimum", 0)
    maximum = scale.get("maximum", 100)
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, (int, float))
        or not isinstance(maximum, (int, float))
        or minimum >= maximum
    ):
        raise GradingRulesError("Invalid score scale.")

    policy = rules.get("policy", {})
    if not isinstance(policy, dict):
        raise GradingRulesError("'policy' must be an object.")

    if policy.get("unavailable_metrics", "exclude_and_renormalize") != (
        "exclude_and_renormalize"
    ):
        raise GradingRulesError("Unsupported unavailable-metric policy.")

    return rules


def _eligible_correctness(
    evidence: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, str]:
    preflight = evidence.get("preflight")
    if policy.get("require_successful_preflight", True):
        if not isinstance(preflight, dict) or preflight.get("decision") != "continue":
            return False, "Preflight did not pass."

    reconstruction = evidence.get("reconstruction")
    if policy.get("require_unambiguous_problem", True):
        if (
            not isinstance(reconstruction, dict)
            or reconstruction.get("status") != "ready"
            or len(reconstruction.get("candidates", [])) != 1
        ):
            return False, "The intended problem is not unambiguous."

    if policy.get("require_explicit_test_cases_for_correctness", True):
        tests = evidence.get("test_evaluation")
        if not isinstance(tests, dict) or tests.get("status") != "completed":
            return False, "Explicit test-case evaluation is unavailable."

        total = tests.get("total")
        passed = tests.get("passed")
        failed = tests.get("failed")
        inconclusive = tests.get("inconclusive", 0)
        counts = (total, passed, failed, inconclusive)
        if (
            any(isinstance(value, bool) or not isinstance(value, int)
                for value in counts)
            or total <= 0
            or passed < 0
            or failed < 0
            or inconclusive < 0
            or passed + failed + inconclusive != total
            or passed + failed == 0
        ):
            return False, "Test-case counts are invalid or contain no determinate cases."

    return True, "Required correctness evidence is available."


def grade_submission(
    evidence: dict[str, Any],
    metric_scores: dict[str, float | int | None],
    *,
    rules_path: str | Path = DEFAULT_GRADING_RULES,
) -> dict[str, Any]:
    """
    Compute a weighted score from externally supplied metric scores.

    Metric scores must be normalized to the configured score scale.
    Missing metrics are excluded and remaining weights are renormalized.
    This function does not invent metric scores from AI opinions.
    """
    if not isinstance(evidence, dict) or not isinstance(metric_scores, dict):
        raise ValueError("Evidence and metric scores must be objects.")

    rules = load_grading_rules(rules_path)
    weights = rules["weights"]
    policy = rules.get("policy", {})
    minimum = rules.get("score_scale", {}).get("minimum", 0)
    maximum = rules.get("score_scale", {}).get("maximum", 100)

    eligible, eligibility_reason = _eligible_correctness(evidence, policy)
    breakdown = {}
    excluded = {}

    for name, weight in weights.items():
        score = metric_scores.get(name)

        if name == "correctness" and not eligible:
            excluded[name] = eligibility_reason
            breakdown[name] = {
                "weight": weight,
                "score": None,
                "weighted_contribution": None,
                "status": "excluded",
                "reason": eligibility_reason,
            }
            continue

        if score is None:
            excluded[name] = "Metric score was not supplied."
            breakdown[name] = {
                "weight": weight,
                "score": None,
                "weighted_contribution": None,
                "status": "unavailable",
                "reason": excluded[name],
            }
            continue

        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or score < minimum
            or score > maximum
        ):
            raise ValueError(
                f"Metric {name!r} must be a number between {minimum} and {maximum}."
            )

        breakdown[name] = {
            "weight": weight,
            "score": score,
            "weighted_contribution": None,
            "status": "included",
            "reason": "Metric score supplied.",
        }

    included_weight = sum(
        item["weight"]
        for item in breakdown.values()
        if item["status"] == "included"
    )

    if included_weight == 0:
        return {
            "status": "not_gradeable",
            "score": None,
            "score_scale": {"minimum": minimum, "maximum": maximum},
            "included_weight": 0,
            "excluded_metrics": excluded,
            "breakdown": breakdown,
            "message": "No eligible metric scores are available.",
        }

    weighted_sum = 0.0
    for name, item in breakdown.items():
        if item["status"] != "included":
            continue
        contribution = item["score"] * item["weight"] / included_weight
        item["weighted_contribution"] = round(contribution, 4)
        weighted_sum += contribution

    return {
        "status": "graded" if eligible else "provisional",
        "score": round(weighted_sum, 2),
        "score_scale": {"minimum": minimum, "maximum": maximum},
        "included_weight": included_weight,
        "excluded_metrics": excluded,
        "breakdown": breakdown,
        "message": (
            "Score is based on eligible supplied metrics; excluded metrics "
            "were not treated as zero."
            if eligible
            else "Provisional score only: correctness grading requirements were not met."
        ),
    }
