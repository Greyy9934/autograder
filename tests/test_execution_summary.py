import unittest

from app.execution_summary import summarize_execution_evidence


class ExecutionSummaryTests(unittest.TestCase):
    def test_summarizes_random_and_adversarial_observations(self):
        result = summarize_execution_evidence({
            "random_test_execution": {
                "status": "completed_with_execution_issues",
                "executed": 3,
                "summary": {
                    "program_success": 1,
                    "time_limit_exceeded": 1,
                    "runtime_crash": 1,
                },
                "results": [{}, {}, {}],
            },
            "adversarial_execution": {
                "status": "completed",
                "executed": 2,
                "summary": {"program_success": 2},
                "results": [{}, {}],
            },
        })

        self.assertEqual(result["random_tests"]["executed"], 3)
        self.assertEqual(
            result["random_tests"]["outcome_counts"]["time_limit_exceeded"], 1
        )
        self.assertEqual(result["adversarial_tests"]["executed"], 2)
        self.assertEqual(
            result["adversarial_tests"]["outcome_counts"]["program_success"], 2
        )
        self.assertIsNone(result["correctness_score_contribution"])
        self.assertEqual(result["random_tests"]["verdict_authority"], "none")

    def test_missing_execution_evidence_is_safe(self):
        result = summarize_execution_evidence({})
        self.assertEqual(result["random_tests"]["executed"], 0)
        self.assertEqual(result["random_tests"]["status"], "not_run")
        self.assertIsNone(result["correctness_score_contribution"])

    def test_invalid_summary_counts_are_not_trusted(self):
        result = summarize_execution_evidence({
            "random_test_execution": {
                "summary": {
                    "program_success": -2,
                    "runtime_error": True,
                    "runtime_crash": "many",
                }
            }
        })
        counts = result["random_tests"]["outcome_counts"]
        self.assertEqual(counts["program_success"], 0)
        self.assertEqual(counts["runtime_error"], 0)
        self.assertEqual(counts["runtime_crash"], 0)


if __name__ == "__main__":
    unittest.main()
