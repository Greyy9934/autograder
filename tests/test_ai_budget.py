from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ai.base import AIProviderError
from app.ai.budget import BudgetedProvider, RequestBudget


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def generate_json(self, task, payload, schema):
        self.calls += 1
        return {"ok": True}


def test_budget_reserves_credits_and_rejects_exhaustion(tmp_path):
    budget = RequestBudget(tmp_path / "usage.sqlite3", daily_limit=5)

    assert budget.reserve(3) == 3
    assert budget.reserve(2) == 5

    with pytest.raises(AIProviderError) as caught:
        budget.reserve(1)

    assert caught.value.category == "budget_exhausted"


def test_budget_persists_across_instances(tmp_path):
    path = tmp_path / "usage.sqlite3"
    RequestBudget(path, daily_limit=4).reserve(3)

    second_instance = RequestBudget(path, daily_limit=4)
    with pytest.raises(AIProviderError):
        second_instance.reserve(2)


def test_concurrent_reservations_cannot_exceed_limit(tmp_path):
    budget = RequestBudget(tmp_path / "usage.sqlite3", daily_limit=10)

    def reserve():
        try:
            budget.reserve(1)
            return True
        except AIProviderError:
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        outcomes = list(executor.map(lambda _: reserve(), range(20)))

    assert sum(outcomes) == 10


def test_budgeted_provider_blocks_before_call(tmp_path):
    budget = RequestBudget(tmp_path / "usage.sqlite3", daily_limit=2)
    provider = FakeProvider()
    guarded = BudgetedProvider(provider, budget, credits_per_call=2)

    assert guarded.generate_json("task", {}, {}) == {"ok": True}

    with pytest.raises(AIProviderError) as caught:
        guarded.generate_json("task", {}, {})

    assert caught.value.category == "budget_exhausted"
    assert provider.calls == 1
