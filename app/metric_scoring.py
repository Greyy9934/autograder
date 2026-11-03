"""Derive normalized grading metrics only from validated evidence."""
# Module role: Maps determinate execution and validated AI rubric evidence to normalized score dimensions.

from typing import Any


# Function role: Implements the internal valid counts helper for metric scoring.
# Same-file callers: _determinate_trials.
def _valid_counts(report: Any) -> tuple[int, int] | None:
    if not isinstance(report, dict) or report.get("status") != "completed":
        return None
    passed, failed, inconclusive = report.get("passed"), report.get("failed"), report.get("inconclusive", 0)
    values = (passed, failed, inconclusive)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        return None
    if report.get("total") != passed + failed + inconclusive:
        return None
    return passed, failed


# Function role: Extracts student-versus-reference trials while excluding timeouts and infrastructure uncertainty.
# Same-file callers: _determinate_trials, _comparison_rate, derive_metric_scores.
def _comparison_trials(report: Any, suite_name: str, input_cases: list[Any] | None = None) -> list[tuple[str, bool]]:
    if not isinstance(report, dict) or not isinstance(report.get("differential_comparisons"), list):
        return []
    trials = []
    inconclusive = {"infrastructure_error", "execution_unknown", "not_executed_before_deadline", "time_limit_exceeded", "timeout"}
    for index, comparison in enumerate(report["differential_comparisons"], 1):
        if not isinstance(comparison, dict):
            continue
        outcomes = comparison.get("outcomes")
        if not isinstance(outcomes, dict):
            continue
        student, brute = outcomes.get("student"), outcomes.get("brute_force")
        if not isinstance(student, dict) or not isinstance(brute, dict) or brute.get("execution_class") != "program_success":
            continue
        student_class = student.get("execution_class")
        if student_class in inconclusive:
            continue
        if student_class == "program_success":
            result = str(student.get("stdout", "")).strip() == str(brute.get("stdout", "")).strip()
        else:
            result = False
        case_id = comparison.get("case", index)
        input_text = comparison.get("input")
        if not input_text and isinstance(input_cases, list) and isinstance(case_id, int) and 1 <= case_id <= len(input_cases):
            item = input_cases[case_id - 1]
            input_text = item.get("input") if isinstance(item, dict) else None
        key = (str(input_text).replace("\r\n", "\n") if isinstance(input_text, str) else f"{suite_name}:{case_id}")
        trials.append((key, result))
    return trials


# Function role: Collects and deduplicates only evidence with a determinate pass/fail outcome.
# Same-file callers: derive_metric_scores.
# Direct call references (conditional/branch-dependent): _valid_counts, _comparison_trials.
def _determinate_trials(evidence: dict[str, Any]) -> list[tuple[str, bool]]:
    trials: list[tuple[str, bool]] = []
    tests = evidence.get("test_evaluation")
    if isinstance(tests, dict) and tests.get("status") == "completed":
        results = tests.get("results")
        found = False
        if isinstance(results, list):
            for index, item in enumerate(results, 1):
                if not isinstance(item, dict) or item.get("inconclusive") is True:
                    continue
                if item.get("passed") is True or item.get("failed") is True:
                    found = True
                    text = item.get("input")
                    key = str(text).replace("\r\n", "\n") if isinstance(text, str) else f"explicit:{item.get('case', index)}"
                    trials.append((key, item.get("passed") is True))
        if not found:
            counts = _valid_counts(tests)
            if counts:
                trials.extend((f"explicit-count-pass:{i}", True) for i in range(counts[0]))
                trials.extend((f"explicit-count-fail:{i}", False) for i in range(counts[1]))
    generated = evidence.get("agent3a")
    generated_inputs = ((generated.get("generation") or {}).get("inputs", []) if isinstance(generated, dict) else [])
    trials.extend(_comparison_trials(evidence.get("agent3a_benchmark"), "random", generated_inputs))
    # Deduplicate identical input strings. Conflicting outcomes on the same input
    # are excluded as nondeterministic evidence rather than arbitrarily choosing one.
    by_input: dict[str, set[bool]] = {}
    for key, outcome in trials:
        by_input.setdefault(key, set()).add(outcome)
    return [(key, next(iter(values))) for key, values in by_input.items() if len(values) == 1]


# Function role: Computes a percentage from a non-empty collection of determinate trials.
# Same-file callers: derive_metric_scores.
def _score_trials(trials: list[tuple[str, bool]]) -> float | None:
    if not trials:
        return None
    passed = sum(result for _, result in trials)
    return round(100.0 * passed / len(trials), 2)


# Function role: Implements the internal comparison rate helper for metric scoring.
# Direct call references (conditional/branch-dependent): _comparison_trials.
def _comparison_rate(report: Any) -> tuple[int, int] | None:
    trials = _comparison_trials(report, "edge")
    if not trials:
        return None
    passed = sum(value for _, value in trials)
    return passed, len(trials) - passed


# Function role: Accepts only an anchored integer rating with non-empty evidence and maps it onto the 0-100 scale.
# Same-file callers: derive_metric_scores.
def _rating_score(item: Any) -> float | None:
    if not isinstance(item, dict):
        return None
    rating = item.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 4:
        return None
    evidence = item.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return None
    return float(rating * 25)


# Function role: Apply the published mappings; AI never supplies a numeric score directly.
# Numbered workflow order: 07.1 - convert evidence to normalized rubric dimensions; AI never returns the final score.
# Direct call references (conditional/branch-dependent): _score_trials, _determinate_trials, _comparison_trials, _rating_score.
def derive_metric_scores(evidence: dict[str, Any]) -> dict[str, float | None]:
    """Apply the published mappings; AI never supplies a numeric score directly."""
    scores: dict[str, float | None] = {
        "correctness": None, "edge_cases": None, "mathematical_correctness": None,
        "complexity": None, "readability": None, "modularity": None,
        "design_originality": None,
    }
    scores["correctness"] = _score_trials(_determinate_trials(evidence))
    scores["edge_cases"] = _score_trials(
        [(key, value) for key, value in _comparison_trials(evidence.get("agent3b_execution"), "edge")]
    )

    proof = evidence.get("mathematical_verification")
    if isinstance(proof, dict):
        outcome = proof.get("outcome", proof.get("status"))
        if outcome == "counterexample_found":
            scores["mathematical_correctness"] = 0.0
        elif outcome == "proof_sketch":
            scores["mathematical_correctness"] = 75.0
        elif outcome in {"verified", "formally_verified"} and proof.get("formally_verified") is True:
            scores["mathematical_correctness"] = 100.0

    complexity = evidence.get("complexity_analysis")
    if isinstance(complexity, dict) and complexity.get("status") == "analyzed":
        analysis = complexity.get("ai_analysis", complexity)
        scores["complexity"] = _rating_score(analysis.get("grading_assessment")) if isinstance(analysis, dict) else None

    quality = evidence.get("code_quality")
    if isinstance(quality, dict) and quality.get("status") == "completed":
        rubric = quality.get("rubric_ratings")
        if isinstance(rubric, dict):
            scores["readability"] = _rating_score(rubric.get("readability"))
            scores["modularity"] = _rating_score(rubric.get("modularity"))
            scores["design_originality"] = _rating_score(rubric.get("design_originality"))
    return scores
