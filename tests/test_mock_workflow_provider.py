import json
import subprocess
import sys

from app.ai.mock_workflow_provider import MockWorkflowProvider, _generator_program


def test_mock_provider_routes_each_agent_task_without_network_calls():
    provider = MockWorkflowProvider()
    cases = [
        ("Reconstruct the intended programming problem.", {}, {}),
        ("Generate candidate C reference solutions.", {}, {}),
        ("Design a problem-specific randomized test generator for Agent 3A.", {
            "agent1_input_schema": {"token_count": 3, "minimum": -5, "maximum": 5}
        }, {}),
        ("Discover concrete adversarial edge cases for the submitted C program.", {
            "agent1_input_schema": {"token_count": 3, "minimum": -5, "maximum": 5}
        }, {}),
        ("Perform AI-first time and space complexity analysis.", {}, {}),
        ("Produce a mathematical correctness proof or concrete counterexample.", {}, {}),
        ("Perform the final AI-led code quality and maintainability review.", {
            "submitted_source_code": "int main(void) { return 0; }"
        }, {}),
    ]
    results = [provider.generate_json(task, payload, schema) for task, payload, schema in cases]
    assert len(provider.calls) == 7
    assert results[0]["status"] == "needs_clarification"
    assert results[0]["candidates"] == []
    assert results[0]["clarifying_questions"]
    assert results[0]["limitations"]
    assert "brute_force" in results[1]
    assert "generator_program" in results[2]
    assert len(results[3]["cases"]) == 3
    assert results[4]["status"] == "inconclusive"
    assert results[5]["outcome"] == "inconclusive"
    assert "SIMULATED AGENT 6 RESPONSE" in results[6]["limitations"][0]


def test_mock_agent3a_generator_is_reproducible_and_emits_valid_legacy_inputs():
    code = _generator_program({
        "token_count": 4, "minimum": -10, "maximum": 10
    })
    run = subprocess.run(
        [sys.executable, "-c", code, "42", "5"],
        check=True, capture_output=True, text=True,
    )
    cases = json.loads(run.stdout)["inputs"]
    assert len(cases) == 5
    assert all(len(case["input"].split()) == 4 for case in cases)
    assert run.stdout == subprocess.run(
        [sys.executable, "-c", code, "42", "5"],
        check=True, capture_output=True, text=True,
    ).stdout


def test_mock_agent3a_generator_respects_structured_schema_and_stratifies_size():
    schema = {
        "version": 1,
        "size_field": "values",
        "fields": [
            {"name": "n", "type": "int", "min": 1, "max": 20},
            {"name": "values", "type": "int_array", "length_from": "n", "min": -9, "max": 9},
            {"name": "target", "type": "int", "min": -9, "max": 9},
        ],
    }
    code = _generator_program(schema)
    run = subprocess.run(
        [sys.executable, "-c", code, "7", "4"],
        check=True, capture_output=True, text=True,
    )
    cases = json.loads(run.stdout)["inputs"]
    sizes = [int(case["input"].splitlines()[0]) for case in cases]
    assert all(1 <= size <= 20 for size in sizes)
    assert all(len(case["input"].splitlines()[1].split()) == sizes[i] for i, case in enumerate(cases))


def test_mock_agent3a_keeps_large_batches_brute_force_focused():
    schema = {
        "version": 1,
        "size_field": "values",
        "fields": [
            {"name": "n", "type": "int", "min": 1, "max": 20000},
            {"name": "values", "type": "int_array", "length_from": "n", "min": -9, "max": 9},
        ],
    }
    code = _generator_program(schema)
    run = subprocess.run(
        [sys.executable, "-c", code, "17", "100"],
        check=True, capture_output=True, text=True,
    )
    sizes = [int(case["input"].splitlines()[0]) for case in json.loads(run.stdout)["inputs"]]
    assert len(sizes) == 100
    assert max(sizes) <= 128
    assert sum(size <= 32 for size in sizes) >= 60


def test_mock_agent_responses_match_real_agent_json_schemas():
    from jsonschema import Draft202012Validator
    from analyzers.problem_reconstruction import RECONSTRUCTION_SCHEMA
    from analyzers.reference_solutions import REFERENCE_SCHEMA
    from analyzers.agent3_ai import GENERATOR_SCHEMA, EDGE_SCHEMA
    from analyzers.complexity_analysis import COMPLEXITY_ANALYSIS_SCHEMA
    from analyzers.mathematical_verification import VERIFICATION_SCHEMA
    from analyzers.code_quality import CODE_QUALITY_SCHEMA

    provider = MockWorkflowProvider()
    requests = [
        ("Reconstruct the intended programming problem.", {}, RECONSTRUCTION_SCHEMA),
        ("Generate candidate C reference solutions.", {}, REFERENCE_SCHEMA),
        ("Design a problem-specific randomized test generator for Agent 3A.",
         {"agent1_input_schema": {"token_count": 3, "minimum": -2, "maximum": 2}}, GENERATOR_SCHEMA),
        ("Discover concrete adversarial edge cases for the submitted C program.",
         {"agent1_input_schema": {"token_count": 3, "minimum": -2, "maximum": 2}}, EDGE_SCHEMA),
        ("Perform AI-first time and space complexity analysis.", {}, COMPLEXITY_ANALYSIS_SCHEMA),
        ("Produce a mathematical correctness proof or concrete counterexample.", {}, VERIFICATION_SCHEMA),
        ("Perform the final AI-led code quality and maintainability review.",
         {"submitted_source_code": "int main(void) { return 0; }"}, CODE_QUALITY_SCHEMA),
    ]
    for task, payload, schema in requests:
        response = provider.generate_json(task, payload, schema)
        errors = list(Draft202012Validator(schema).iter_errors(response))
        assert not errors, f"{task}: " + "; ".join(error.message for error in errors)


def test_mock_agent1_only_selects_two_sum_when_statement_explicitly_says_two_sum():
    provider = MockWorkflowProvider()

    unrelated = provider.generate_json(
        "Reconstruct the intended programming problem.",
        {"problem_statement": "Read two integers and print their sum."},
        {},
    )
    assert unrelated["status"] == "needs_clarification"
    assert unrelated["candidates"] == []

    demo = provider.generate_json(
        "Reconstruct the intended programming problem.",
        {"problem_statement": "Two Sum: find two values that add to target."},
        {},
    )
    assert demo["status"] == "ready"
    assert demo["candidates"]
    assert any("SIMULATED DEMO" in item for item in demo["limitations"])
