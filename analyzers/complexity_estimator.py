"""Conservative heuristic estimates of C source complexity."""

import re
from typing import Any


def estimate_complexity(source: str) -> dict[str, Any]:
    """Estimate complexity from source patterns; not a semantic proof."""
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "time_complexity": "unknown",
            "space_complexity": "unknown",
            "findings": [],
        }

    lines = source.splitlines()
    findings = []

    loop_pattern = re.compile(r"\b(for|while)\s*\(")
    loops = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        for match in loop_pattern.finditer(line):
            loops.append((number, match.group(1), stripped[:240]))

    # Approximate nesting by brace depth at each loop declaration.
    brace_depth = 0
    loop_depths = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        for match in loop_pattern.finditer(line):
            loop_depths.append((number, brace_depth, match.group(1), stripped[:240]))

        # This intentionally simple brace count is only a heuristic.
        brace_depth += line.count("{") - line.count("}")
        brace_depth = max(brace_depth, 0)

    max_loop_depth = 0
    for index, (line_number, depth, kind, evidence) in enumerate(loop_depths):
        # Loops declared at deeper brace nesting may be nested, but functions
        # and conditionals also increase brace depth; do not call this proof.
        nesting = 1 + sum(
            1 for _, earlier_depth, _, _ in loop_depths[:index]
            if earlier_depth < depth
        )
        max_loop_depth = max(max_loop_depth, min(nesting, len(loop_depths)))
        findings.append({
            "rule_id": "loop_pattern",
            "line": line_number,
            "evidence": evidence,
            "message": f"{kind} loop detected; inspect its bounds and nesting.",
        })

    recursive_functions = []
    function_pattern = re.compile(
        r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
    )
    for index, line in enumerate(lines):
        match = function_pattern.search(line)
        if not match:
            continue
        name = match.group(1)
        # Inspect a bounded function-like region; braces and declarations
        # are not parsed, so recursion detection can be incomplete.
        depth = 0
        started = False
        body = []
        for candidate_line in lines[index:]:
            body.append(candidate_line)
            depth += candidate_line.count("{") - candidate_line.count("}")
            started = started or "{" in candidate_line
            if started and depth <= 0:
                break
        if re.search(r"\b" + re.escape(name) + r"\s*\(", "\n".join(body[1:])):
            recursive_functions.append(name)

    allocation_lines = [
        (number, line.strip()[:240])
        for number, line in enumerate(lines, start=1)
        if re.search(r"\b(?:malloc|calloc|realloc)\s*\(", line)
        and not line.strip().startswith("//")
    ]

    if not loops and not recursive_functions:
        time_estimate = "O(1) candidate; verify called functions and input-dependent work"
    elif recursive_functions:
        time_estimate = "unknown; recursion detected, recurrence not inferred"
    elif max_loop_depth >= 2:
        time_estimate = (
            "possibly polynomial; nested loops detected, but bounds and "
            "relationships are not inferred"
        )
    else:
        time_estimate = (
            "possibly O(n) or another input-dependent bound; loop bounds "
            "are not inferred"
        )

    if allocation_lines:
        space_estimate = (
            "dynamic allocation detected; asymptotic space cannot be inferred "
            "reliably from these patterns"
        )
    else:
        space_estimate = (
            "unknown; no obvious dynamic allocation detected, but stack and "
            "input-dependent storage may exist"
        )

    for number, evidence in allocation_lines:
        findings.append({
            "rule_id": "dynamic_allocation",
            "line": number,
            "evidence": evidence,
            "message": "Dynamic allocation found; inspect allocation size and lifetime.",
        })

    return {
        "status": "completed",
        "time_complexity": time_estimate,
        "space_complexity": space_estimate,
        "loop_count": len(loops),
        "max_loop_depth_estimate": max_loop_depth,
        "recursive_functions": sorted(set(recursive_functions)),
        "dynamic_allocation_count": len(allocation_lines),
        "findings": findings,
        "message": (
            "These are source-pattern estimates, not measured runtime or "
            "proven asymptotic bounds."
        ),
        "limitations": [
            "C syntax and control flow are not fully parsed.",
            "Loop bounds and input-size relationships are not derived.",
            "Recursion detection and brace-based nesting can be wrong.",
            "Called functions, macros, compiler optimization, and data structure behavior are not modeled.",
            "Empirical timing and profiling are separate measurements.",
        ],
    }
