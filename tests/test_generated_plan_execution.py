import hashlib
from unittest.mock import patch

from app.orchestrator import evaluate_execution_evidence


def prepared(source):
    return {
        "status": "reconstruction_ready",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "preflight": {"decision": "continue"},
        "reconstruction": {
            "status": "ready",
            "candidates": [{"id": "sum", "problem_statement": "Sum integers."}],
            "constraints": [],
        },
        "reference_solutions": None,
    }


def plans(source):
    return {
        "status": "generated",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "spec_fingerprint": "a" * 64,
        "random_tests": {
            "status": "generated",
            "spec_fingerprint": "a" * 64,
            "inputs": ["1 2\n", "3 4\n"],
        },
        "adversarial_tests": {
            "status": "planned",
            "spec_fingerprint": "a" * 64,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "cases": [{"input": "0 0\n"}],
        },
    }


@patch("analyzers.random_test_execution.execute_random_test_inputs")
@patch("analyzers.adversarial_execution.execute_adversarial_candidates")
def test_generated_plans_reach_both_execution_agents(mock_adversarial, mock_random):
    source = "int main(void) { return 0; }"
    mock_adversarial.return_value = {"status": "completed", "results": []}
    mock_random.return_value = {"status": "completed", "results": []}

    result = evaluate_execution_evidence(
        source, prepared(source), generated_test_plans=plans(source)
    )

    mock_adversarial.assert_called_once()
    mock_random.assert_called_once_with(source, ["1 2\n", "3 4\n"])
    assert result["execution_status"] == "completed"
    assert result["execution_evidence_summary"]["correctness_score_contribution"] is None


@patch("analyzers.random_test_execution.execute_random_test_inputs")
@patch("analyzers.adversarial_execution.execute_adversarial_candidates")
def test_modified_source_rejects_generated_plans(mock_adversarial, mock_random):
    source = "int main(void) { return 0; }"
    changed_source = source + "\n"
    result = evaluate_execution_evidence(
        changed_source, prepared(changed_source), generated_test_plans=plans(source)
    )

    mock_adversarial.assert_not_called()
    mock_random.assert_not_called()
    assert result["execution_status"] == "not_run"


@patch("analyzers.random_test_execution.execute_random_test_inputs")
@patch("analyzers.adversarial_execution.execute_adversarial_candidates")
def test_mismatched_spec_fingerprints_reject_both_plans(mock_adversarial, mock_random):
    source = "int main(void) { return 0; }"
    generated = plans(source)
    generated["random_tests"]["spec_fingerprint"] = "b" * 64

    result = evaluate_execution_evidence(
        source, prepared(source), generated_test_plans=generated
    )

    mock_adversarial.assert_not_called()
    mock_random.assert_not_called()
    assert result["execution_status"] == "not_run"
