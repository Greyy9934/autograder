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
            {"problem_statement": "Find a maximum.", "input_format": "One integer.", "output_format": "Print one integer.", "input_schema": {
                "version": 1,
                "fields": [{"name": "x", "type": "int", "min": -10, "max": 10}],
                "size_field": "x",
            }}, provider
        )
        self.assertEqual(result["status"], "generated_unverified")
        self.assertFalse(result["references_trusted"])
        self.assertFalse(result["validation"]["compiled"])
        self.assertFalse(result["validation"]["differentially_tested"])
        self.assertEqual(len(provider.calls), 1)

    def test_complete_confirmed_io_contract_is_sent_to_reference_agent(self):
        provider = MockAIProvider(valid_response())
        assignment = {
            "problem_statement": "Return the maximum subarray sum.",
            "title": "Maximum subarray",
            "constraints": ["1 <= n <= 100000"],
            "input_format": "n followed by n integers",
            "output_format": "One integer: the maximum subarray sum",
            "input_schema": {
                "version": 1,
                "fields": [
                    {"name": "n", "type": "int", "min": 1, "max": 100000},
                    {"name": "values", "type": "int_array", "length_from": "n", "min": -1000, "max": 1000},
                ],
                "size_field": "values",
            },
            "user_supplied_problem_statement": "Given an array, find its maximum subarray sum.",
        }
        result = generate_reference_solutions(assignment, provider)
        self.assertEqual(result["status"], "generated_unverified")
        payload = provider.calls[0]["payload"]
        self.assertEqual(payload["input_schema"], assignment["input_schema"])
        self.assertEqual(payload["assignment_specification"]["input_format"], assignment["input_format"])
        self.assertEqual(payload["assignment_specification"]["output_format"], assignment["output_format"])
        self.assertEqual(payload["output_contract"]["format"], assignment["output_format"])
        self.assertEqual(payload["assignment_specification"]["output_contract"], payload["output_contract"])
        self.assertEqual(payload["user_supplied_problem_statement"], assignment["user_supplied_problem_statement"])

    def test_missing_input_schema_rejected_before_provider_call(self):
        provider = MockAIProvider(valid_response())
        result = generate_reference_solutions(
            {"problem_statement": "Find a maximum."}, provider
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("Agent 1", result["message"])
        self.assertEqual(provider.calls, [])

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
            {"problem_statement": "Find a maximum.", "input_format": "One integer.", "output_format": "Print one integer.", "input_schema": {
                "version": 1,
                "fields": [{"name": "x", "type": "int", "min": -10, "max": 10}],
                "size_field": "x",
            }},
            MockAIProvider({"problem_summary": "Incomplete"}),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertFalse(result["references_trusted"])

    def test_provider_error_is_reported(self):
        class FailingProvider:
            def generate_json(self, task, payload, schema):
                raise AIProviderError("Service unavailable")

        result = generate_reference_solutions(
            {"problem_statement": "Find a maximum.", "input_format": "One integer.", "output_format": "Print one integer.", "input_schema": {
                "version": 1,
                "fields": [{"name": "x", "type": "int", "min": -10, "max": 10}],
                "size_field": "x",
            }}, FailingProvider()
        )
        self.assertEqual(result["status"], "provider_error")


if __name__ == "__main__":
    unittest.main()
