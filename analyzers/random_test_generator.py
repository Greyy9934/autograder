"""Reproducible random test generation bound to confirmed specifications."""
# In plain terms: This file handles random test generator, one part of the AutoGrader’s workflow.

import random
from typing import Any, Callable

from analyzers.assignment_spec import AssignmentSpec
from analyzers.workload_limits import (
    MAX_GENERATED_BATCH_INPUT_BYTES,
    MAX_GENERATED_CASE_INPUT_BYTES,
    max_generated_array_length,
)


InputGenerator = Callable[[random.Random, AssignmentSpec, str], str]
InputValidator = Callable[[str, AssignmentSpec], bool]


def generate_random_test_batch(
    spec: AssignmentSpec,
    *,
    seed: int,
    count: int,
    input_generator: InputGenerator,
    input_validator: InputValidator,
    schema=None,
    distribution: str = "uniform",
) -> dict[str, Any]:
    """Generate and validate a deterministic batch using an explicit format adapter."""
    # In simple terms: Generate and validate a deterministic batch using an explicit format adapter.
    # What the inputs mean:
    # - spec: the settings or assignment details used here.
    # - seed: the starting number that makes random test generation repeatable.
    # - count: how many items or runs are requested.
    # - input_generator: the input generator used for this step.
    # - input_validator: the input validator used for this step.
    # - schema: the schema used for this step.
    # - distribution: the way random values should be chosen.
    # What it gives back: It returns a set of named results for the next step.

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
    total_input_bytes = 0
    generated_size_cap = None

    from analyzers.structured_input_schema import StructuredIntegerInputSchema
    if isinstance(schema, StructuredIntegerInputSchema):
        generated_size_cap = max_generated_array_length(schema)

    try:
        for index in range(count):
            if generated_size_cap is not None and isinstance(
                schema, StructuredIntegerInputSchema
            ):
                generated = schema.generate(
                    rng, distribution, max_array_length=generated_size_cap
                )
            else:
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

            input_bytes = len(generated.encode("utf-8"))
            if input_bytes > MAX_GENERATED_CASE_INPUT_BYTES:
                break
            if total_input_bytes + input_bytes > MAX_GENERATED_BATCH_INPUT_BYTES:
                break

            inputs.append(generated)
            total_input_bytes += input_bytes

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
        "requested_count": count,
        "shortfall_count": max(0, count - len(inputs)),
        "coverage_status": "complete" if len(inputs) == count else "partial",
        "total_input_bytes": total_input_bytes,
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
    # In simple terms: Generate tests using an explicit integer input schema.
    # What the inputs mean:
    # - spec: the settings or assignment details used here.
    # - schema: the schema used for this step.
    # - seed: the starting number that makes random test generation repeatable.
    # - count: how many items or runs are requested.
    # - distribution: the way random values should be chosen.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {
            "status": "rejected",
            "reason": "A confirmed assignment specification is required.",
            "inputs": [],
        }

    from analyzers.input_schema import IntegerInputSchema
    from analyzers.structured_input_schema import StructuredIntegerInputSchema

    if not isinstance(schema, (IntegerInputSchema, StructuredIntegerInputSchema)):
        return {"status": "invalid_request", "inputs": []}

    return generate_random_test_batch(
        spec,
        seed=seed,
        count=count,
        distribution=distribution,
        input_generator=lambda rng, _spec, mode: schema.generate(rng, mode),
        input_validator=lambda text, _spec: schema.validate(text),
        schema=schema,
    )
