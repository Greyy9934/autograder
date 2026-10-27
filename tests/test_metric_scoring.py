import unittest

from app.metric_scoring import derive_metric_scores


class MetricScoringTests(unittest.TestCase):
    def test_correctness_uses_explicit_test_pass_rate(self):
        result = derive_metric_scores({
            "test_evaluation": {
                "status": "completed",
                "total": 4,
                "passed": 3,
                "failed": 1,
            }
        })
        self.assertEqual(result["correctness"], 75.0)

    def test_all_tests_pass_gives_full_test_score(self):
        result = derive_metric_scores({
            "test_evaluation": {
                "status": "completed",
                "total": 2,
                "passed": 2,
                "failed": 0,
            }
        })
        self.assertEqual(result["correctness"], 100.0)

    def test_invalid_test_counts_produce_no_score(self):
        result = derive_metric_scores({
            "test_evaluation": {
                "status": "completed",
                "total": 2,
                "passed": 3,
                "failed": -1,
            }
        })
        self.assertIsNone(result["correctness"])

    def test_incomplete_test_evaluation_produces_no_score(self):
        result = derive_metric_scores({
            "test_evaluation": {"status": "invalid_request"}
        })
        self.assertIsNone(result["correctness"])

    def test_unsupported_metrics_remain_unavailable(self):
        result = derive_metric_scores({
            "complexity_estimate": {"status": "completed"},
            "memory_safety": {"status": "completed"},
        })
        for name in (
            "edge_cases",
            "code_quality",
            "complexity",
            "memory_safety",
            "readability",
            "originality_review",
        ):
            self.assertIsNone(result[name])


if __name__ == "__main__":
    unittest.main()
