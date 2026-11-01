import pytest

from app.ai.base import AIProviderError
from app.ai.scenario_provider import (
    ScenarioAIProvider,
    provider_auth_failure,
    provider_rate_limit,
    provider_timeout,
    provider_unavailable,
)


def test_replays_multiple_distinct_responses_in_order():
    provider = ScenarioAIProvider([
        {"status": "ready"},
        {"status": "needs_clarification"},
        {"status": "ready", "confidence": 0.99},
    ])

    assert provider.generate_json("agent1", {}, {}) == {"status": "ready"}
    assert provider.generate_json("agent1", {}, {}) == {
        "status": "needs_clarification"
    }
    assert provider.generate_json("agent1", {}, {}) == {
        "status": "ready", "confidence": 0.99
    }
    assert provider.remaining == 0
    assert len(provider.calls) == 3


def test_records_each_task_payload_and_schema():
    provider = ScenarioAIProvider([{"ok": True}])
    provider.generate_json(
        "reconstruct",
        {"source_code": "int main(void) {}"},
        {"type": "object"},
    )

    assert provider.calls[0]["task"] == "reconstruct"
    assert provider.calls[0]["payload"]["source_code"] == "int main(void) {}"
    assert provider.calls[0]["schema"] == {"type": "object"}


def test_recorded_inputs_are_defensively_copied():
    payload = {"items": [1]}
    schema = {"required": ["items"]}
    provider = ScenarioAIProvider([{"ok": True}])

    provider.generate_json("task", payload, schema)
    payload["items"].append(2)
    schema["required"].append("extra")

    assert provider.calls[0]["payload"] == {"items": [1]}
    assert provider.calls[0]["schema"] == {"required": ["items"]}


def test_returned_response_is_defensively_copied():
    provider = ScenarioAIProvider([{"items": [1]}], repeat_last=True)
    first = provider.generate_json("task", {}, {})
    first["items"].append(2)

    second = provider.generate_json("task", {}, {})
    assert second == {"items": [1]}


def test_scenario_queue_exhaustion_is_explicit():
    provider = ScenarioAIProvider([{"ok": True}])
    provider.generate_json("task", {}, {})

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == "scenario_exhausted"


def test_repeat_last_is_opt_in():
    provider = ScenarioAIProvider([{"status": "ready"}], repeat_last=True)

    assert provider.generate_json("task", {}, {}) == {"status": "ready"}
    assert provider.generate_json("task", {}, {}) == {"status": "ready"}


@pytest.mark.parametrize(
    ("factory", "category", "retryable", "status_code"),
    [
        (provider_timeout, "timeout", True, None),
        (provider_rate_limit, "rate_limit", True, 429),
        (provider_auth_failure, "authentication_error", False, 401),
        (provider_unavailable, "provider_unavailable", True, 503),
    ],
)
def test_provider_failure_scenarios(factory, category, retryable, status_code):
    provider = ScenarioAIProvider([factory()])

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == category
    assert caught.value.retryable is retryable
    assert caught.value.status_code == status_code


def test_callable_scenario_can_inspect_request():
    provider = ScenarioAIProvider([
        lambda task, payload, schema: {
            "task_received": task,
            "source_received": payload["source"],
            "schema_received": schema["type"],
        }
    ])

    result = provider.generate_json(
        "agent1", {"source": "int main(void) {}"}, {"type": "object"}
    )

    assert result == {
        "task_received": "agent1",
        "source_received": "int main(void) {}",
        "schema_received": "object",
    }


def test_non_object_scenario_is_rejected():
    provider = ScenarioAIProvider([["not", "an", "object"]])

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == "invalid_response"
