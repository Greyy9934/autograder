"""Hard resource limits for schema-valid local test generation."""

MAX_GENERATED_CASE_INPUT_BYTES = 16 * 1024
MAX_GENERATED_BATCH_INPUT_BYTES = 512 * 1024
MAX_AGENT3A_GENERATOR_OUTPUT_BYTES = 1024 * 1024
MAX_GENERATED_ARRAY_LENGTH = 512


def max_generated_array_length(schema) -> int | None:
    """Return a conservative per-length-field cap for a schema's arrays."""
    fields = getattr(schema, "fields", ())
    arrays = [field for field in fields if field.get("type") == "int_array"]
    if not arrays:
        return None
    # A signed 32-bit value plus a separator needs at most 12 bytes.
    per_array_cap = max(
        1,
        (MAX_GENERATED_CASE_INPUT_BYTES - 256)
        // (12 * max(1, len(arrays))),
    )
    return min(MAX_GENERATED_ARRAY_LENGTH, per_array_cap)
