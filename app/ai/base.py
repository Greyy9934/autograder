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
        # In-function documentation:
        # Parameters:
        #   - message: the message value used by this operation (type annotation: str).
        #   - category: the category value used by this operation (type annotation: str).
        #   - retryable: the retryable value used by this operation (type annotation: bool).
        #   - status_code: status or result code interpreted by this function (type annotation: int | None).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: no value (None); work is performed through side effects or validation.
        # Flow: delegate work to a helper or external boundary; derive or store intermediate values.
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
        # In-function documentation:
        # Parameters:
        #   - task: the task value used by this operation (type annotation: str).
        #   - payload: the request data being sent across an API/provider boundary (type annotation: dict[str, Any]).
        #   - schema: declared data contract inputs or results must satisfy (type annotation: dict[str, Any]).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type dict[str, Any].
        ...
