"""Immutable, explicitly confirmed assignment specifications."""

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class AssignmentSpec:
    problem_id: str
    title: str
    problem_statement: str
    constraints: tuple[str, ...]
    input_format: str
    output_format: str
    time_limit_seconds: float | None = None
    memory_limit_mb: int | None = None
    version: int = 1
    confirmed: bool = False

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
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object.")

        return cls(
            problem_id=candidate.get("id", ""),
            title=candidate.get("title", ""),
            problem_statement=candidate.get("problem_statement", ""),
            constraints=tuple(formats.pop("constraints", ())),
            input_format=formats.pop("input_format", ""),
            output_format=formats.pop("output_format", ""),
            **formats,
            confirmed=False,
        )

    def confirm(self, *, instructor_approved: bool):
        if instructor_approved is not True:
            raise ValueError("Explicit instructor approval is required.")

        values = asdict(self)
        values["confirmed"] = True
        return AssignmentSpec(**values)

    def canonical_json(self) -> str:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
