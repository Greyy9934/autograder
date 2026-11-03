"""Deterministic, rule-driven grading with explicit evidence eligibility."""
# It applies the score rules stored in grading.json; correctness has the greatest weight and missing evidence is not made up.

import json
import hashlib
import math
from pathlib import Path
from typing import Any

DEFAULT_GRADING_RULES = (
    Path(__file__).resolve().parent.parent / "rules" / "grading.json"
)


class GradingRulesError(ValueError):
    """Raised when grading rules are invalid."""


# The numbers live in rules/grading.json so the score formula is visible and easy to review.
# Correctness matters most; missing evidence is left out and the other weights are fairly scaled up.
def load_grading_rules(path: str | Path = DEFAULT_GRADING_RULES) -> dict[str, Any]:
    """Load and validate external grading rules."""
    # Reads the weights and grading choices from grading.json and rejects invalid settings.
    # What the inputs mean:
    # - path: the file location being read or written.
    # What it gives back: It returns a set of named results for the next step.
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
            or not math.isfinite(weight)
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
        or not math.isfinite(minimum)
        or not math.isfinite(maximum)
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
    # Checks that the problem and test results are clear enough to include correctness in the grade.
    # What the inputs mean:
    # - evidence: the test and review results used to make a decision.
    # - policy: the policy used for this step.
    # What it gives back: It returns a small group of related values.
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


def _reproducibility_metadata(
    evidence: dict[str, Any],
    metric_scores: dict[str, Any],
    rules_path: str | Path,
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Fingerprint the stable inputs that determine a grade, excluding timings."""
    # Records which code, assignment, rules, and test results were used to calculate this grade.
    # What the inputs mean:
    # - evidence: the test and review results used to make a decision.
    # - metric_scores: the score values calculated from available evidence.
    # - rules_path: the location of the grading rules file.
    # - rules: the grading settings loaded from the rules file.
    # What it gives back: It returns a set of named results for the next step.
    try:
        rules_digest = hashlib.sha256(Path(rules_path).read_bytes()).hexdigest()
    except OSError:
        rules_digest = hashlib.sha256(
            json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    tests = evidence.get("test_evaluation")
    test_cases = []
    if isinstance(tests, dict):
        for item in tests.get("results", []):
            if not isinstance(item, dict):
                continue
            test_cases.append({
                key: item.get(key)
                for key in (
                    "case", "input", "expected_output", "actual_output",
                    "passed", "failed", "inconclusive", "execution_class",
                )
            })
    differential_suites = {}
    for suite_name in ("agent3a_benchmark", "agent3b_execution"):
        suite = evidence.get(suite_name)
        comparisons = suite.get("differential_comparisons", []) if isinstance(suite, dict) else []
        if suite_name == "agent3a_benchmark":
            generated = evidence.get("agent3a")
            suite_inputs = ((generated.get("generation") or {}).get("inputs", []) if isinstance(generated, dict) else [])
        else:
            generated = evidence.get("agent3b")
            suite_inputs = generated.get("cases", []) if isinstance(generated, dict) else []
        differential_suites[suite_name] = [
            {
                "case": item.get("case"),
                "input": (
                    item.get("input")
                    or ((suite_inputs[item.get("case") - 1] or {}).get("input")
                        if isinstance(suite_inputs, list)
                        and isinstance(item.get("case"), int)
                        and 1 <= item.get("case") <= len(suite_inputs)
                        and isinstance(suite_inputs[item.get("case") - 1], dict)
                        else None)
                ),
                "input_size": item.get("input_size"),
                "outcomes": {
                    program: {
                        key: (outcome or {}).get(key)
                        for key in ("execution_class", "exit_code", "stdout")
                    }
                    for program, outcome in (item.get("outcomes") or {}).items()
                    if program in {"student", "brute_force", "efficient"}
                },
            }
            for item in comparisons if isinstance(item, dict)
        ] if isinstance(comparisons, list) else []
    suite_payload = {
        "status": tests.get("status") if isinstance(tests, dict) else None,
        "cases": test_cases,
        "differential_suites": differential_suites,
    }
    suite_digest = hashlib.sha256(json.dumps(
        suite_payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    stable_inputs = {
        "grading_version": str(rules.get("version", "unversioned")),
        "rules_version": str(rules.get("version", "unversioned")),
        "rules_sha256": rules_digest,
        "source_sha256": evidence.get("source_sha256"),
        "assignment_spec_fingerprint": evidence.get("assignment_spec_fingerprint"),
        "test_suite_fingerprint": suite_digest,
        "metric_scores": metric_scores,
    }
    fingerprint = hashlib.sha256(json.dumps(
        stable_inputs, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {"fingerprint": fingerprint, **stable_inputs}


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
    # Applies the published score weights to available evidence and explains what was included or left out.
    # What the inputs mean:
    # - evidence: the test and review results used to make a decision.
    # - metric_scores: the score values calculated from available evidence.
    # - rules_path: the location of the grading rules file.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(evidence, dict) or not isinstance(metric_scores, dict):
        raise ValueError("Evidence and metric scores must be objects.")

    rules = load_grading_rules(rules_path)
    weights = rules["weights"]
    unknown_metrics = set(metric_scores) - set(weights)
    if unknown_metrics:
        raise ValueError(f"Unknown metric score(s): {', '.join(sorted(unknown_metrics))}.")
    policy = rules.get("policy", {})
    minimum = rules.get("score_scale", {}).get("minimum", 0)
    maximum = rules.get("score_scale", {}).get("maximum", 100)
    reproducibility = _reproducibility_metadata(
        evidence, metric_scores, rules_path, rules
    )

    eligible, eligibility_reason = _eligible_correctness(evidence, policy)

    tests = evidence.get("test_evaluation")
    test_coverage_complete = True
    if policy.get("require_explicit_test_cases_for_correctness", True):
        test_coverage_complete = (
            isinstance(tests, dict)
            and tests.get("inconclusive", 0) == 0
        )

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
            or not math.isfinite(score)
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
            "grade_band": None,
            "score_scale": {"minimum": minimum, "maximum": maximum},
            "included_weight": 0,
            "excluded_metrics": excluded,
            "breakdown": breakdown,
            "reproducibility": reproducibility,
            "message": "No eligible metric scores are available.",
        }

    weighted_sum = 0.0
    for name, item in breakdown.items():
        if item["status"] != "included":
            continue
        contribution = item["score"] * item["weight"] / included_weight
        item["weighted_contribution"] = round(contribution, 4)
        weighted_sum += contribution

    final_score = round(weighted_sum, 2)
    grade_band = (
        "A" if final_score >= 90 else "B" if final_score >= 80
        else "C" if final_score >= 70 else "D" if final_score >= 60 else "F"
    )
    return {
        "status": (
            "graded" if eligible and test_coverage_complete else "provisional"
        ),
        "score": final_score,
        "grade_band": grade_band,
        "score_scale": {"minimum": minimum, "maximum": maximum},
        "included_weight": included_weight,
        "excluded_metrics": excluded,
        "breakdown": breakdown,
        "reproducibility": reproducibility,
        "message": (
            "Score is based on eligible supplied metrics; excluded metrics "
            "were not treated as zero."
            if eligible and test_coverage_complete
            else (
                "Provisional score: one or more supplied test cases were "
                "inconclusive. Correctness uses determinate cases only."
                if eligible
                else "Provisional score only: correctness grading requirements were not met."
            )
        ),
    }
