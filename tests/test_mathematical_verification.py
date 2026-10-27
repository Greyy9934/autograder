import unittest

from app.ai.base import AIProviderError
from app.ai.mock_provider import MockAIProvider
from analyzers.mathematical_verification import verify_algorithm


PROBLEM = {
    "problem_statement": "Given integers, return their maximum.",
    "constraints": ["At least one integer."],
}

ALGORITHM = {
    "algorithm": "Initialize the answer with the first value, then scan the rest.",
    "code": "int main(void) { return 0; }",
}


def response(outcome="proof_sketch", counterexample=None):
    return {
        "outcome": outcome,
        "reasoning": "Inspect the initialization and every later comparison.",
        "assumptions": ["The input is non-empty."],
        "counterexample": counterexample,
        "limitations": ["No execution or formal proof was performed."],
    }


class MathematicalVerificationTests(unittest.TestCase):
    def test_proof_sketch_is_not_formal_verification(self):
        result = verify_algorithm(
            PROBLEM, ALGORITHM, MockAIProvider(response())
        )
        self.assertEqual(result["status"], "proof_sketch")
        self.assertFalse(result["formally_verified"])

    def test_counterexample_requires_concrete_details(self):
        result = verify_algorithm(
            PROBLEM,
            ALGORITHM,
            MockAIProvider(response("counterexample_found", {
                "input": "-5 -2",
                "expected_behavior": "-2",
                "observed_or_predicted_behavior": "-5",
                "explanation": "The algorithm keeps the first value incorrectly.",
            })),
        )
        self.assertEqual(result["status"], "counterexample_found")
        self.assertFalse(result["formally_verified"])

    def test_incomplete_counterexample_is_rejected(self):
        result = verify_algorithm(
            PROBLEM,
            ALGORITHM,
            MockAIProvider(response("counterexample_found", {"input": "1"})),
        )
        self.assertEqual(result["status"], "provider_error")

    def test_missing_problem_rejected_without_provider_call(self):
        provider = MockAIProvider(response())
        result = verify_algorithm({}, ALGORITHM, provider)
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(provider.calls, [])

    def test_provider_failure_is_reported(self):
        class BrokenProvider:
            def generate_json(self, task, payload, schema):
                raise AIProviderError("Temporary failure")

        result = verify_algorithm(PROBLEM, ALGORITHM, BrokenProvider())
        self.assertEqual(result["status"], "provider_error")
        self.assertFalse(result["formally_verified"])


if __name__ == "__main__":
    unittest.main()
