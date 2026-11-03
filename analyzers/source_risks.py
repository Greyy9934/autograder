"""Targeted, cautious C source-risk checks and structural counts."""
# Module role: Implements the source risks subsystem used by the AutoGrader workflow.

import re
from typing import Any

from analyzers.complexity_estimator import (
    FUNCTION_PATTERN,
    LOOP_HEADER_PATTERN,
    _brace_body,
    _mask_comments_and_strings,
)


# Function role: Report actionable source patterns; ordinary constructs are not alarms.
# Direct call references (conditional/branch-dependent): add.
def analyze_source_risks(source: str) -> dict[str, Any]:
    """Report actionable source patterns; ordinary constructs are not alarms."""
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "findings": [], "count": 0, "metrics": {}}

    masked = _mask_comments_and_strings(source)
    original_lines = source.splitlines()
    masked_lines = masked.splitlines()
    findings: list[dict[str, Any]] = []

    # Function role: Adds one validated finding/case/issue to the result being assembled by analyze_source_risks.
    # Context: method/helper owned by analyze_source_risks; it is reached through that object's workflow.
    # Same-file callers: analyze_source_risks.
    def add(rule_id: str, line: int, severity: str, message: str) -> None:
        evidence = original_lines[line - 1].strip()[:240] if 0 < line <= len(original_lines) else ""
        findings.append({
            "rule_id": rule_id,
            "line": line,
            "severity": severity,
            "evidence": evidence,
            "message": message,
            "confirmed_bug": False,
        })

    # Generic indexing, loops, arithmetic and malloc calls are not defects.
    # Report only patterns with a concrete safety concern.
    risky_calls = {
        "gets": ("high", "gets() cannot limit input to the destination size."),
        "strcpy": ("medium", "strcpy() does not verify destination capacity."),
        "strcat": ("medium", "strcat() does not verify remaining destination capacity."),
        "sprintf": ("medium", "sprintf() does not limit output to the destination size."),
    }
    for line, code in enumerate(masked_lines, 1):
        for name, (severity, message) in risky_calls.items():
            if re.search(r"\b" + name + r"\s*\(", code):
                add("unsafe_buffer_operation", line, severity, message)

    for match in re.finditer(r"\bscanf\s*\(", masked):
        remainder = source[match.end():]
        format_match = re.search(r'\s*"((?:\\.|[^"\\])*)"', remainder)
        if not format_match:
            continue
        conversions = re.findall(r"%(?!%)([-+ #0]*\d*)s", format_match.group(1))
        if any(not re.search(r"\d", width) for width in conversions):
            add(
                "unbounded_string_input",
                masked.count("\n", 0, match.start()) + 1,
                "high",
                "scanf %s conversion has no field width; input may exceed the destination buffer.",
            )

    for match in LOOP_HEADER_PATTERN.finditer(masked):
        if match.group(1) != "for":
            continue
        parts = [part.strip() for part in match.group(2).split(";")]
        if len(parts) != 3:
            continue
        variable_match = re.search(r"(?:[A-Za-z_]\w*\s+)*([A-Za-z_]\w*)\s*=", parts[0])
        variable = variable_match.group(1) if variable_match else None
        if not variable or not re.search(
            rf"\b{re.escape(variable)}\s*<=\s*(?:n|m|len|size|count)\b", parts[1], re.I
        ):
            continue
        body = _brace_body(masked, match.end())
        if re.search(rf"\b[A-Za-z_]\w*\s*\[[^\]]*\b{re.escape(variable)}\b[^\]]*\]", body):
            add(
                "possible_off_by_one",
                masked.count("\n", 0, match.start()) + 1,
                "medium",
                "The loop includes its input-size bound and indexes an array with the loop variable; verify the final index is valid.",
            )

    function_names = [
        match.group(1) for match in FUNCTION_PATTERN.finditer(masked)
        if match.group(1) not in {"if", "for", "while", "switch"}
    ]
    metrics = {
        "function_names": function_names,
        "function_count": len(set(function_names)),
        "loop_count": len(LOOP_HEADER_PATTERN.findall(masked)),
        "indexed_access_count": len(re.findall(r"\b[A-Za-z_]\w*\s*\[[^\]\n]+\]", masked)),
        "dynamic_allocation_count": len(re.findall(r"\b(?:malloc|calloc|realloc)\s*\(", masked)),
        "input_call_count": len(re.findall(r"\b(?:scanf|fscanf|getchar|fgets)\s*\(", masked)),
    }
    findings = list({(item["rule_id"], item["line"]): item for item in findings}.values())
    return {
        "status": "completed",
        "findings": findings,
        "count": len(findings),
        "metrics": metrics,
        "summary": (
            f"{len(findings)} targeted safety concern(s) need review."
            if findings else "No high-signal unsafe-input or obvious boundary pattern was detected."
        ),
        "message": "Ordinary loops, array accesses and arithmetic are summarized as structure; they are not reported as defects.",
        "limitations": [
            "Source-pattern checks can miss defects and do not prove safety.",
            "Compiler diagnostics and runtime memory checks provide separate evidence.",
        ],
    }
