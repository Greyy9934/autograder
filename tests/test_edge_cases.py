import unittest

from analyzers.edge_cases import analyze_edge_cases


class EdgeCaseAnalyzerTests(unittest.TestCase):
    def test_missing_problem_rejected(self):
        self.assertEqual(
            analyze_edge_cases({})["status"], "invalid_request"
        )

    def test_non_object_rejected(self):
        self.assertEqual(
            analyze_edge_cases(None)["status"], "invalid_request"
        )

    def test_returns_candidate_ideas(self):
        result = analyze_edge_cases({
            "problem_statement": "Find the maximum integer in an array.",
            "constraints": ["1 <= n <= 100000", "Values are integers"],
        })
        self.assertEqual(result["count"], 8)
        self.assertFalse(result["concrete_inputs_generated"])
        self.assertIn("minimum_size", [c["id"] for c in result["cases"]])

    def test_empty_case_is_conditional(self):
        result = analyze_edge_cases({
            "problem_statement": "Find the maximum value.",
            "constraints": ["n >= 1"],
        })
        empty_case = next(
            c for c in result["cases"] if c["id"] == "empty_input"
        )
        self.assertEqual(empty_case["category"], "conditional")

    def test_missing_constraints_are_not_invented(self):
        result = analyze_edge_cases({
            "problem_statement": "Process a collection.",
        })
        self.assertEqual(result["status"], "needs_clarification")
        self.assertTrue(any(
            c["category"] == "needs_clarification"
            for c in result["cases"]
        ))

    def test_limitations_are_explicit(self):
        result = analyze_edge_cases({
            "problem_statement": "Find the maximum.",
            "constraints": [],
        })
        self.assertTrue(result["limitations"])


if __name__ == "__main__":
    unittest.main()
