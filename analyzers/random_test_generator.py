"""Reproducible random test generation bound to confirmed specifications."""

import random
from typing import Any, Callable

from analyzers.assignment_spec import AssignmentSpec


InputGenerator = Callable[[random.Random, AssignmentSpec, str], str]
InputValidator = Callable[[str, AssignmentSpec], bool]


def generate_random_test_batch(
    spec: AssignmentSpec,
    *,
    seed: int,
    count: int,
    input_generator: InputGenerator,
    input_validator: InputValidator,
    distribution: str = "uniform",
) -> dict[str, Any]:
    """Generate and validate a deterministic batch using an explicit format adapter."""

    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {
            "status": "rejected",
            "reason": "A confirmed assignment specification is required.",
            "inputs": [],
        }

    if isinstance(seed, bool) or not isinstance(seed, int):
        return {"status": "invalid_request", "inputs": []}

    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        return {"status": "invalid_request", "inputs": []}

    if not callable(input_generator) or not callable(input_validator):
        return {"status": "invalid_request", "inputs": []}

    allowed_distributions = {
        "uniform",
        "boundary_biased",
        "duplicate_heavy",
        "sorted",
        "reverse_sorted",
    }
    if distribution not in allowed_distributions:
        return {"status": "invalid_request", "inputs": []}

    rng = random.Random(seed)
    inputs = []

    try:
        for index in range(count):
            generated = input_generator(rng, spec, distribution)

            if not isinstance(generated, str):
                raise ValueError(f"Generated input {index + 1} is not text.")

            if not input_validator(generated, spec):
                return {
                    "status": "validation_failed",
                    "seed": seed,
                    "spec_fingerprint": spec.fingerprint(),
                    "inputs": inputs,
                    "rejected_case": index + 1,
                    "message": "Generated input failed assignment validation.",
                }

            inputs.append(generated)

    except Exception as exc:
        return {
            "status": "generator_error",
            "seed": seed,
            "spec_fingerprint": spec.fingerprint(),
            "inputs": inputs,
            "message": str(exc),
        }

    return {
        "status": "generated",
        "seed": seed,
        "distribution": distribution,
        "count": len(inputs),
        "inputs": inputs,
        "spec_fingerprint": spec.fingerprint(),
        "reproducible": True,
        "limitations": [
            "Input validity depends on the supplied assignment-specific validator.",
            "Random test generation does not establish program correctness.",
        ],
    }


def generate_schema_test_batch(
    spec: AssignmentSpec,
    *,
    schema,
    seed: int,
    count: int,
    distribution: str = "uniform",
) -> dict[str, Any]:
    """Generate tests using an explicit integer input schema."""
    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {
            "status": "rejected",
            "reason": "A confirmed assignment specification is required.",
            "inputs": [],
        }

    from analyzers.input_schema import IntegerInputSchema

    if not isinstance(schema, IntegerInputSchema):
        return {"status": "invalid_request", "inputs": []}

    return generate_random_test_batch(
        spec,
        seed=seed,
        count=count,
        distribution=distribution,
        input_generator=lambda rng, _spec, mode: schema.generate(rng, mode),
        input_validator=lambda text, _spec: schema.validate(text),
    )
