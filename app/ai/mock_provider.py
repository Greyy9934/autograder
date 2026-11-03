"""Predictable AI provider for tests; makes no network requests."""
# This file handles mock provider as one part of the app.

from copy import deepcopy
from typing import Any

from app.ai.base import AIProviderError


class MockAIProvider:
    def __init__(self, response: dict[str, Any]):
        # Helps with init inside init.
        # What the inputs mean:
        # - response: the reply received from the AI service or web request.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.response = deepcopy(response)
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        # Handles init as a supporting part of mock provider .
        # What the inputs mean:
        # - task: the task used for this step.
        # - payload: the information being sent to an AI service.
        # - schema: the schema used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns a set of named results for the next step.
        if not isinstance(self.response, dict):
            raise AIProviderError("Provider response must be a JSON object.")

        self.calls.append({
            "task": task,
            "payload": deepcopy(payload),
            "schema": deepcopy(schema),
        })
        return deepcopy(self.response)
