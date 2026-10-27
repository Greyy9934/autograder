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
            "code_quality": 70,
            "complexity": 60,
            "memory_safety": 90,
            "readability": 80,
            "originality_review": 100,
        }
        result = grade_submission(valid_evidence(), scores)
        self.assertEqual(result["status"], "graded")
        self.assertEqual(result["score"], 89.0)

    def test_missing_metrics_are_excluded_and_renormalized(self):
        result = grade_submission(
            valid_evidence(),
            {"correctness": 80, "edge_cases": None},
        )
        self.assertEqual(result["score"], 80.0)
        self.assertEqual(result["included_weight"], 50)
        self.assertEqual(result["breakdown"]["edge_cases"]["status"], "unavailable")

    def test_ambiguous_problem_prevents_correctness_grade(self):
        evidence = valid_evidence()
        evidence["reconstruction"]["candidates"].append({"id": "B"})
        result = grade_submission(
            evidence,
            {"correctness": 100, "code_quality": 80},
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
            grade_submission(valid_evidence(), {"code_quality": 101})

    def test_invalid_rules_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grading.json"
            path.write_text(
                json.dumps({"weights": {"correctness": -1}}),
                encoding="utf-8",
            )
            with self.assertRaises(GradingRulesError):
                load_grading_rules(path)


if __name__ == "__main__":
    unittest.main()
