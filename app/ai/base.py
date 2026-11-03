"""Shared contract for all AutoGrader AI providers."""
# Module role: Implements the base subsystem used by the AutoGrader workflow.

from typing import Any, Protocol


class AIProviderError(RuntimeError):
    """A provider failed or returned unusable output."""

    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by AIProviderError; it is reached through that object's workflow.
    # Same-file callers: __init__.
    # Direct call references (conditional/branch-dependent): __init__.
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
    # Function role: Generate one structured JSON object.
    # Context: method/helper owned by AIProvider; it is reached through that object's workflow.
    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate one structured JSON object."""
        ...
