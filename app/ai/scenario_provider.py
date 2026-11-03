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
        # In-function documentation:
        # Parameters:
        #   - scenarios: the scenarios value used by this operation (type annotation: Iterable[Any]).
        #   - repeat_last: the repeat last value used by this operation (type annotation: bool).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: derive or store intermediate values.
        self._scenarios = deque(scenarios)
        self._last = None
        self.repeat_last = repeat_last
        self.calls: list[dict[str, Any]] = []

    # Function role: Implements remaining for scenario provider using this module's input and result contracts.
    # Context: method/helper owned by ScenarioAIProvider; it is reached through that object's workflow.
    @property
    def remaining(self) -> int:
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type int.
        # Flow: return the stage result.
        return len(self._scenarios)

    # Function role: Requests one structured JSON response from the configured provider or deterministic fixture.
    # Context: method/helper owned by ScenarioAIProvider; it is reached through that object's workflow.
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
        # Flow: delegate work to a helper or external boundary; branch on validation or workflow conditions.
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
    # In-function documentation:
    # Parameters:
    #   - message: the message value used by this operation (type annotation: str); defaults to 'Simulated provider timeout.' when omitted.
    # Returns: a value of declared type AIProviderError.
    # Flow: return the stage result.
    return AIProviderError(
        message, category="timeout", retryable=True
    )


# Function role: Implements provider rate limit for scenario provider using this module's input and result contracts.
def provider_rate_limit(message: str = "Simulated rate limit.") -> AIProviderError:
    # In-function documentation:
    # Parameters:
    #   - message: the message value used by this operation (type annotation: str); defaults to 'Simulated rate limit.' when omitted.
    # Returns: a value of declared type AIProviderError.
    # Flow: return the stage result.
    return AIProviderError(
        message, category="rate_limit", retryable=True, status_code=429
    )


# Function role: Implements provider auth failure for scenario provider using this module's input and result contracts.
def provider_auth_failure(message: str = "Simulated authentication failure.") -> AIProviderError:
    # In-function documentation:
    # Parameters:
    #   - message: the message value used by this operation (type annotation: str); defaults to 'Simulated authentication failure.' when omitted.
    # Returns: a value of declared type AIProviderError.
    # Flow: return the stage result.
    return AIProviderError(
        message, category="authentication_error", status_code=401
    )


# Function role: Implements provider unavailable for scenario provider using this module's input and result contracts.
def provider_unavailable(message: str = "Simulated provider outage.") -> AIProviderError:
    # In-function documentation:
    # Parameters:
    #   - message: the message value used by this operation (type annotation: str); defaults to 'Simulated provider outage.' when omitted.
    # Returns: a value of declared type AIProviderError.
    # Flow: return the stage result.
    return AIProviderError(
        message, category="provider_unavailable", retryable=True, status_code=503
    )
