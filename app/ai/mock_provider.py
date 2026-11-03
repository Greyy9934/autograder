"""Predictable AI provider for tests; makes no network requests."""
# Module role: Implements the mock provider subsystem used by the AutoGrader workflow.

from copy import deepcopy
from typing import Any

from app.ai.base import AIProviderError


class MockAIProvider:
    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by MockAIProvider; it is reached through that object's workflow.
    def __init__(self, response: dict[str, Any]):
        self.response = deepcopy(response)
        self.calls: list[dict[str, Any]] = []

    # Function role: Requests one structured JSON response from the configured provider or deterministic fixture.
    # Context: method/helper owned by MockAIProvider; it is reached through that object's workflow.
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
