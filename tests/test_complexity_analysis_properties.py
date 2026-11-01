"""Generated and adversarial tests for Agent 4 AI response validation."""

from copy import deepcopy

import pytest
from hypothesis import given, settings, strategies as st

from analyzers.complexity_analysis import (
    _validate_response,
    analyze_complexity,
)
from app.ai.mock_scenarios import get_scenario
from app.ai.scenario_provider import (
    ScenarioAIProvider,
    provider_timeout,
    provider_rate_limit,
    provider_auth_failure,
)


SOURCE = (
    "int main(void) {\n"
    "    int n = 10;\n"
    "    for (int i = 0; i < n; i++) {\n"
    "        puts(\"x\");\n"
    "    }\n"
    "}\n"
)


def valid_response():
    return get_scenario("agent4", "linear_scan")


@settings(max_examples=100, deadline=None)
@given(
    bad_line=st.integers(min_value=7, max_value=10**9)
)
def test_generated_out_of_range_source_references_are_rejected(bad_line):
    response = valid_response()
    response["evidence"][0]["line_start"] = bad_line
    response["evidence"][0]["line_end"] = bad_line
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("source-line" in error for error in errors)


@settings(max_examples=100, deadline=None)
@given(
    confidence=st.one_of(
        st.floats(max_value=-0.000001, allow_nan=False, allow_infinity=False),
        st.floats(min_value=1.000001, allow_nan=False, allow_infinity=False),
    )
)
def test_generated_out_of_range_confidence_is_rejected(confidence):
    response = valid_response()
    response["confidence"] = confidence
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("confidence" in error for error in errors)


@settings(max_examples=100, deadline=None)
@given(
    function_name=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu"),
            min_codepoint=65,
            max_codepoint=122,
        ),
        min_size=1,
        max_size=20,
    ).filter(lambda value: value.lower() not in {
        "log", "ln", "log2", "log10", "sqrt", "factorial",
        "exp", "log_star", "alpha",
    })
)
def test_generated_unsupported_complexity_functions_are_rejected(function_name):
    response = valid_response()
    response["time_complexity"]["worst_case"] = (
        f"O({function_name}(n))"
    )
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("unsupported or invalid" in error for error in errors)


@settings(max_examples=100, deadline=None)
@given(
    field=st.sampled_from([
        "name", "description", "input_size_model"
    ])
)
def test_generated_missing_algorithm_fields_are_rejected(field):
    response = valid_response()
    del response["algorithm"][field]
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any(f"algorithm.{field}" in error for error in errors)


@settings(max_examples=100, deadline=None)
@given(
    field=st.sampled_from([
        "best_case", "average_case", "worst_case"
    ])
)
def test_generated_invalid_time_complexity_fields_are_rejected(field):
    response = valid_response()
    response["time_complexity"][field] = " "
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any(
        f"time_complexity.{field}" in error for error in errors
    )


@settings(max_examples=100, deadline=None)
@given(
    line_start=st.integers(min_value=1, max_value=6),
    line_end=st.integers(min_value=1, max_value=6),
)
def test_generated_reversed_line_ranges_are_rejected(line_start, line_end):
    if line_start <= line_end:
        return
    response = valid_response()
    response["evidence"][0]["line_start"] = line_start
    response["evidence"][0]["line_end"] = line_end
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert any("source-line" in error for error in errors)


@pytest.mark.parametrize(
    "scenario",
    ["provider_timeout", "provider_rate_limit", "provider_auth_failure"],
)
def test_provider_failure_scenarios_are_returned_safely(scenario):
    factories = {
        "provider_timeout": provider_timeout,
        "provider_rate_limit": provider_rate_limit,
        "provider_auth_failure": provider_auth_failure,
    }
    provider = ScenarioAIProvider([factories[scenario]()])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] == "provider_error"
    assert result["provider_error"]["category"]
    assert isinstance(result["provider_error"]["retryable"], bool)


def test_provider_malformed_non_object_response_is_rejected():
    provider = ScenarioAIProvider([["not", "an", "object"]])
    result = analyze_complexity(SOURCE, provider)
    assert result["status"] == "provider_error"
    assert result["provider_error"]["category"] == "invalid_response"


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "algorithm",
        "time_complexity",
        "space_complexity",
        "evidence",
        "assumptions",
        "confidence",
        "limitations",
        "unresolved_questions",
    ],
)
def test_each_top_level_required_field_is_enforced(field):
    response = valid_response()
    del response[field]
    validated, errors = _validate_response(response, SOURCE)
    assert validated is None
    assert errors


def test_validation_does_not_mutate_provider_response():
    response = valid_response()
    before = deepcopy(response)
    _validate_response(response, SOURCE)
    assert response == before


def test_valid_but_semantically_wrong_response_remains_unproven():
    response = valid_response()
    response["time_complexity"]["worst_case"] = "O(1)"
    validated, errors = _validate_response(response, SOURCE)
    assert errors == []
    assert validated["time_complexity"]["worst_case"] == "O(1)"
    # Structural validation cannot prove that the algorithmic claim is true.
