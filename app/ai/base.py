"""Shared contract for all AutoGrader AI providers."""
# In plain terms: This file handles base, one part of the AutoGrader’s workflow.

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
        # In simple terms: Sets up .
        # What the inputs mean:
        # - message: the message used for this step.
        # - category: the category used for this step.
        # - retryable: the retryable used for this step.
        # - status_code: the status code used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It does its work and does not return a value.
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
        # In simple terms: Generate one structured JSON object.
        # What the inputs mean:
        # - task: the task used for this step.
        # - payload: the information being sent to an AI service.
        # - schema: the schema used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns a set of named results for the next step.
        ...
