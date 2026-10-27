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
