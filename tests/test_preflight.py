import unittest

from analyzers.preflight import preflight


class PreflightTests(unittest.TestCase):
    def test_empty_source_rejected(self):
        result = preflight("")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["stage"], "input_validation")

    def test_compile_error_rejected(self):
        result = preflight("int main( {")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["status"], "compile_error")

    def test_valid_program_continues(self):
        result = preflight(
            '#include <stdio.h>\nint main(void){puts("READY");}'
        )
        self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["stdout"], "READY\n")

    def test_infinite_loop_blocked(self):
        result = preflight("int main(void){for(;;){} return 0;}")
        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["status"], "timeout")

    def test_source_limit_enforced(self):
        result = preflight("x" * (256 * 1024 + 1))
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["stage"], "input_validation")


    def test_compiler_warning_is_reported_separately(self):
        from analyzers.preflight import extract_compiler_warnings

        diagnostics = (
            "file.c:3:5: warning: unused variable [-Wunused-variable]\n"
            "file.c:4:1: note: declared here\n"
            "linker: informational message\n"
        )
        warnings = extract_compiler_warnings(diagnostics)
        self.assertEqual(len(warnings), 1)
        self.assertIn("unused variable", warnings[0])


if __name__ == "__main__":
    unittest.main()
