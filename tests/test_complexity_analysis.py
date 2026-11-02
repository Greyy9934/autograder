import pytest

from analyzers.complexity_analysis import analyze_complexity, _validate_response
from app.ai.scenario_provider import ScenarioAIProvider, provider_timeout
from app.ai.mock_scenarios import get_scenario


SOURCE = (
    "int main(void) {\n"
    "    int n = 10;\n"
    "    for (int i = 0; i < n; i++) {\n"
    "        puts(\"x\");\n"
    "    }\n"
    "}\n"
)


def test_valid_ai_analysis_is_primary():
    provider = ScenarioAIProvider([get_scenario("agent4", "linear_scan")])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] == "analyzed"
    assert result["analysis_type"] == "ai_primary"
    assert result["proof_status"] == "not_proven"
    assert result["ai_analysis"]["time_complexity"]["worst_case"] == "O(n)"


def test_static_and_benchmark_are_only_supporting_evidence():
    static = {"time_complexity": "O(1)"}
    benchmark = {"growth_observations": [{"runtime_ratio": 2.0}]}
    provider = ScenarioAIProvider([get_scenario("agent4", "linear_scan")])
    result = analyze_complexity(
        SOURCE, provider, static_analysis=static, benchmark=benchmark
    )
    payload = provider.calls[0]["payload"]
    assert payload["static_analysis_supporting_evidence"] == static
    assert payload["empirical_benchmark_supporting_evidence"] == benchmark
    assert "primary algorithm complexity analyst" in payload["instructions"]
    assert result["supporting_evidence"] == {
        "static_analysis_supplied": True,
        "benchmark_supplied": True,
    }


@pytest.mark.parametrize(
    "scenario",
    ["nested_loops", "recursive_divide_and_conquer", "sorting", "inconclusive"],
)
def test_additional_agent4_scenarios_are_accepted(scenario):
    provider = ScenarioAIProvider([get_scenario("agent4", scenario)])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] in {"analyzed", "inconclusive"}


def test_structurally_valid_but_wrong_ai_conclusion_is_not_mistaken_for_proof():
    provider = ScenarioAIProvider([get_scenario("agent4", "plausible_but_wrong")])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] == "analyzed"
    assert result["ai_analysis"]["time_complexity"]["worst_case"] == "O(1)"
    assert result["proof_status"] == "not_proven"


def test_invalid_source_line_reference_is_rejected():
    response = get_scenario("agent4", "linear_scan")
    response["evidence"][0]["line_end"] = 999
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("source-line" in error for error in errors)


def test_reversed_source_line_reference_is_rejected():
    response = get_scenario("agent4", "linear_scan")
    response["evidence"][0]["line_start"] = 5
    response["evidence"][0]["line_end"] = 3
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("source-line" in error for error in errors)


def test_unsupported_complexity_expression_is_rejected():
    response = get_scenario("agent4", "linear_scan")
    response["time_complexity"]["worst_case"] = "O(unknown(n))"
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("unsupported or invalid" in error for error in errors)


def test_missing_required_content_is_rejected():
    response = get_scenario("agent4", "linear_scan")
    del response["algorithm"]["name"]
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("algorithm.name" in error for error in errors)


def test_boolean_confidence_is_rejected():
    response = get_scenario("agent4", "linear_scan")
    response["confidence"] = True
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("confidence" in error for error in errors)


def test_analyzed_result_requires_worst_case_and_space():
    response = get_scenario("agent4", "linear_scan")
    response["time_complexity"]["worst_case"] = None
    response["space_complexity"]["auxiliary"] = None
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("worst-case" in error for error in errors)
    assert any("auxiliary and total space" in error for error in errors)


def test_provider_timeout_is_reported_without_crashing():
    provider = ScenarioAIProvider([provider_timeout()])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] == "provider_error"
    assert result["provider_error"]["category"] == "timeout"
    assert result["provider_error"]["retryable"] is True


@pytest.mark.parametrize("source", ["", "   ", None])
def test_invalid_source_is_rejected_without_provider_call(source):
    provider = ScenarioAIProvider([])
    result = analyze_complexity(source, provider)
    assert result["status"] == "invalid_request"
    assert provider.calls == []


def test_invalid_supporting_evidence_type_is_rejected():
    provider = ScenarioAIProvider([])
    result = analyze_complexity(SOURCE, provider, static_analysis="not-an-object")
    assert result["status"] == "invalid_request"
    assert provider.calls == []


def test_agent4_receives_approved_io_contract():
    context = {
        "problem_statement": "Sum the n values.",
        "constraints": ["1 <= n <= 10"],
        "input_format": "n followed by n integers",
        "output_format": "One integer: the sum",
        "input_schema": {
            "version": 1,
            "fields": [
                {"name": "n", "type": "int", "min": 1, "max": 10},
                {"name": "values", "type": "int_array", "length_from": "n", "min": -9, "max": 9},
            ],
            "size_field": "values",
        },
    }
    provider = ScenarioAIProvider([get_scenario("agent4", "linear_scan")])
    result = analyze_complexity(SOURCE, provider, problem_context=context)
    assert result["status"] == "analyzed"
    contract = provider.calls[0]["payload"]["approved_io_contract"]
    assert {key: contract[key] for key in context} == context
    assert contract["output_contract"]["format"] == context["output_format"]
