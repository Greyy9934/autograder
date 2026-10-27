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


    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_single_candidate_generates_untrusted_references(
        self, mock_preflight, mock_generate
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        mock_generate.return_value = {
            "status": "generated_unverified",
            "references_trusted": False,
        }
        provider = MockAIProvider(reconstruction([candidate("A", "Print the sum.")]))

        result = evaluate_submission(
            "int main(void) { return 0; }", provider=provider
        )

        self.assertEqual(
            result["reference_solutions"]["status"], "generated_unverified"
        )
        self.assertFalse(result["reference_solutions"]["references_trusted"])
        mock_generate.assert_called_once()
        self.assertIs(mock_generate.call_args.args[1], provider)

    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_multiple_candidates_skip_reference_generation(
        self, mock_preflight, mock_generate
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(reconstruction([
            candidate("A", "Print the sum."),
            candidate("B", "Print the maximum."),
        ]))

        result = evaluate_submission(
            "int main(void) { return 0; }", provider=provider
        )

        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["reference_solutions"])
        mock_generate.assert_not_called()

    @patch("app.orchestrator.validate_reference_pair")
    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_reference_validation_failure_is_reported(
        self, mock_preflight, mock_generate, mock_validate
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        mock_generate.return_value = {
            "status": "generated_unverified",
            "references_trusted": False,
            "brute_force": {"code": "int main(void){return 0;}"},
            "efficient": {"code": "int main(void){return 0;}"},
            "validation": {},
        }
        mock_validate.return_value = {
            "status": "reference_agreement_inconclusive_or_failed",
            "brute_force": {"passed": False},
            "efficient": {"passed": True},
            "comparisons": [],
            "references_trusted": False,
        }
        provider = MockAIProvider(reconstruction([candidate("A", "Print the sum.")]))

        result = evaluate_submission(
            "int main(void){return 0;}",
            test_cases=[{"input": "", "expected_output": "0\n"}],
            provider=provider,
        )

        self.assertFalse(
            result["reference_solutions"]["validation"][
                "compiled_and_passed_supplied_cases"
            ]
        )
        self.assertFalse(result["reference_solutions"]["references_trusted"])

    @patch("app.orchestrator.validate_reference_pair")
    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_reference_validation_does_not_claim_trust(
        self, mock_preflight, mock_generate, mock_validate
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        mock_generate.return_value = {
            "status": "generated_unverified",
            "references_trusted": False,
            "brute_force": {"code": "int main(void){return 0;}"},
            "efficient": {"code": "int main(void){return 0;}"},
            "validation": {},
        }
        mock_validate.return_value = {
            "status": "references_agree_on_tested_cases",
            "brute_force": {"passed": True},
            "efficient": {"passed": True},
            "comparisons": [{"outputs_agree": True}],
            "references_trusted": False,
        }
        provider = MockAIProvider(reconstruction([candidate("A", "Print the sum.")]))

        result = evaluate_submission(
            "int main(void){return 0;}",
            test_cases=[{"input": "", "expected_output": "0\n"}],
            provider=provider,
        )

        self.assertTrue(
            result["reference_solutions"]["validation"][
                "compiled_and_passed_supplied_cases"
            ]
        )
        self.assertTrue(
            result["reference_solutions"]["validation"]["differentially_tested"]
        )
        self.assertFalse(result["reference_solutions"]["references_trusted"])
        self.assertFalse(result["correctness_assessed"])

    @patch("app.orchestrator.verify_algorithm")
    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_generated_references_trigger_mathematical_verification(
        self, mock_preflight, mock_generate, mock_verify
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        mock_generate.return_value = {
            "status": "generated_unverified",
            "references_trusted": False,
            "brute_force": {"code": "int main(void){return 0;}"},
            "efficient": {
                "code": "int main(void){return 0;}",
                "algorithm": "Return a constant.",
            },
            "validation": {},
        }
        mock_verify.return_value = {
            "status": "proof_sketch",
            "formally_verified": False,
        }
        provider = MockAIProvider(reconstruction([candidate("A", "Print the sum.")]))

        result = evaluate_submission(
            "int main(void){return 0;}", provider=provider
        )

        self.assertEqual(
            result["mathematical_verification"]["status"], "proof_sketch"
        )
        self.assertFalse(
            result["mathematical_verification"]["formally_verified"]
        )
        mock_verify.assert_called_once()

    @patch("app.orchestrator.verify_algorithm")
    @patch("app.orchestrator.generate_reference_solutions")
    @patch("app.orchestrator.preflight")
    def test_provider_reference_failure_skips_mathematical_verification(
        self, mock_preflight, mock_generate, mock_verify
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        mock_generate.return_value = {
            "status": "provider_error",
            "references_trusted": False,
        }
        provider = MockAIProvider(reconstruction([candidate("A", "Print the sum.")]))

        result = evaluate_submission(
            "int main(void){return 0;}", provider=provider
        )

        self.assertIsNone(result["mathematical_verification"])
        mock_verify.assert_not_called()

    @patch("app.orchestrator.preflight")
    def test_complexity_estimate_is_returned_when_preflight_passes(
        self, mock_preflight
    ):
        mock_preflight.return_value = {"decision": "continue", "status": "completed"}
        provider = MockAIProvider(
            reconstruction([candidate("A", "Print the sum.")])
        )

        result = evaluate_submission(
            "int main(void) { for (int i = 0; i < 10; i++) {} return 0; }",
            provider=provider,
        )

        self.assertEqual(result["complexity_estimate"]["status"], "completed")
        self.assertEqual(result["complexity_estimate"]["loop_count"], 1)
        self.assertIn("bounds", result["complexity_estimate"]["time_complexity"])

    @patch("app.orchestrator.preflight")
    def test_complexity_estimate_is_returned_when_preflight_blocks(
        self, mock_preflight
    ):
        mock_preflight.return_value = {"decision": "block", "status": "timeout"}

        result = evaluate_submission(
            "int main(void) { for (;;) {} return 0; }"
        )

        self.assertEqual(result["status"], "preflight_blocked")
        self.assertIsNotNone(result["complexity_estimate"])
        self.assertEqual(result["complexity_estimate"]["loop_count"], 1)

    @patch("app.orchestrator.analyze_memory_safety")
    @patch("app.orchestrator.preflight")
    def test_memory_diagnostics_run_when_enabled_and_preflight_passes(
        self, mock_preflight, mock_memory
    ):
        mock_preflight.return_value = {
            "decision": "continue",
            "status": "completed",
        }
        mock_memory.return_value = {"status": "completed", "results": []}

        provider = MockAIProvider(
            reconstruction([candidate("A", "Print the sum.")])
        )
        result = evaluate_submission(
            "int main(void) { return 0; }",
            provider=provider,
            run_memory_diagnostics=True,
        )

        self.assertEqual(result["memory_safety"]["status"], "completed")
        mock_memory.assert_called_once_with("int main(void) { return 0; }")

    @patch("app.orchestrator.analyze_memory_safety")
    @patch("app.orchestrator.preflight")
    def test_memory_diagnostics_skip_when_preflight_blocks(
        self, mock_preflight, mock_memory
    ):
        mock_preflight.return_value = {
            "decision": "block",
            "status": "timeout",
        }

        result = evaluate_submission(
            "int main(void) { return 0; }",
            run_memory_diagnostics=True,
        )

        self.assertIsNone(result["memory_safety"])
        mock_memory.assert_not_called()
if __name__ == "__main__":
    unittest.main()

