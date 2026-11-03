"""Predictable AI provider for tests; makes no network requests."""
# Module role: Implements the mock provider subsystem used by the AutoGrader workflow.

from copy import deepcopy
from typing import Any

from app.ai.base import AIProviderError


class MockAIProvider:
    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by MockAIProvider; it is reached through that object's workflow.
    def __init__(self, response: dict[str, Any]):
        # In-function documentation:
        # Parameters:
        #   - response: structured provider or HTTP response being checked or converted (type annotation: dict[str, Any]).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: derive or store intermediate values.
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
        # In-function documentation:
        # Parameters:
        #   - task: the task value used by this operation (type annotation: str).
        #   - payload: the request data being sent across an API/provider boundary (type annotation: dict[str, Any]).
        #   - schema: declared data contract inputs or results must satisfy (type annotation: dict[str, Any]).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type dict[str, Any].
        # Flow: branch on validation or workflow conditions; delegate work to a helper or external boundary; return the stage result.
        if not isinstance(self.response, dict):
            raise AIProviderError("Provider response must be a JSON object.")

        self.calls.append({
            "task": task,
            "payload": deepcopy(payload),
            "schema": deepcopy(schema),
        })
        return deepcopy(self.response)
