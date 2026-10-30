import unittest

from app.ai.base import AIProviderError
from app.ai.mock_provider import MockAIProvider
from analyzers.problem_reconstruction import reconstruct_problem


def candidate(identifier, title, statement, confidence):
    return {
        "id": identifier,
        "title": title,
        "problem_statement": statement,
        "input_format": "A sequence of integers separated by whitespace.",
        "output_format": "Print the calculated result followed by a newline.",
        "evidence": ["The source contains a loop over an integer array."],
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

    def test_malformed_response_is_not_trusted(self):
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider({"status": "ready", "candidates": []}),
        )
        self.assertEqual(result["status"], "provider_error")
        self.assertTrue(result["can_continue"])

    def test_missing_statement_and_tests_are_allowed(self):
        result = reconstruct_problem(
            "int main(void) { return 0; }",
            provider=MockAIProvider(response([
                candidate("A", "Unknown", "A tentative interpretation.", 0.3)
            ])),
        )
        self.assertTrue(result["can_continue"])
        self.assertEqual(result["problem_statement_source"], "missing")
        self.assertEqual(result["valid_test_case_count"], 0)

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
