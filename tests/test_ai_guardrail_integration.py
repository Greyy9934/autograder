import pytest

from app.ai.base import AIProviderError
from app.ai.budget import BudgetedProvider


SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ready"]}},
    "required": ["status"],
    "additionalProperties": False,
}


class FakeBudget:
    def __init__(self):
        self.reservations = 0

    def reserve(self, credits):
        self.reservations += credits


class FakeProvider:
    def __init__(self, result):
        self.result = result

    def generate_json(self, task, payload, schema):
        return self.result


def test_budgeted_provider_preserves_concrete_provider_and_validates_output():
    raw = FakeProvider({"status": "ready"})
    budget = FakeBudget()
    provider = BudgetedProvider(raw, budget, credits_per_call=2)

    assert provider.provider is raw
    assert provider.generate_json("task", {}, SCHEMA) == {"status": "ready"}
    assert budget.reservations == 2


def test_budgeted_provider_rejects_schema_invalid_provider_output():
    raw = FakeProvider({"status": "not-ready"})
    provider = BudgetedProvider(raw, FakeBudget())

    with pytest.raises(AIProviderError) as error:
        provider.generate_json("task", {}, SCHEMA)

    assert error.value.category == "schema_validation_error"


def test_budgeted_provider_rejects_extra_output_fields():
    raw = FakeProvider({"status": "ready", "grade": 100})
    provider = BudgetedProvider(raw, FakeBudget())

    with pytest.raises(AIProviderError):
        provider.generate_json("task", {}, SCHEMA)
