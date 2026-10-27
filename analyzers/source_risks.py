"""Heuristic C-source risk indicators with line-level evidence."""

import re
from typing import Any


def analyze_source_risks(source: str) -> dict[str, Any]:
    """Report suspicious source patterns, not definitive correctness claims."""
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "findings": [],
            "count": 0,
        }

    findings = []

    patterns = [
        (
            "array_indexing",
            re.compile(r"\b\w+\s*\[[^\]]+\]"),
            "Array indexing found; check index bounds and array length.",
            "low",
        ),
        (
            "unbounded_input",
            re.compile(r"\b(?:gets|scanf)\s*\("),
            "Input operation found; verify buffer sizes and input conversions.",
            "medium",
        ),
        (
            "integer_division",
            re.compile(r"(?<!/)/(?!/|=)"),
            "Division operator found; check zero divisors and integer truncation.",
            "low",
        ),
        (
            "signed_arithmetic",
            re.compile(r"\b(?:int|long|short)\b[^;\n]*[+\-*]"),
            "Integer arithmetic may overflow; verify type ranges and constraints.",
            "low",
        ),
        (
            "loop",
            re.compile(r"\b(?:for|while)\s*\("),
            "Loop found; inspect termination and boundary conditions.",
            "low",
        ),
        (
            "allocation",
            re.compile(r"\b(?:malloc|calloc|realloc)\s*\("),
            "Dynamic allocation found; check failure handling and allocation size.",
            "medium",
        ),
        (
            "manual_memory_management",
            re.compile(r"\b(?:free|memcpy|memmove|strcpy|strncpy)\s*\("),
            "Memory-management or copying operation found; inspect sizes and lifetimes.",
            "medium",
        ),
    ]

    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        for rule_id, pattern, message, severity in patterns:
            if pattern.search(line):
                findings.append({
                    "rule_id": rule_id,
                    "line": line_number,
                    "severity": severity,
                    "evidence": stripped[:240],
                    "message": message,
                    "confirmed_bug": False,
                })

    return {
        "status": "completed",
        "findings": findings,
        "count": len(findings),
        "message": (
            "Findings are heuristic risk indicators. Review source context "
            "and use tests or runtime diagnostics before concluding a bug exists."
        ),
        "limitations": [
            "Regular expressions do not parse C syntax or understand control flow.",
            "Comments, macros, multiline expressions, and complex types can cause misses or false positives.",
            "A reported pattern does not establish a defect.",
        ],
    }
