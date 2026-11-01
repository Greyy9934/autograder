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

    def test_inconclusive_cases_are_excluded_from_correctness_denominator(self):
        result = derive_metric_scores({
            "test_evaluation": {
                "status": "completed",
                "total": 10,
                "passed": 1,
                "failed": 0,
                "inconclusive": 9,
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

    def test_complete_complexity_report_alone_does_not_earn_a_score(self):
        report = {
            "status": "completed",
            "time_complexity": "possibly O(n)",
            "space_complexity": "unknown",
            "loop_count": 1,
            "max_loop_depth_estimate": 1,
            "recursive_functions": [],
            "dynamic_allocation_count": 0,
            "findings": [],
            "limitations": ["Heuristic only"],
            "message": "Not a proof",
        }
        result = derive_metric_scores({"complexity_estimate": report})
        self.assertIsNone(result["complexity"])

    def test_malformed_complexity_report_has_no_score(self):
        report = {
            "status": "completed",
            "time_complexity": "possibly O(n)",
            "space_complexity": "unknown",
            "loop_count": "unknown",
            "max_loop_depth_estimate": 1,
            "recursive_functions": [],
            "dynamic_allocation_count": 0,
            "findings": [],
            "limitations": ["Heuristic only"],
            "message": "Not a proof",
        }
        result = derive_metric_scores({"complexity_estimate": report})
        self.assertIsNone(result["complexity"])


    def test_incomplete_complexity_report_has_no_score(self):
        result = derive_metric_scores({
            "complexity_estimate": {"status": "completed"}
        })
        self.assertIsNone(result["complexity"])

    def test_missing_complexity_report_has_no_score(self):
        result = derive_metric_scores({})
        self.assertIsNone(result["complexity"])


    def test_edge_case_ideas_alone_do_not_earn_a_score(self):
        result = derive_metric_scores({
            "edge_cases": {
                "status": "ready",
                "count": 8,
                "concrete_inputs_generated": False,
                "cases": [{"id": "minimum_size", "category": "applicable"}],
            }
        })
        self.assertIsNone(result["edge_cases"])


    def test_unsupported_metrics_remain_unavailable(self):
        result = derive_metric_scores({
            "complexity_estimate": {"status": "completed"},
            "memory_safety": {"status": "completed"},
        })
        for name in (
            "edge_cases",
            "mathematical_correctness",
            "complexity",
            "readability",
            "modularity",
            "design_originality",
        ):
            self.assertIsNone(result[name])


    def test_composite_metrics_follow_fixed_evidence_mappings(self):
        scores = derive_metric_scores({
            "test_evaluation": {"status": "completed", "total": 4, "passed": 2, "failed": 1, "inconclusive": 1},
            "agent3a_benchmark": {"differential_comparisons": [
                {"outcomes": {"student": {"execution_class": "program_success", "stdout": "ok\n"}, "brute_force": {"execution_class": "program_success", "stdout": "ok\n"}}},
                {"outcomes": {"student": {"execution_class": "time_limit_exceeded"}, "brute_force": {"execution_class": "program_success", "stdout": "ok\n"}}},
            ]},
            "agent3b_execution": {"differential_comparisons": [
                {"outcomes": {"student": {"execution_class": "program_success", "stdout": "same"}, "brute_force": {"execution_class": "program_success", "stdout": "same"}}},
                {"outcomes": {"student": {"execution_class": "program_success", "stdout": "wrong"}, "brute_force": {"execution_class": "program_success", "stdout": "right"}}},
            ]},
            "mathematical_verification": {"outcome": "proof_sketch"},
            "complexity_analysis": {"status": "analyzed", "ai_analysis": {"grading_assessment": {"rating": 2, "evidence": [{"line": 1}]}}},
            "code_quality": {"status": "completed", "rubric_ratings": {
                "readability": {"rating": 3, "evidence": [{"line": 1}]},
                "modularity": {"rating": 2, "evidence": [{"line": 2}]},
                "design_originality": {"rating": 4, "evidence": [{"line": 3}]},
            }},
        })
        self.assertEqual(scores["correctness"], 75.0)
        self.assertEqual(scores["edge_cases"], 50.0)
        self.assertEqual(scores["mathematical_correctness"], 75.0)
        self.assertEqual(scores["complexity"], 50.0)
        self.assertEqual(scores["readability"], 75.0)
        self.assertEqual(scores["modularity"], 50.0)
        self.assertEqual(scores["design_originality"], 100.0)


    def test_same_input_is_counted_once_across_explicit_and_random_evidence(self):
        result = derive_metric_scores({
            "test_evaluation": {
                "status": "completed", "total": 1, "passed": 1, "failed": 0, "inconclusive": 0,
                "results": [{"case": 1, "input": "1\n", "passed": True, "failed": False, "inconclusive": False}],
            },
            "agent3a": {"generation": {"inputs": [
                {"input": "1\n"}, {"input": "2\n"},
            ]}},
            "agent3a_benchmark": {"differential_comparisons": [
                {"case": 1, "outcomes": {"student": {"execution_class": "program_success", "stdout": "ok"}, "brute_force": {"execution_class": "program_success", "stdout": "ok"}}},
                {"case": 2, "outcomes": {"student": {"execution_class": "program_success", "stdout": "bad"}, "brute_force": {"execution_class": "program_success", "stdout": "ok"}}},
            ]},
        })
        self.assertEqual(result["correctness"], 50.0)


if __name__ == "__main__":
    unittest.main()
