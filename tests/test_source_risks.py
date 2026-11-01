import unittest

from analyzers.source_risks import analyze_source_risks


class SourceRiskTests(unittest.TestCase):
    def test_empty_source_rejected(self):
        self.assertEqual(
            analyze_source_risks("")["status"], "invalid_request"
        )

    def test_ordinary_array_indexing_is_reported_as_structure_not_risk(self):
        result = analyze_source_risks(
            "int main(void) {\n    return a[i];\n}"
        )
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["metrics"]["indexed_access_count"], 1)

    def test_loop_and_arithmetic_are_summarized_not_flagged_as_defects(self):
        result = analyze_source_risks(
            "while (x > 0) {\n    y = a / x;\n}"
        )
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["metrics"]["loop_count"], 1)

    def test_allocation_and_free_are_summarized_not_flagged_as_defects(self):
        result = analyze_source_risks(
            "p = malloc(n * sizeof(int));\nfree(p);"
        )
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["metrics"]["dynamic_allocation_count"], 1)

    def test_clean_source_returns_no_findings(self):
        result = analyze_source_risks(
            "int main(void) {\n    return 0;\n}"
        )
        self.assertEqual(result["count"], 0)

    def test_numeric_scanf_is_not_flagged_as_unbounded_input(self):
        source = 'int n; if (scanf("%d", &n) != 1) return 1;'
        result = analyze_source_risks(source)
        rules = {item["rule_id"] for item in result["findings"]}
        self.assertNotIn("unbounded_input", rules)

    def test_unbounded_string_input_is_flagged(self):
        source = 'char name[8]; scanf("%s", name);'
        result = analyze_source_risks(source)
        rules = {item["rule_id"] for item in result["findings"]}
        self.assertIn("unbounded_string_input", rules)

    def test_limitations_are_disclosed(self):
        result = analyze_source_risks("int main(void) { return 0; }")
        self.assertTrue(result["limitations"])

    def test_obvious_off_by_one_loop_is_flagged(self):
        result = analyze_source_risks(
            "int main(void) {\n"
            "  for (int i = 0; i <= n; ++i) {\n"
            "    values[i] = i;\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["findings"][0]["rule_id"], "possible_off_by_one")


if __name__ == "__main__":
    unittest.main()
