"""Coordinate Agent 3A and Agent 3B using a confirmed assignment."""

from typing import Any

from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema
from analyzers.random_test_generator import generate_schema_test_batch
from analyzers.adversarial_test_planner import plan_adversarial_tests


def generate_test_plans(
    source: str,
    spec: AssignmentSpec,
    schema: IntegerInputSchema,
    *,
    random_seed: int = 42,
    random_count: int = 50,
    random_distribution: str = "uniform",
    adversarial_seed: int = 43,
    adversarial_count: int = 30,
    static_findings: list[dict[str, Any]] | None = None,
    reference_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate random and adversarial inputs without executing student code."""

    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {
            "status": "rejected",
            "reason": "Instructor-confirmed assignment specification required.",
            "random_tests": None,
            "adversarial_tests": None,
        }

    if not isinstance(schema, IntegerInputSchema):
        return {
            "status": "invalid_request",
            "reason": "An explicit integer input schema is required.",
            "random_tests": None,
            "adversarial_tests": None,
        }

    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "reason": "Non-empty student source is required.",
            "random_tests": None,
            "adversarial_tests": None,
        }

    random_tests = generate_schema_test_batch(
        spec,
        schema=schema,
        seed=random_seed,
        count=random_count,
        distribution=random_distribution,
    )

    adversarial_tests = plan_adversarial_tests(
        source,
        spec,
        schema,
        seed=adversarial_seed,
        max_cases=adversarial_count,
        static_findings=static_findings,
        reference_metadata=reference_metadata,
    )

    return {
        "status": (
            "generated"
            if random_tests.get("status") == "generated"
            and adversarial_tests.get("status") == "planned"
            else "partial_or_failed"
        ),
        "spec_fingerprint": spec.fingerprint(),
        "source_sha256": __import__("hashlib").sha256(
            source.encode("utf-8")
        ).hexdigest(),
        "random_tests": random_tests,
        "adversarial_tests": adversarial_tests,
        "execution_performed": False,
        "limitations": [
            "Input schema must be explicitly supplied and validated against the assignment.",
            "Generated inputs have not been executed.",
            "Generation does not establish program correctness.",
        ],
    }
