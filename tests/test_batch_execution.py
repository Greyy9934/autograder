import unittest
from unittest.mock import patch

from analyzers.batch_execution import run_c_batch


class BatchExecutionTests(unittest.TestCase):
    @patch("analyzers.batch_execution.runner._run_bounded")
    def test_compiles_once_and_runs_each_input(self, mock_run):
        mock_run.side_effect = [
            {"status": "completed", "exit_code": 0, "seconds": 0.1},
            {"status": "completed", "exit_code": 0, "stdout": "3\n",
             "stderr": "", "seconds": 0.01},
            {"status": "completed", "exit_code": 0, "stdout": "7\n",
             "stderr": "", "seconds": 0.02},
        ]
        result = run_c_batch("int main(void){return 0;}", ["1 2\n", "3 4\n"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["compiled_once"])
        self.assertEqual(result["executed"], 2)
        self.assertEqual(mock_run.call_count, 3)

    @patch("analyzers.batch_execution.runner._run_bounded")
    def test_compile_failure_prevents_execution(self, mock_run):
        mock_run.return_value = {
            "status": "completed", "exit_code": 1, "stderr": "compile error",
        }
        result = run_c_batch("invalid C", ["1\n"])
        self.assertEqual(result["status"], "compile_failed")
        self.assertEqual(mock_run.call_count, 1)

    def test_rejects_empty_batch(self):
        self.assertEqual(
            run_c_batch("int main(void){return 0;}", [])["status"],
            "invalid_request",
        )

    def test_rejects_invalid_input_type(self):
        self.assertEqual(
            run_c_batch("int main(void){return 0;}", [None])["status"],
            "invalid_request",
        )


if __name__ == "__main__":
    unittest.main()
