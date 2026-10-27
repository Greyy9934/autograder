"""Predictable AI provider for tests; makes no network requests."""

from copy import deepcopy
from typing import Any

from app.ai.base import AIProviderError


class MockAIProvider:
    def __init__(self, response: dict[str, Any]):
        self.response = deepcopy(response)
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(self.response, dict):
            raise AIProviderError("Provider response must be a JSON object.")

        self.calls.append({
            "task": task,
            "payload": deepcopy(payload),
            "schema": deepcopy(schema),
        })
        return deepcopy(self.response)
