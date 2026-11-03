"""Hard resource limits for schema-valid local test generation."""
# Module role: Implements the workload limits subsystem used by the AutoGrader workflow.

MAX_GENERATED_CASE_INPUT_BYTES = 16 * 1024
MAX_GENERATED_BATCH_INPUT_BYTES = 512 * 1024
MAX_AGENT3A_GENERATOR_OUTPUT_BYTES = 1024 * 1024
MAX_GENERATED_ARRAY_LENGTH = 512


# Function role: Return a conservative per-length-field cap for a schema's arrays.
def max_generated_array_length(schema) -> int | None:
    """Return a conservative per-length-field cap for a schema's arrays."""
    # In-function documentation:
    # Parameters:
    #   - schema: declared data contract inputs or results must satisfy.
    # Returns: a value of declared type int | None.
    # Flow: derive or store intermediate values; branch on validation or workflow conditions.
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
