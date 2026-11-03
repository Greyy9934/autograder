"""Provider-independent validation and safety boundary for AI agents."""
# This file handles guardrails as one part of the app.

import json
import os
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from app.ai.base import AIProviderError


class GuardedProvider:
    """Validate all AI inputs and outputs before they enter the application."""

    def __init__(self, provider: Any) -> None:
        # Helps with init inside init.
        # What the inputs mean:
        # - provider: the selected AI service.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It does its work and does not return a value.
        self.provider = provider
        self.max_payload_bytes = int(
            os.getenv("AUTOGRADER_AI_MAX_PAYLOAD_BYTES", "1048576")
        )
        self.max_schema_bytes = 131072
        self.max_task_chars = 12000

        if not 1024 <= self.max_payload_bytes <= 4194304:
            raise AIProviderError(
                "AI payload limit must be between 1 KB and 4 MB.",
                category="configuration_error",
            )

    @staticmethod
    def _encode(value: Any, label: str) -> bytes:
        # Helps with encode inside encode.
        # What the inputs mean:
        # - value: the particular value being checked or changed.
        # - label: the label used for this step.
        # What it gives back: It returns the bytes result.
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise AIProviderError(
                f"{label} must contain finite, JSON-serializable data.",
                category="invalid_input",
            ) from exc

    def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        # Creates json.
        # What the inputs mean:
        # - task: the task used for this step.
        # - payload: the information being sent to an AI service.
        # - schema: the schema used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns a set of named results for the next step.
        if not isinstance(task, str) or not task.strip():
            raise AIProviderError(
                "AI task must be a non-empty string.",
                category="invalid_input",
            )

        if len(task) > self.max_task_chars:
            raise AIProviderError(
                "AI task exceeds the configured length limit.",
                category="input_too_large",
            )

        if not isinstance(payload, dict) or not isinstance(schema, dict):
            raise AIProviderError(
                "AI payload and schema must be JSON objects.",
                category="invalid_input",
            )

        payload_bytes = self._encode(payload, "AI payload")
        schema_bytes = self._encode(schema, "AI schema")

        if len(payload_bytes) > self.max_payload_bytes:
            raise AIProviderError(
                "AI payload exceeds the configured size limit.",
                category="input_too_large",
            )

        if len(schema_bytes) > self.max_schema_bytes:
            raise AIProviderError(
                "AI schema exceeds the configured size limit.",
                category="invalid_schema",
            )

        try:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
        except SchemaError as exc:
            raise AIProviderError(
                "The requested AI output schema is invalid.",
                category="invalid_schema",
            ) from exc

        # The task is application-authored. Payload content is data only.
        # Provider implementations must preserve this separation in their
        # system instructions; this wrapper independently validates output.
        result = self.provider.generate_json(task, payload, schema)

        if not isinstance(result, dict):
            raise AIProviderError(
                "AI provider returned a non-object response.",
                category="invalid_response",
            )

        result_bytes = self._encode(result, "AI response")
        if len(result_bytes) > self.max_payload_bytes:
            raise AIProviderError(
                "AI response exceeds the configured size limit.",
                category="invalid_response",
            )

        errors = list(validator.iter_errors(result))
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.absolute_path)
            raise AIProviderError(
                "AI response failed schema validation"
                + (f" at {location}." if location else "."),
                category="schema_validation_error",
            )

        return result
