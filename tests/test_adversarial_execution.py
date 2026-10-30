import unittest
import hashlib
from unittest.mock import patch

from analyzers.adversarial_execution import execute_adversarial_candidates


class AdversarialExecutionTests(unittest.TestCase):
    def setUp(self):
        self.source = "int main(void) { return 0; }"
        self.plan = {
            "status": "planned",
            "source_sha256": hashlib.sha256(self.source.encode()).hexdigest(),
            "cases": [
                {
                    "input": "0 10\n",
                    "reason": "Boundary test",
                    "priority": "high",
                    "source_trigger": "array:line_4",
                }
            ],
        }

    @patch("analyzers.adversarial_execution.run_c_program")
    def test_executes_candidates_without_assigning_verdict(self, mock_run):
        mock_run.return_value = {
            "status": "completed",
            "stdout": "10\n",
            "stderr": "",
            "exit_code": 0,
        }
        result = execute_adversarial_candidates(self.source, self.plan)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["executed"], 1)
        self.assertEqual(result["results"][0]["verdict"], "unclassified")
        self.assertEqual(result["results"][0]["stdout"], "10\n")

    def test_rejects_source_mismatch(self):
        result = execute_adversarial_candidates(
            self.source + " ", self.plan
        )
        self.assertEqual(result["status"], "source_mismatch")

    def test_rejects_unplanned_input(self):
        result = execute_adversarial_candidates(
            self.source, {"status": "invalid", "cases": []}
        )
        self.assertEqual(result["status"], "invalid_plan")

    def test_rejects_malformed_case(self):
        plan = dict(self.plan)
        plan["cases"] = [{"input": None}]
        result = execute_adversarial_candidates(self.source, plan)
        self.assertEqual(result["status"], "invalid_plan")


if __name__ == "__main__":
    unittest.main()
