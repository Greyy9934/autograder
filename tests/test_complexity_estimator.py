import unittest

from analyzers.complexity_estimator import estimate_complexity


class ComplexityEstimatorTests(unittest.TestCase):
    def test_empty_source_is_rejected(self):
        result = estimate_complexity("  ")
        self.assertEqual(result["status"], "invalid_request")

    def test_simple_loop_is_detected(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  for (int i = 0; i < 10; i++) {}\n"
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(result["loop_count"], 1)
        self.assertIn("possibly O(n)", result["time_complexity"])

    def test_nested_loops_are_flagged_as_heuristic(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  for (int i = 0; i < 10; i++) {\n"
            "    for (int j = 0; j < 10; j++) {}\n"
            "  }\n"
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(result["loop_count"], 2)
        self.assertIn("nested loops detected", result["time_complexity"])
        self.assertTrue(result["limitations"])

    def test_recursion_is_detected_as_candidate(self):
        result = estimate_complexity(
            "int f(int n) {\n"
            "  if (n <= 1) return 1;\n"
            "  return f(n - 1);\n"
            "}\n"
        )
        self.assertIn("f", result["recursive_functions"])
        self.assertIn("recurrence not inferred", result["time_complexity"])

    def test_dynamic_allocation_is_detected(self):
        result = estimate_complexity(
            "#include <stdlib.h>\n"
            "int main(void) {\n"
            "  int *p = malloc(10 * sizeof(int));\n"
            "  free(p);\n"
            "}\n"
        )
        self.assertEqual(result["dynamic_allocation_count"], 1)
        self.assertIn("dynamic allocation detected", result["space_complexity"])

    def test_no_pattern_does_not_claim_proven_constant_complexity(self):
        result = estimate_complexity("int main(void) { return 0; }")
        self.assertIn("candidate", result["time_complexity"])
        self.assertIn("not measured runtime", result["message"])


if __name__ == "__main__":
    unittest.main()
