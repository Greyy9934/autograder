"""Immutable, explicitly confirmed assignment specifications."""
# In plain terms: This file holds the version of the assignment that the instructor reviewed and approved.

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

    def __post_init__(self):
        # In simple terms: Checks the new object .
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
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

    @classmethod
    def create_draft(cls, candidate: dict[str, Any], **formats):
        # In simple terms: Creates draft.
        # What the inputs mean:
        # - candidate: the candidate used for this step.
        # - formats: the formats used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
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

    def confirm(self, *, instructor_approved: bool):
        # In simple terms: Helps with confirm.
        # What the inputs mean:
        # - instructor_approved: the instructor approved used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        if instructor_approved is not True:
            raise ValueError("Explicit instructor approval is required.")

        values = self.to_dict()
        values["confirmed"] = True
        return AssignmentSpec(**values)

    def canonical_json(self) -> str:
        # In simple terms: Marks the reviewed assignment as approved and returns that approved copy.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns text.
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    def fingerprint(self) -> str:
        # In simple terms: Writes the assignment details in one consistent order so they can be compared reliably.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns text.
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        # In simple terms: Creates a short identity mark from the assignment details.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns a set of named results for the next step.
        values = asdict(self)
        if values["input_schema"] is not None:
            values["input_schema"] = json.loads(values["input_schema"])
        return values
