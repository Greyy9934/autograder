import unittest
from unittest.mock import patch

from analyzers.reference_validation import (
    validate_reference_pair,
    validate_reference_program,
)


class ReferenceValidationTests(unittest.TestCase):
    def test_successful_case_does_not_claim_trust(self):
        with patch(
            "analyzers.reference_validation.run_c_batch",
            return_value={
                "status": "completed",
                "compiled_once": True,
                "results": [{
    "status": "completed",
    "exit_code": 0,
    "stdout": "42\n",
    "stderr": "",
    "stdout_truncated": False,
    "stderr_truncated": False,
    "run_seconds": 0.01,
                }],
            },
        ):
            result = validate_reference_program(
                "int main(void) { return 0; }",
                [{"input": "21\n", "expected_output": "42\n"}],
            )
        self.assertTrue(result["passed"])
        self.assertFalse(result["trusted"])

    def test_nonzero_exit_fails(self):
        with patch(
            "analyzers.reference_validation.run_c_batch",
            return_value={
                "status": "completed",
                "compiled_once": True,
                "results": [{
    "status": "completed",
    "exit_code": 7,
    "stdout": "42\n",
    "stderr": "",
    "stdout_truncated": False,
    "stderr_truncated": False,
                }],
            },
        ):
            result = validate_reference_program(
                "int main(void) { return 7; }",
                [{"input": "", "expected_output": "42\n"}],
            )
        self.assertFalse(result["passed"])

    def test_wrong_output_fails(self):
        with patch(
            "analyzers.reference_validation.run_c_batch",
            return_value={
                "status": "completed",
                "compiled_once": True,
                "results": [{
    "status": "completed",
    "exit_code": 0,
    "stdout": "41\n",
    "stderr": "",
    "stdout_truncated": False,
    "stderr_truncated": False,
                }],
            },
        ):
            result = validate_reference_program(
                "int main(void) { return 0; }",
                [{"input": "", "expected_output": "42\n"}],
            )
        self.assertEqual(result["status"], "validation_failed")

    def test_empty_cases_are_insufficient(self):
        result = validate_reference_program("int main(void){return 0;}", [])
        self.assertEqual(result["status"], "insufficient_tests")

    def test_invalid_case_fails_validation(self):
        result = validate_reference_program(
            "int main(void){return 0;}", [{"input": 42}]
        )
        self.assertFalse(result["passed"])

    def test_pair_never_claims_trust(self):
        with patch(
            "analyzers.reference_validation.run_c_batch",
            return_value={
                "status": "completed",
                "compiled_once": True,
                "results": [{
    "status": "completed",
    "exit_code": 0,
    "stdout": "ok\n",
    "stderr": "",
    "stdout_truncated": False,
    "stderr_truncated": False,
                }],
            },
        ):
            result = validate_reference_pair(
                "int main(void){return 0;}",
                "int main(void){return 0;}",
                [{"input": "", "expected_output": "ok\n"}],
            )
        self.assertTrue(result["comparisons"][0]["outputs_agree"])
        self.assertFalse(result["references_trusted"])


if __name__ == "__main__":
    unittest.main()
