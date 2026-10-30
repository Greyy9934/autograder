import unittest
from unittest.mock import patch

from analyzers.random_test_execution import execute_random_test_inputs


class RandomTestExecutionTests(unittest.TestCase):
    @patch("analyzers.random_test_execution.run_c_batch")
    def test_executes_inputs_without_claiming_correctness(self, mock_run):
        mock_run.return_value = {
            "status": "completed",
            "compile_seconds": 0.1,
            "compiled_once": True,
            "executed": 1,
            "results": [{
                "case": 1, "input": "2 3\n",
                "status": "completed", "stdout": "5\n",
                "stderr": "", "exit_code": 0,
                "stdout_truncated": False,
                "stderr_truncated": False, "run_seconds": 0.01,
            }],
        }
        result = execute_random_test_inputs("int main(void){return 0;}", ["2 3\n"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["executed"], 1)
        self.assertEqual(result["results"][0]["verdict"], "unclassified")

    def test_rejects_empty_input_list(self):
        self.assertEqual(
            execute_random_test_inputs("int main(void){return 0;}", [])["status"],
            "invalid_request",
        )

    def test_rejects_non_string_input(self):
        self.assertEqual(
            execute_random_test_inputs("int main(void){return 0;}", [None])["status"],
            "invalid_request",
        )

    def test_rejects_more_than_one_thousand_inputs(self):
        self.assertEqual(
            execute_random_test_inputs("int main(void){return 0;}", [""] * 1001)["status"],
            "invalid_request",
        )


if __name__ == "__main__":
    unittest.main()
