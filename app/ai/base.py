"""Shared contract for all AutoGrader AI providers."""

from typing import Any, Protocol


class AIProviderError(RuntimeError):
    """A provider failed or returned unusable output."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


class AIProvider(Protocol):
    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate one structured JSON object."""
        ...
