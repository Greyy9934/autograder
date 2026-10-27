import json

import pytest

from app.ai.base import AIProviderError
from app.ai.gemini_provider import GeminiProvider


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models):
        self.models = models


@pytest.fixture
def schema():
    return {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }


def test_generates_json_with_schema(schema):
    models = FakeModels(FakeResponse('{"status":"ready"}'))
    provider = GeminiProvider(
        api_key="test-key",
        model="test-model",
        client=FakeClient(models),
    )

    result = provider.generate_json("Check task", {"source": "int main(){}"}, schema)

    assert result == {"status": "ready"}
    call = models.calls[0]
    assert call["model"] == "test-model"
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_json_schema"] == schema
    assert "temperature" not in call["config"]


def test_rejects_invalid_json(schema):
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(FakeModels(FakeResponse("not json"))),
    )
    with pytest.raises(AIProviderError, match="invalid JSON"):
        provider.generate_json("Check", {}, schema)


def test_rejects_non_object_json(schema):
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(FakeModels(FakeResponse("[1, 2]"))),
    )
    with pytest.raises(AIProviderError, match="JSON object"):
        provider.generate_json("Check", {}, schema)


def test_handles_empty_response(schema):
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(FakeModels(FakeResponse(None))),
    )
    with pytest.raises(AIProviderError, match="empty response"):
        provider.generate_json("Check", {}, schema)


def test_wraps_api_errors(schema):
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(FakeModels(error=RuntimeError("network failure"))),
    )
    with pytest.raises(AIProviderError, match="RuntimeError"):
        provider.generate_json("Check", {}, schema)


def test_rejects_empty_task(schema):
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(FakeModels(FakeResponse("{}"))),
    )
    with pytest.raises(AIProviderError, match="Task"):
        provider.generate_json(" ", {}, schema)


@pytest.mark.parametrize(
    ("code", "category", "retryable"),
    [
        (429, "rate_limited", True),
        (503, "provider_unavailable", True),
        (401, "authentication_error", False),
        (403, "authentication_error", False),
        (404, "invalid_request_or_model", False),
    ],
)
def test_classifies_api_errors(schema, code, category, retryable):
    models = FakeModels(error=FakeAPIError(code))
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(models),
        max_retries=0,
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("Check", {}, schema)

    assert caught.value.category == category
    assert caught.value.retryable is retryable
    assert caught.value.status_code == code


def test_retries_temporary_error_then_succeeds(schema):
    models = FakeModelsSequence(
        [FakeAPIError(503), FakeResponse('{"status":"ready"}')]
    )
    sleeps = []
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(models),
        sleep=sleeps.append,
    )

    result = provider.generate_json("Check", {}, schema)

    assert result == {"status": "ready"}
    assert len(models.calls) == 2
    assert sleeps == [0.5]


def test_stops_after_bounded_retries(schema):
    models = FakeModels(error=FakeAPIError(503))
    sleeps = []
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(models),
        sleep=sleeps.append,
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("Check", {}, schema)

    assert caught.value.category == "provider_unavailable"
    assert len(models.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_does_not_retry_authentication_error(schema):
    models = FakeModels(error=FakeAPIError(403))
    sleeps = []
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeClient(models),
        sleep=sleeps.append,
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("Check", {}, schema)

    assert caught.value.category == "authentication_error"
    assert len(models.calls) == 1
    assert sleeps == []


def test_rejects_more_than_two_retries():
    with pytest.raises(ValueError, match="max_retries"):
        GeminiProvider(
            api_key="test-key",
            client=FakeClient(FakeModels()),
            max_retries=3,
        )


class FakeAPIError(Exception):
    def __init__(self, code):
        super().__init__("simulated API failure")
        self.code = code


class FakeModelsSequence(FakeModels):
    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = list(outcomes)

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
