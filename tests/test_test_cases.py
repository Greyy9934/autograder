import unittest

from analyzers.test_cases import analyze_test_cases, normalize_output


class TestCaseAnalyzerTests(unittest.TestCase):
    def test_matching_output_passes(self):
        result = analyze_test_cases(
            '#include <stdio.h>\nint main(void){int n;if(scanf("%d",&n)!=1)return 1;printf("%d\\n",n*2);}',
            [{"input": "4\n", "expected_output": "8\n"}],
        )
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["results"][0]["passed"])

    def test_wrong_output_has_evidence(self):
        result = analyze_test_cases(
            '#include <stdio.h>\nint main(void){puts("wrong");}',
            [{"input": "", "expected_output": "right\n"}],
        )
        case = result["results"][0]
        self.assertFalse(case["passed"])
        self.assertEqual(case["actual_output"], "wrong\n")
        self.assertIn("differs", case["explanation"])

    def test_matching_output_with_nonzero_exit_code_fails(self):
        from unittest.mock import patch

        with patch(
            "analyzers.test_cases.run_c_program",
            return_value={
                "status": "completed",
                "stdout": "expected\\n",
                "stderr": "runtime error",
                "exit_code": 1,
            },
        ):
            result = analyze_test_cases(
                "int main(void){return 1;}",
                [{"input": "", "expected_output": "expected\\n"}],
            )

        case = result["results"][0]
        self.assertFalse(case["passed"])
        self.assertIn("exit code", case["explanation"].lower())

    def test_runtime_timeout_fails_case(self):
        result = analyze_test_cases(
            "int main(void){for(;;){} return 0;}",
            [{"input": "", "expected_output": ""}],
        )
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][0]["status"], "timeout")

    def test_empty_test_list_rejected(self):
        result = analyze_test_cases("int main(void){return 0;}", [])
        self.assertEqual(result["status"], "invalid_request")

    def test_output_normalization(self):
        self.assertEqual(normalize_output("hello  \r\nworld\n"), "hello\nworld")


if __name__ == "__main__":
    unittest.main()
