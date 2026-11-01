import json
import tempfile
import unittest
from pathlib import Path

from app.grading import (
    GradingRulesError,
    grade_submission,
    load_grading_rules,
)


def valid_evidence():
    return {
        "preflight": {"decision": "continue"},
        "reconstruction": {
            "status": "ready",
            "candidates": [{"id": "A"}],
        },
        "test_evaluation": {
            "status": "completed",
            "total": 2,
            "passed": 2,
            "failed": 0,
        },
        "reference_solutions": {"refs_trusted": True},
    }


class GradingTests(unittest.TestCase):
    def test_rules_load(self):
        rules = load_grading_rules()
        self.assertEqual(sum(rules["weights"].values()), 100)

    def test_weighted_score_is_deterministic(self):
        scores = {
            "correctness": 100,
            "edge_cases": 80,
            "mathematical_correctness": 70,
            "complexity": 60,
            "readability": 80,
            "modularity": 90,
            "design_originality": 100,
        }
        result = grade_submission(valid_evidence(), scores)
        self.assertEqual(result["status"], "graded")
        self.assertEqual(result["score"], 87.0)

    def test_same_source_spec_and_test_evidence_has_stable_reproducibility_id(self):
        evidence = valid_evidence()
        evidence.update({
            "source_sha256": "a" * 64,
            "assignment_spec_fingerprint": "b" * 64,
        })
        evidence["test_evaluation"]["results"] = [{
            "case": 1, "input": "1", "expected_output": "1\\n",
            "actual_output": "1\\n", "passed": True, "failed": False,
            "inconclusive": False, "execution_class": "program_success",
        }]
        scores = {"correctness": 100.0}
        first = grade_submission(evidence, scores)
        second = grade_submission(evidence, scores)
        self.assertEqual(first["score"], second["score"])
        self.assertEqual(
            first["reproducibility"]["fingerprint"],
            second["reproducibility"]["fingerprint"],
        )

    def test_missing_metrics_are_excluded_and_renormalized(self):
        result = grade_submission(
            valid_evidence(),
            {"correctness": 80, "edge_cases": None},
        )
        self.assertEqual(result["score"], 80.0)
        self.assertEqual(result["included_weight"], 45)
        self.assertEqual(result["breakdown"]["edge_cases"]["status"], "unavailable")

    def test_ambiguous_problem_prevents_correctness_grade(self):
        evidence = valid_evidence()
        evidence["reconstruction"]["candidates"].append({"id": "B"})
        result = grade_submission(
            evidence,
            {"correctness": 100, "readability": 80},
        )
        self.assertEqual(result["status"], "provisional")
        self.assertIsNone(result["breakdown"]["correctness"]["score"])
        self.assertNotIn("correctness", [
            name for name, item in result["breakdown"].items()
            if item["status"] == "included"
        ])

    def test_untrusted_references_do_not_block_explicit_test_grading(self):
        evidence = valid_evidence()
        evidence["reference_solutions"]["refs_trusted"] = False
        result = grade_submission(evidence, {"correctness": 100})
        self.assertEqual(result["status"], "graded")
        self.assertEqual(result["score"], 100.0)

    def test_failed_preflight_prevents_correctness_grade(self):
        evidence = valid_evidence()
        evidence["preflight"]["decision"] = "block"
        result = grade_submission(evidence, {"correctness": 100})
        self.assertEqual(result["status"], "not_gradeable")

    def test_invalid_metric_score_rejected(self):
        with self.assertRaises(ValueError):
            grade_submission(valid_evidence(), {"readability": 101})

    def test_invalid_rules_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grading.json"
            path.write_text(
                json.dumps({"weights": {"correctness": -1}}),
                encoding="utf-8",
            )
            with self.assertRaises(GradingRulesError):
                load_grading_rules(path)


    def test_non_finite_metric_scores_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    grade_submission(valid_evidence(), {"code_quality": value})

    def test_non_finite_rule_weights_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "grading.json"
                    path.write_text(
                        json.dumps({"weights": {"correctness": value}}),
                        encoding="utf-8",
                    )
                    with self.assertRaises(GradingRulesError):
                        load_grading_rules(path)

    def test_non_finite_score_scale_is_rejected(self):
        for scale in (
            {"minimum": float("nan"), "maximum": 100},
            {"minimum": 0, "maximum": float("inf")},
        ):
            with self.subTest(scale=scale):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "grading.json"
                    path.write_text(
                        json.dumps({
                            "weights": {"correctness": 100},
                            "score_scale": scale,
                        }),
                        encoding="utf-8",
                    )
                    with self.assertRaises(GradingRulesError):
                        load_grading_rules(path)


    def test_reproducibility_fingerprint_covers_differential_outcomes_but_not_timing(self):
        evidence = valid_evidence()
        evidence.update({"source_sha256": "c" * 64, "assignment_spec_fingerprint": "d" * 64})
        evidence["agent3a_benchmark"] = {"differential_comparisons": [{
            "case": 1, "input_size": 10,
            "outcomes": {
                "student": {"execution_class": "program_success", "stdout": "YES", "run_seconds": 0.001},
                "brute_force": {"execution_class": "program_success", "stdout": "YES", "run_seconds": 0.002},
                "efficient": {"execution_class": "program_success", "stdout": "YES", "run_seconds": 0.001},
            },
        }]}
        first = grade_submission(evidence, {"correctness": 100})
        evidence["agent3a_benchmark"]["differential_comparisons"][0]["outcomes"]["student"]["run_seconds"] = 0.8
        timing_only = grade_submission(evidence, {"correctness": 100})
        self.assertEqual(first["reproducibility"]["fingerprint"], timing_only["reproducibility"]["fingerprint"])
        evidence["agent3a_benchmark"]["differential_comparisons"][0]["outcomes"]["brute_force"]["stdout"] = "NO"
        changed_result = grade_submission(evidence, {"correctness": 100})
        self.assertNotEqual(first["reproducibility"]["fingerprint"], changed_result["reproducibility"]["fingerprint"])


if __name__ == "__main__":
    unittest.main()
