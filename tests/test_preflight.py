import unittest
from analyzers.preflight import preflight


class PreflightTests(unittest.TestCase):
    def test_empty_source_rejected(self):
        result = preflight("")
        self.assertEqual(result["decision"], "reject")

    def test_non_string_source_rejected(self):
        result = preflight(None)
        self.assertEqual(result["decision"], "reject")

    def test_valid_source_continues_without_compilation(self):
        result = preflight("int main(void) { return 0; }")
        self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["status"], "source_validated")
        self.assertNotIn("stdout", result)

    def test_invalid_c_syntax_is_not_compiled(self):
        result = preflight("int main( {")
        self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["status"], "source_validated")

    def test_infinite_loop_is_not_executed(self):
        result = preflight("int main(void) { for (;;) {} }")
        self.assertEqual(result["decision"], "continue")

    def test_source_limit_enforced(self):
        result = preflight("x" * (256 * 1024 + 1))
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["status"], "source_too_large")


if __name__ == "__main__":
    unittest.main()
