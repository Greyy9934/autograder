"""Immutable, explicitly confirmed assignment specifications."""
# Module role: Models the instructor-reviewed assignment contract and canonical fingerprint passed between stages.

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from analyzers.structured_input_schema import StructuredIntegerInputSchema


@dataclass(frozen=True)
class AssignmentSpec:
    problem_id: str
    title: str
    problem_statement: str
    constraints: tuple[str, ...]
    input_format: str
    output_format: str
    input_schema: Any = None
    time_limit_seconds: float | None = None
    memory_limit_mb: int | None = None
    version: int = 1
    confirmed: bool = False

    # Function role: Validates the constructed data object's invariants and canonicalizes supported fields.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): to_dict.
    def __post_init__(self):
        for field in (
            "problem_id",
            "title",
            "problem_statement",
            "input_format",
            "output_format",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be non-empty text.")

        if not isinstance(self.constraints, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.constraints
        ):
            raise ValueError("constraints must be a tuple of non-empty strings.")

        if self.input_schema is not None:
            try:
                raw_schema = (
                    json.loads(self.input_schema)
                    if isinstance(self.input_schema, str)
                    else self.input_schema
                )
                parsed_schema = StructuredIntegerInputSchema.from_dict(raw_schema)
                canonical_schema = json.dumps(
                    parsed_schema.to_dict(), sort_keys=True, separators=(",", ":")
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"input_schema is invalid: {exc}") from exc
            object.__setattr__(self, "input_schema", canonical_schema)

        if self.time_limit_seconds is not None and (
            isinstance(self.time_limit_seconds, bool)
            or not isinstance(self.time_limit_seconds, (int, float))
            or self.time_limit_seconds <= 0
        ):
            raise ValueError("time_limit_seconds must be positive.")

        if self.memory_limit_mb is not None and (
            isinstance(self.memory_limit_mb, bool)
            or not isinstance(self.memory_limit_mb, int)
            or self.memory_limit_mb <= 0
        ):
            raise ValueError("memory_limit_mb must be a positive integer.")

        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be a positive integer.")

        if not isinstance(self.confirmed, bool):
            raise ValueError("confirmed must be boolean.")

    # Function role: Constructs draft with the module's required invariants.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    @classmethod
    def create_draft(cls, candidate: dict[str, Any], **formats):
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object.")

        return cls(
            problem_id=candidate.get("id", ""),
            title=candidate.get("title", ""),
            problem_statement=candidate.get("problem_statement", ""),
            constraints=tuple(formats.pop("constraints", ())),
            input_format=formats.pop("input_format", ""),
            output_format=formats.pop("output_format", ""),
            input_schema=formats.pop("input_schema", candidate.get("input_schema")),
            **formats,
            confirmed=False,
        )

    # Function role: Returns a confirmed immutable specification only after explicit instructor approval.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): to_dict.
    def confirm(self, *, instructor_approved: bool):
        if instructor_approved is not True:
            raise ValueError("Explicit instructor approval is required.")

        values = self.to_dict()
        values["confirmed"] = True
        return AssignmentSpec(**values)

    # Function role: Produces deterministic JSON with stable key ordering for identity and comparison.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    # Same-file callers: fingerprint.
    # Direct call references (conditional/branch-dependent): to_dict.
    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    # Function role: Hashes the canonical representation so downstream steps can detect specification changes.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): canonical_json.
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    # Function role: Serializes the internal model to the stable plain-dictionary shape used by API and persistence boundaries.
    # Context: method/helper owned by AssignmentSpec; it is reached through that object's workflow.
    # Same-file callers: __post_init__, confirm, canonical_json.
    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        if values["input_schema"] is not None:
            values["input_schema"] = json.loads(values["input_schema"])
        return values
