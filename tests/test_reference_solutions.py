import unittest

from app.ai.base import AIProviderError
from app.ai.mock_provider import MockAIProvider
from analyzers.reference_solutions import generate_reference_solutions


def valid_response():
    solution = {
        "algorithm": "Enumerate candidate values.",
        "code": "#include <stdio.h>\nint main(void) { return 0; }\n",
        "time_complexity": "O(n)",
        "space_complexity": "O(1)",
    }
    return {
        "problem_summary": "Example problem.",
        "assumptions": ["Input is valid."],
        "brute_force": dict(solution),
        "efficient": dict(solution),
        "limitations": [],
    }


class ReferenceSolutionTests(unittest.TestCase):
    def test_generates_unverified_references(self):
        provider = MockAIProvider(valid_response())
        result = generate_reference_solutions(
            {"problem_statement": "Find a maximum."}, provider
        )
        self.assertEqual(result["status"], "generated_unverified")
        self.assertFalse(result["references_trusted"])
        self.assertFalse(result["validation"]["compiled"])
        self.assertFalse(result["validation"]["differentially_tested"])
        self.assertEqual(len(provider.calls), 1)

    def test_missing_problem_statement_rejected(self):
        provider = MockAIProvider(valid_response())
        result = generate_reference_solutions({}, provider)
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(provider.calls, [])

    def test_non_object_problem_rejected(self):
        result = generate_reference_solutions([], MockAIProvider(valid_response()))
        self.assertEqual(result["status"], "invalid_request")

    def test_malformed_response_rejected(self):
        result = generate_reference_solutions(
            {"problem_statement": "Find a maximum."},
            MockAIProvider({"problem_summary": "Incomplete"}),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertFalse(result["references_trusted"])

    def test_provider_error_is_reported(self):
        class FailingProvider:
            def generate_json(self, task, payload, schema):
                raise AIProviderError("Service unavailable")

        result = generate_reference_solutions(
            {"problem_statement": "Find a maximum."}, FailingProvider()
        )
        self.assertEqual(result["status"], "provider_error")


if __name__ == "__main__":
    unittest.main()
