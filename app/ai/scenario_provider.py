"""Deterministic multi-scenario AI provider for exhaustive offline testing."""

from collections import deque
from copy import deepcopy
from typing import Any, Iterable

from app.ai.base import AIProviderError


class ScenarioAIProvider:
    """Replay realistic responses and failures without making network requests."""

    def __init__(self, scenarios: Iterable[Any], *, repeat_last: bool = False):
        self._scenarios = deque(scenarios)
        self._last = None
        self.repeat_last = repeat_last
        self.calls: list[dict[str, Any]] = []

    @property
    def remaining(self) -> int:
        return len(self._scenarios)

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


def provider_timeout(message: str = "Simulated provider timeout.") -> AIProviderError:
    return AIProviderError(
        message, category="timeout", retryable=True
    )


def provider_rate_limit(message: str = "Simulated rate limit.") -> AIProviderError:
    return AIProviderError(
        message, category="rate_limit", retryable=True, status_code=429
    )


def provider_auth_failure(message: str = "Simulated authentication failure.") -> AIProviderError:
    return AIProviderError(
        message, category="authentication_error", status_code=401
    )


def provider_unavailable(message: str = "Simulated provider outage.") -> AIProviderError:
    return AIProviderError(
        message, category="provider_unavailable", retryable=True, status_code=503
    )
