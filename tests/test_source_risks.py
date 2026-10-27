import unittest

from analyzers.source_risks import analyze_source_risks


class SourceRiskTests(unittest.TestCase):
    def test_empty_source_rejected(self):
        self.assertEqual(
            analyze_source_risks("")["status"], "invalid_request"
        )

    def test_array_indexing_reported_with_line(self):
        result = analyze_source_risks(
            "int main(void) {\n    return a[i];\n}"
        )
        finding = next(
            item for item in result["findings"]
            if item["rule_id"] == "array_indexing"
        )
        self.assertEqual(finding["line"], 2)
        self.assertFalse(finding["confirmed_bug"])

    def test_loop_and_division_detected(self):
        result = analyze_source_risks(
            "while (x > 0) {\n    y = a / x;\n}"
        )
        rules = {item["rule_id"] for item in result["findings"]}
        self.assertIn("loop", rules)
        self.assertIn("integer_division", rules)

    def test_memory_operations_detected(self):
        result = analyze_source_risks(
            "p = malloc(n * sizeof(int));\nfree(p);"
        )
        rules = {item["rule_id"] for item in result["findings"]}
        self.assertIn("allocation", rules)
        self.assertIn("manual_memory_management", rules)

    def test_clean_source_returns_no_findings(self):
        result = analyze_source_risks(
            "int main(void) {\n    return 0;\n}"
        )
        self.assertEqual(result["count"], 0)

    def test_limitations_are_disclosed(self):
        result = analyze_source_risks("int main(void) { return 0; }")
        self.assertTrue(result["limitations"])


if __name__ == "__main__":
    unittest.main()
