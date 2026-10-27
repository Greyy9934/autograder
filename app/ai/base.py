"""Shared contract for all AutoGrader AI providers."""

from typing import Any, Protocol


class AIProviderError(RuntimeError):
    """A provider failed or returned unusable output."""


class AIProvider(Protocol):
    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate one structured JSON object."""
        ...
