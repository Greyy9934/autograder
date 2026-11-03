"""Deterministic multi-scenario AI provider for exhaustive offline testing."""
# Module role: Implements the scenario provider subsystem used by the AutoGrader workflow.

from collections import deque
from copy import deepcopy
from typing import Any, Iterable

from app.ai.base import AIProviderError


class ScenarioAIProvider:
    """Replay realistic responses and failures without making network requests."""

    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by ScenarioAIProvider; it is reached through that object's workflow.
    def __init__(self, scenarios: Iterable[Any], *, repeat_last: bool = False):
        self._scenarios = deque(scenarios)
        self._last = None
        self.repeat_last = repeat_last
        self.calls: list[dict[str, Any]] = []

    # Function role: Implements remaining for scenario provider using this module's input and result contracts.
    # Context: method/helper owned by ScenarioAIProvider; it is reached through that object's workflow.
    @property
    def remaining(self) -> int:
        return len(self._scenarios)

    # Function role: Requests one structured JSON response from the configured provider or deterministic fixture.
    # Context: method/helper owned by ScenarioAIProvider; it is reached through that object's workflow.
    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({
            "task": task,
            "payload": deepcopy(payload),
            "schema": deepcopy(schema),
        })

        if self._scenarios:
            scenario = self._scenarios.popleft()
            self._last = scenario
        elif self.repeat_last and self._last is not None:
            scenario = self._last
        else:
            raise AIProviderError(
                "Scenario queue exhausted.",
                category="scenario_exhausted",
            )

        if isinstance(scenario, BaseException):
            raise scenario

        if callable(scenario):
            scenario = scenario(
                task=task,
                payload=deepcopy(payload),
                schema=deepcopy(schema),
            )

        if not isinstance(scenario, dict):
            raise AIProviderError(
                "Scenario response must be a JSON object.",
                category="invalid_response",
            )

        return deepcopy(scenario)


# Function role: Implements provider timeout for scenario provider using this module's input and result contracts.
def provider_timeout(message: str = "Simulated provider timeout.") -> AIProviderError:
    return AIProviderError(
        message, category="timeout", retryable=True
    )


# Function role: Implements provider rate limit for scenario provider using this module's input and result contracts.
def provider_rate_limit(message: str = "Simulated rate limit.") -> AIProviderError:
    return AIProviderError(
        message, category="rate_limit", retryable=True, status_code=429
    )


# Function role: Implements provider auth failure for scenario provider using this module's input and result contracts.
def provider_auth_failure(message: str = "Simulated authentication failure.") -> AIProviderError:
    return AIProviderError(
        message, category="authentication_error", status_code=401
    )


# Function role: Implements provider unavailable for scenario provider using this module's input and result contracts.
def provider_unavailable(message: str = "Simulated provider outage.") -> AIProviderError:
    return AIProviderError(
        message, category="provider_unavailable", retryable=True, status_code=503
    )
