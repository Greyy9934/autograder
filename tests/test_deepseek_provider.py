import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from app.ai.base import AIProviderError
from app.ai.deepseek_provider import DeepSeekProvider


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.data if size < 0 else self.data[:size]


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(content):
    return FakeResponse(json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode())


def test_sends_json_mode_request_and_parses_object():
    opener = FakeOpener([response('{"status":"ready"}')])
    provider = DeepSeekProvider(
        "test-key",
        opener=opener,
        sleep=lambda _: None,
    )

    result = provider.generate_json(
        "Analyze code",
        {"source": "int main(void) { return 0; }"},
        {"type": "object", "required": ["status"]},
    )

    assert result == {"status": "ready"}
    request, timeout = opener.calls[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert body["model"] == "deepseek-chat"
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in body["messages"][0]["content"]
    assert timeout == 45


def test_retries_temporary_http_error_then_succeeds():
    error = HTTPError("https://api.deepseek.com", 503, "unavailable", {}, BytesIO())
    opener = FakeOpener([error, response('{"ok":true}')])
    sleeps = []
    provider = DeepSeekProvider(
        "test-key",
        opener=opener,
        sleep=sleeps.append,
    )

    assert provider.generate_json("task", {}, {}) == {"ok": True}
    assert len(opener.calls) == 2
    assert sleeps == [0.5]


def test_does_not_retry_authentication_error():
    error = HTTPError("https://api.deepseek.com", 401, "unauthorized", {}, BytesIO())
    opener = FakeOpener([error])
    provider = DeepSeekProvider("test-key", opener=opener, sleep=lambda _: None)

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == "authentication_error"
    assert caught.value.retryable is False
    assert len(opener.calls) == 1


def test_classifies_rate_limit():
    error = HTTPError("https://api.deepseek.com", 429, "limited", {}, BytesIO())
    provider = DeepSeekProvider(
        "test-key",
        opener=FakeOpener([error]),
        max_retries=0,
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == "rate_limited"
    assert caught.value.status_code == 429


def test_retries_network_failure():
    opener = FakeOpener([URLError("offline"), response('{"ok":true}')])
    sleeps = []
    provider = DeepSeekProvider(
        "test-key",
        opener=opener,
        sleep=sleeps.append,
    )

    assert provider.generate_json("task", {}, {}) == {"ok": True}
    assert len(opener.calls) == 2
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ("not json", "invalid_json"),
        ("[1,2]", "invalid_json"),
        ("", "invalid_response"),
    ],
)
def test_rejects_invalid_model_output(content, category):
    provider = DeepSeekProvider(
        "test-key",
        opener=FakeOpener([response(content)]),
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {})

    assert caught.value.category == category


def test_rejects_empty_task():
    provider = DeepSeekProvider("test-key", opener=FakeOpener([]))

    with pytest.raises(AIProviderError, match="Task"):
        provider.generate_json(" ", {}, {})


def test_rejects_insecure_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        DeepSeekProvider("test-key", endpoint="http://localhost/api")


def test_rejects_more_than_two_retries():
    with pytest.raises(ValueError, match="max_retries"):
        DeepSeekProvider("test-key", max_retries=3)


def test_rejects_response_that_does_not_match_schema():
    provider = DeepSeekProvider(
        "test-key",
        opener=FakeOpener([response('{"status":123}')]),
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json(
            "task",
            {},
            {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        )

    assert caught.value.category == "schema_validation_error"


def test_rejects_oversized_response():
    provider = DeepSeekProvider(
        "test-key",
        max_response_bytes=20,
        opener=FakeOpener([FakeResponse(b"x" * 21)]),
    )

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {"type": "object"})

    assert caught.value.category == "response_too_large"


def test_rejects_invalid_schema_before_network_call():
    opener = FakeOpener([])
    provider = DeepSeekProvider("test-key", opener=opener)

    with pytest.raises(AIProviderError) as caught:
        provider.generate_json("task", {}, {"type": "not-a-json-schema-type"})

    assert caught.value.category == "invalid_request"
    assert opener.calls == []


def test_rejects_non_positive_response_limit():
    with pytest.raises(ValueError, match="max_response_bytes"):
        DeepSeekProvider("test-key", max_response_bytes=0)
