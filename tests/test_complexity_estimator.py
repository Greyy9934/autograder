import unittest

from analyzers.complexity_estimator import estimate_complexity


class ComplexityEstimatorTests(unittest.TestCase):
    def test_empty_source_is_rejected(self):
        result = estimate_complexity("  ")
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["proof_status"], "not_proven")

    def test_non_string_source_is_rejected(self):
        self.assertEqual(estimate_complexity(None)["status"], "invalid_request")

    def test_simple_loop_is_detected(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  for (int i = 0; i < 10; i++) {}\n"
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(result["loop_count"], 1)
        self.assertIn("O(1) candidate", result["time_complexity"])

    def test_nested_constant_loops_are_classified_as_constant_work(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  for (int i = 0; i < 10; i++) {\n"
            "    for (int j = 0; j < 10; j++) {}\n"
            "  }\n"
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(result["loop_count"], 2)
        self.assertIn("O(1) candidate", result["time_complexity"])
        self.assertEqual(result["max_loop_depth_estimate"], 2)

    def test_loops_in_comments_and_strings_are_ignored(self):
        result = estimate_complexity(
            'int main(void) {\n'
            '  // for (int i = 0; i < n; i++) {}\n'
            '  char *s = "while (x) { for (;;) }";\n'
            '  /* while (y) { } */\n'
            '  return 0;\n'
            '}\n'
        )
        self.assertEqual(result["loop_count"], 0)
        self.assertEqual(result["findings"], [])

    def test_recursion_is_detected_as_candidate(self):
        result = estimate_complexity(
            "int f(int n) {\n"
            "  if (n <= 1) return 1;\n"
            "  return f(n - 1);\n"
            "}\n"
        )
        self.assertIn("f", result["recursive_functions"])
        self.assertIn("O(n) candidate", result["time_complexity"])

    def test_recursive_search_inside_input_loop_suggests_factorial_growth(self):
        source = """
        void search(int n, int depth) {
            if (depth == n) return;
            for (int next = 1; next < n; ++next) {
                if (next > 0) search(n, depth + 1);
            }
        }
        """
        result = estimate_complexity(source)
        self.assertIn("O(n!) candidate", result["time_complexity"])
        self.assertTrue(result["recursive_analysis"][0]["recursive_call_inside_loop"])

    def test_input_halving_loop_is_classified_logarithmic(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  for (int i = 1; i < n; i *= 2) {}\n"
            "}\n"
        )
        self.assertEqual(result["loop_analysis"][0]["model"], "logarithmic")
        self.assertIn("O(log n) candidate", result["time_complexity"])

    def test_recursion_in_string_is_ignored(self):
        result = estimate_complexity(
            'int f(void) {\n'
            '  char *s = "f("; \n'
            '  return 0;\n'
            '}\n'
        )
        self.assertEqual(result["recursive_functions"], [])

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

    def test_allocation_in_comment_is_ignored(self):
        result = estimate_complexity(
            "int main(void) {\n"
            "  // malloc(n * sizeof(int));\n"
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(result["dynamic_allocation_count"], 0)

    def test_result_explicitly_marks_heuristic_and_unproven(self):
        result = estimate_complexity("int main(void) { return 0; }")
        self.assertEqual(result["analysis_type"], "static_heuristic")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["proof_status"], "not_proven")
        self.assertEqual(result["input_size_model"], "not_inferred")
        self.assertIn("not measured runtime", result["message"])


if __name__ == "__main__":
    unittest.main()
