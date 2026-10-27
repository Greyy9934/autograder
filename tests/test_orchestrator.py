import unittest
from unittest.mock import patch

from app.orchestrator import evaluate_submission
from app.ai.mock_provider import MockAIProvider


def candidate(identifier, statement):
    return {
        "id": identifier,
        "title": identifier,
        "problem_statement": statement,
        "evidence": ["Source evidence"],
        "assumptions": [],
        "confidence": 0.7,
    }


def reconstruction(candidates, status="ready", questions=None):
    return {
        "status": status,
        "candidates": candidates,
        "clarifying_questions": questions or [],
        "constraints": [],
        "limitations": [],
    }


class OrchestratorTests(unittest.TestCase):
    @patch("app.orchestrator.preflight")
    def test_blocked_preflight_does_not_call_provider(self, mock_preflight):
        mock_preflight.return_value = {"decision": "block", "status": "timeout"}

        result = evaluate_submission("int main(void) { return 0; }")

        self.assertEqual(result["status"], "preflight_blocked")
        self.assertIsNone(result["reconstruction"])
        mock_preflight.assert_called_once()

    @patch("app.orchestrator.preflight")
    def test_single_candidate_is_reconstruction_ready(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Print the sum.")])
        )

        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
        )

        self.assertEqual(result["status"], "reconstruction_ready")
        self.assertFalse(result["correctness_assessed"])

    @patch("app.orchestrator.preflight")
    def test_multiple_candidates_require_clarification(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([
                candidate("A", "Print the sum."),
                candidate("B", "Print the maximum."),
            ])
        )

        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
        )

        self.assertEqual(result["status"], "needs_clarification")
        self.assertFalse(result["correctness_assessed"])

    @patch("app.orchestrator.preflight")
    def test_provider_failure_preserves_preflight(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider({"malformed": True})

        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
        )

        self.assertEqual(result["status"], "ai_unavailable")
        self.assertEqual(result["preflight"]["decision"], "continue")
        self.assertFalse(result["correctness_assessed"])

    @patch("app.orchestrator.preflight")
    @patch("app.orchestrator.create_ai_provider", return_value=None)
    def test_no_provider_allows_intake_without_ai(
        self, mock_factory, mock_preflight
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}

        result = evaluate_submission("int main(void) { return 0; }")

        self.assertEqual(result["status"], "reconstruction_ready")
        self.assertEqual(
            result["reconstruction"]["status"],
            "ready_for_reconstruction",
        )


if __name__ == "__main__":
    unittest.main()

    @patch("app.orchestrator.preflight")
    def test_source_risks_are_returned_when_preflight_passes(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Print the sum.")])
        )

        result = evaluate_submission(
            "int main(void) { int x = a[2]; return 0; }",
            provider=provider,
        )

        self.assertIn("source_risks", result)
        self.assertGreater(result["source_risks"]["count"], 0)
        self.assertTrue(
            all(not item["confirmed_bug"]
                for item in result["source_risks"]["findings"])
        )

    @patch("app.orchestrator.preflight")
    def test_source_risks_are_returned_when_preflight_blocks(self, mock_preflight):
        mock_preflight.return_value = {"decision": "block", "status": "timeout"}

        result = evaluate_submission(
            "int main(void) { int a[2]; return a[3]; }"
        )

        self.assertEqual(result["status"], "preflight_blocked")
        self.assertIn("source_risks", result)
        self.assertGreater(result["source_risks"]["count"], 0)
        self.assertIsNone(result["reconstruction"])

    @patch("app.orchestrator.preflight")
    def test_single_candidate_generates_edge_case_ideas(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Given an integer n, print its value.")])
        )

        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
        )

        self.assertEqual(result["status"], "reconstruction_ready")
        self.assertIsNotNone(result["edge_cases"])
        self.assertGreater(result["edge_cases"]["count"], 0)
        self.assertFalse(result["edge_cases"]["concrete_inputs_generated"])

    @patch("app.orchestrator.preflight")
    def test_multiple_candidates_do_not_generate_edge_cases(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([
                candidate("A", "Print the sum."),
                candidate("B", "Print the maximum."),
            ])
        )

        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
        )

        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["edge_cases"])

    @patch("app.orchestrator.preflight")
    def test_supplied_test_cases_are_evaluated(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Read an integer and print it.")])
        )

        result = evaluate_submission(
            '#include <stdio.h>\nint main(void){int n;if(scanf("%d",&n)!=1)return 1;printf("%d\\n",n);}',
            problem_statement="Read an integer and print it.",
            test_cases=[{"input": "7\n", "expected_output": "7\n"}],
            provider=provider,
        )

        self.assertEqual(result["test_evaluation"]["passed"], 1)
        self.assertEqual(result["test_evaluation"]["failed"], 0)
        self.assertFalse(result["correctness_assessed"])

    @patch("app.orchestrator.preflight")
    def test_failing_test_case_is_reported(self, mock_preflight):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Print the expected word.")])
        )

        result = evaluate_submission(
            '#include <stdio.h>\nint main(void){puts("wrong");}',
            problem_statement="Print the expected word.",
            test_cases=[{"input": "", "expected_output": "right\n"}],
            provider=provider,
        )

        self.assertEqual(result["test_evaluation"]["failed"], 1)
        self.assertFalse(result["test_evaluation"]["results"][0]["passed"])
        self.assertFalse(result["correctness_assessed"])
