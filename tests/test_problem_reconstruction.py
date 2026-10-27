import unittest

from analyzers.problem_reconstruction import reconstruct_problem


class ProblemReconstructionTests(unittest.TestCase):
    def test_source_only_can_continue(self):
        result = reconstruct_problem("int main(void){return 0;}")
        self.assertTrue(result["can_continue"])
        self.assertEqual(result["problem_statement_source"], "missing")
        self.assertEqual(result["valid_test_case_count"], 0)
        self.assertIsNone(result["inferred_problem"])

    def test_statement_is_optional_context(self):
        result = reconstruct_problem(
            "int main(void){return 0;}",
            problem_statement="Print the sum of two integers.",
        )
        self.assertEqual(result["problem_statement_source"], "provided")
        self.assertIn("user_supplied_problem_statement", result["available_evidence"])

    def test_test_cases_are_optional(self):
        result = reconstruct_problem("int main(void){return 0;}", test_cases=None)
        self.assertTrue(result["can_continue"])
        self.assertEqual(result["valid_test_case_count"], 0)

    def test_valid_test_cases_are_counted(self):
        result = reconstruct_problem(
            "int main(void){return 0;}",
            test_cases=[{"input": "1 2\n", "expected_output": "3\n"}],
        )
        self.assertEqual(result["valid_test_case_count"], 1)
        self.assertIn("user_supplied_test_cases", result["available_evidence"])

    def test_invalid_source_stops_intake(self):
        result = reconstruct_problem("")
        self.assertFalse(result["can_continue"])
        self.assertEqual(result["status"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
