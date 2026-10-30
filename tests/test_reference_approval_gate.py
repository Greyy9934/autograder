from unittest.mock import Mock, patch

from analyzers.assignment_spec import AssignmentSpec
from app.orchestrator import (
    evaluate_submission,
    generate_reference_solutions_for_confirmed_spec,
)


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        return {
            "problem_summary": "Sum two integers.",
            "assumptions": [],
            "brute_force": {
                "algorithm": "Direct addition",
                "code": "int main(void) { return 0; }",
                "time_complexity": "O(1)",
                "space_complexity": "O(1)",
            },
            "efficient": {
                "algorithm": "Direct addition",
                "code": "int main(void) { return 0; }",
                "time_complexity": "O(1)",
                "space_complexity": "O(1)",
            },
            "limitations": [],
        }


def make_spec():
    return AssignmentSpec(
        problem_id="sum",
        title="Sum two integers",
        problem_statement="Read two integers and print their sum.",
        constraints=("Both integers are between -10 and 10.",),
        input_format="Two whitespace-separated integers.",
        output_format="Print their sum.",
    )


def test_agent_2_rejects_unconfirmed_spec_without_api_call():
    provider = FakeProvider()
    result = generate_reference_solutions_for_confirmed_spec(
        make_spec(), provider
    )

    assert result["status"] == "rejected"
    assert provider.calls == 0


def test_agent_2_runs_after_explicit_confirmation():
    provider = FakeProvider()
    spec = make_spec().confirm(instructor_approved=True)

    result = generate_reference_solutions_for_confirmed_spec(spec, provider)

    assert result["status"] == "generated_unverified"
    assert result["instructor_confirmed"] is True
    assert result["spec_fingerprint"] == spec.fingerprint()
    assert provider.calls == 1
    assert result["references_trusted"] is False


@patch("app.orchestrator.preflight")
@patch("app.orchestrator.reconstruct_problem")
def test_preparation_does_not_call_agent_2(mock_reconstruct, mock_preflight):
    provider = FakeProvider()
    mock_preflight.return_value = {"decision": "continue"}
    mock_reconstruct.return_value = {
        "status": "ready",
        "candidates": [{
            "id": "sum",
            "title": "Sum two integers",
            "problem_statement": "Read two integers and print their sum.",
            "input_format": "Two whitespace-separated integers.",
            "output_format": "Print their sum.",
        }],
        "constraints": ["Both integers are between -10 and 10."],
    }

    result = evaluate_submission(
        "int main(void) { return 0; }",
        provider=provider,
    )

    assert result["status"] == "reconstruction_ready"
    assert result["assignment_spec_status"] == "draft_requires_instructor_confirmation"
    assert result["reference_solutions"] is None
    assert provider.calls == 0
