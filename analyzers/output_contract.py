"""Canonical output-format contract and stdout normalization policy."""
# In plain terms: This file handles output contract, one part of the AutoGrader’s workflow.

OUTPUT_COMPARISON_RULE = (
    "Normalize CRLF to LF; ignore trailing spaces on each line and final newline; "
    "preserve line order, line count, leading spaces, and internal spacing."
)


def output_contract(output_format: str) -> dict:
    # In simple terms: Helps with output contract.
    # What the inputs mean:
    # - output_format: how the program’s answer is expected to look.
    # What it gives back: It returns the dict result.
    if not isinstance(output_format, str) or not output_format.strip():
        raise ValueError("A non-empty approved output_format is required.")
    return {
        "format": output_format,
        "representation": "stdout_text",
        "comparison_rule": OUTPUT_COMPARISON_RULE,
        "stdout_policy": "Print only the specified answer; no prompts, labels, or diagnostics.",
    }


def normalize_stdout(value: str) -> str:
    # In simple terms: Cleans up stdout.
    # What the inputs mean:
    # - value: the particular value being checked or changed.
    # What it gives back: It returns text.
    if not isinstance(value, str):
        raise TypeError("stdout must be text.")
    return "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).rstrip("\n")
