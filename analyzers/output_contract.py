"""Canonical output-format contract and stdout normalization policy."""
# Module role: Implements the output contract subsystem used by the AutoGrader workflow.

OUTPUT_COMPARISON_RULE = (
    "Normalize CRLF to LF; ignore trailing spaces on each line and final newline; "
    "preserve line order, line count, leading spaces, and internal spacing."
)


# Function role: Implements output contract for output contract using this module's input and result contracts.
def output_contract(output_format: str) -> dict:
    if not isinstance(output_format, str) or not output_format.strip():
        raise ValueError("A non-empty approved output_format is required.")
    return {
        "format": output_format,
        "representation": "stdout_text",
        "comparison_rule": OUTPUT_COMPARISON_RULE,
        "stdout_policy": "Print only the specified answer; no prompts, labels, or diagnostics.",
    }


# Function role: Canonicalizes only the allowed output differences (CRLF and trailing spaces/newline) while preserving line order, count, leading spaces, and internal spacing.
def normalize_stdout(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("stdout must be text.")
    return "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).rstrip("\n")
