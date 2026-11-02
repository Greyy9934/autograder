import unittest

from app.ai.base import AIProviderError
from app.ai.mock_provider import MockAIProvider
from analyzers.problem_reconstruction import reconstruct_problem


def candidate(identifier, title, statement, confidence):
    return {
        "id": identifier,
        "title": title,
        "problem_statement": statement,
        "input_format": "n followed by n integers.",
        "output_format": "Print the calculated result followed by a newline.",
        "input_schema": {
            "version": 1,
            "fields": [
                {"name": "n", "type": "int", "min": 1, "max": 100},
                {"name": "values", "type": "int_array", "length_from": "n", "min": -100, "max": 100},
            ],
            "size_field": "values",
        },
        "evidence": ["Line 4 reads n with scanf; line 5 reads n integer values."],
        "assumptions": ["The input contains integers."],
        "confidence": confidence,
    }


def response(candidates, status="ready", questions=None):
    return {
        "status": status,
        "candidates": candidates,
        "clarifying_questions": questions or [],
        "constraints": [],
        "limitations": [],
    }


class ReconstructionAITests(unittest.TestCase):
    def test_multiple_interpretations_are_preserved(self):
        options = [
            candidate("A", "Maximum", "Find the maximum array element.", 0.65),
            candidate("B", "Sum", "Calculate the sum of array elements.", 0.55),
        ]
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(response(options)),
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertIsNone(result["inferred_problem"])
        self.assertEqual(result["confidence"], "multiple_candidates")

    def test_single_interpretation_is_exposed(self):
        item = candidate("A", "Sum", "Calculate an array sum.", 0.9)
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(response([item])),
        )
        self.assertEqual(result["inferred_problem"], "Calculate an array sum.")
        self.assertEqual(result["confidence"], 0.9)

    def test_candidate_without_schema_is_rejected(self):
        item = candidate("A", "Sum", "Calculate an array sum.", 0.9)
        del item["input_schema"]
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(response([item])),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertIn("input_schema", result["message"])

    def test_unsupported_grammar_must_return_questions_without_candidate(self):
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(response([], status="needs_clarification", questions=[
                "Confirm the string-token input grammar and bounds."
            ])),
        )
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["candidates"], [])

    def test_malformed_response_is_not_trusted(self):
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider({"status": "ready", "candidates": []}),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertTrue(result["can_continue"])

    def test_code_is_sufficient_to_start_reconstruction_and_agent_owns_schema(self):
        provider = MockAIProvider(response([
            candidate("A", "Unknown", "A tentative interpretation.", 0.3)
        ]))
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=provider,
        )
        self.assertTrue(result["can_continue"])
        self.assertEqual(result["problem_statement_source"], "missing")
        self.assertEqual(result["valid_test_case_count"], 0)
        self.assertIsNone(provider.calls[0]["payload"]["problem_statement"])
        instructions = provider.calls[0]["payload"]["instructions"]
        self.assertIn("only required user field is C source", instructions)
        self.assertIn("Never ask the user to design or enter", instructions)
        self.assertIn("input_schema", provider.calls[0]["schema"]["properties"]["candidates"]["items"]["required"])

    def test_clarification_response_requires_question(self):
        invalid = response([], status="needs_clarification")
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(invalid),
        )
        self.assertEqual(result["status"], "provider_error")

    def test_provider_error_does_not_reject_submission(self):
        class BrokenProvider:
            def generate_json(self, task, payload, schema):
                raise AIProviderError("Temporary failure")

        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=BrokenProvider(),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertTrue(result["can_continue"])


if __name__ == "__main__":
    unittest.main()
