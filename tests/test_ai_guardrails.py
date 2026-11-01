import pytest

from app.ai.base import AIProviderError
from app.ai.guardrails import GuardedProvider


SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ready", "blocked"]}},
    "required": ["status"],
    "additionalProperties": False,
}


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def generate_json(self, task, payload, schema):
        self.calls += 1
        return self.result


def test_valid_response_passes_schema():
    provider = FakeProvider({"status": "ready"})
    result = GuardedProvider(provider).generate_json("Review", {}, SCHEMA)
    assert result == {"status": "ready"}
    assert provider.calls == 1


def test_invalid_response_is_rejected():
    provider = FakeProvider({"status": "maybe"})
    with pytest.raises(AIProviderError) as error:
        GuardedProvider(provider).generate_json("Review", {}, SCHEMA)
    assert error.value.category == "schema_validation_error"


def test_extra_response_fields_are_rejected():
    provider = FakeProvider({"status": "ready", "score": 100})
    with pytest.raises(AIProviderError):
        GuardedProvider(provider).generate_json("Review", {}, SCHEMA)


def test_non_json_payload_is_rejected_before_provider_call():
    provider = FakeProvider({"status": "ready"})
    with pytest.raises(AIProviderError):
        GuardedProvider(provider).generate_json(
            "Review", {"bad": object()}, SCHEMA
        )
    assert provider.calls == 0


def test_nan_payload_is_rejected_before_provider_call():
    provider = FakeProvider({"status": "ready"})
    with pytest.raises(AIProviderError):
        GuardedProvider(provider).generate_json(
            "Review", {"number": float("nan")}, SCHEMA
        )
    assert provider.calls == 0


def test_oversized_payload_is_rejected_before_provider_call(monkeypatch):
    monkeypatch.setenv("AUTOGRADER_AI_MAX_PAYLOAD_BYTES", "1024")
    provider = FakeProvider({"status": "ready"})
    guarded = GuardedProvider(provider)
    with pytest.raises(AIProviderError) as error:
        guarded.generate_json("Review", {"data": "x" * 2000}, SCHEMA)
    assert error.value.category == "input_too_large"
    assert provider.calls == 0


def test_invalid_schema_is_rejected_before_provider_call():
    provider = FakeProvider({"status": "ready"})
    with pytest.raises(AIProviderError) as error:
        GuardedProvider(provider).generate_json(
            "Review", {}, {"type": "not-a-real-json-schema-type"}
        )
    assert error.value.category == "invalid_schema"
    assert provider.calls == 0


def test_provider_failure_is_not_silently_replaced():
    class BrokenProvider:
        def generate_json(self, task, payload, schema):
            raise AIProviderError("Provider unavailable", category="network_error")

    with pytest.raises(AIProviderError) as error:
        GuardedProvider(BrokenProvider()).generate_json("Review", {}, SCHEMA)
    assert error.value.category == "network_error"
