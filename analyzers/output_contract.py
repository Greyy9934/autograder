"""Canonical output-format contract and stdout normalization policy."""
# This file handles output contract as one part of the app.

OUTPUT_COMPARISON_RULE = (
    "Normalize CRLF to LF; ignore trailing spaces on each line and final newline; "
    "preserve line order, line count, leading spaces, and internal spacing."
)


def output_contract(output_format: str) -> dict:
    # Turns the agreed answer format into simple rules for comparing program output.
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
    # Turns the approved answer description into the rules used to compare program output.
    # What the inputs mean:
    # - value: the particular value being checked or changed.
    # What it gives back: It returns text.
    if not isinstance(value, str):
        raise TypeError("stdout must be text.")
    return "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).rstrip("\n")
