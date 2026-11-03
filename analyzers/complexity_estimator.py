"""Conservative static heuristics for C source complexity.

This module does not parse the full C language and never claims to prove
asymptotic complexity.
"""
# In plain terms: This file handles complexity estimator, one part of the AutoGrader’s workflow.

import re
from typing import Any


LOOP_PATTERN = re.compile(r"\b(for|while)\s*\(")
LOOP_HEADER_PATTERN = re.compile(r"\b(for|while)\s*\(([^()]*)\)")
INPUT_SIZE_NAMES = {"n", "m", "len", "length", "size", "count", "cities", "vertices"}
FUNCTION_PATTERN = re.compile(
    r"\b([A-Za-z_]\w*)\s*\([^;{}]{0,512}\)\s*\{"
)
ALLOCATION_PATTERN = re.compile(r"\b(malloc|calloc|realloc)\s*\(")


def _loop_model(kind: str, header: str, body: str = "") -> dict[str, Any]:
    """Classify common loop forms without claiming full C semantics."""
    # In simple terms: Classify common loop forms without claiming full C semantics.
    # What the inputs mean:
    # - kind: the kind used for this step.
    # - header: the header used for this step.
    # - body: the body used for this step.
    # What it gives back: It returns a set of named results for the next step.
    if kind == "for":
        parts = [part.strip() for part in header.split(";")]
        if len(parts) != 3:
            return {"model": "unknown", "variable": None, "bound": None}
        init, condition, step = parts
        variable_match = re.search(r"(?:[A-Za-z_]\w*\s+)*([A-Za-z_]\w*)\s*=", init)
        variable = variable_match.group(1) if variable_match else None
        bound_match = re.search(
            rf"\b{re.escape(variable or '')}\s*(?:<|<=|>|>=)\s*([A-Za-z_]\w*|\d+)",
            condition,
        ) if variable else None
        bound = bound_match.group(1) if bound_match else None
        input_bound = bool(bound and bound.lower() in INPUT_SIZE_NAMES)
        geometric = bool(variable and re.search(
            rf"(?:\b{re.escape(variable)}\s*\*=\s*[2-9]|\b{re.escape(variable)}\s*=\s*{re.escape(variable)}\s*\*\s*[2-9]|\b{re.escape(variable)}\s*>>=\s*1|\b{re.escape(variable)}\s*/=\s*2)",
            step,
        ))
        if geometric and input_bound:
            model = "logarithmic"
        elif bound and bound.isdigit():
            model = "constant"
        elif input_bound and variable and re.search(
            rf"(?:\+\+\s*{re.escape(variable)}|{re.escape(variable)}\s*\+\+|{re.escape(variable)}\s*\+=\s*\d+|--\s*{re.escape(variable)}|{re.escape(variable)}\s*--)",
            step,
        ):
            model = "linear"
        else:
            model = "unknown"
        return {"model": model, "variable": variable, "bound": bound}

    condition_match = re.search(
        r"\b([A-Za-z_]\w*)\s*(?:<|<=|>|>=)\s*([A-Za-z_]\w*|0|1)\b", header
    )
    variable = condition_match.group(1) if condition_match else None
    bound = condition_match.group(2) if condition_match else None
    input_bound = bool(
        (variable and variable.lower() in INPUT_SIZE_NAMES)
        or (bound and bound.lower() in INPUT_SIZE_NAMES)
    )
    update = body or ""
    if input_bound and re.search(rf"\b{re.escape(variable)}\s*(?:/=\s*2|>>=\s*1|=\s*{re.escape(variable)}\s*/\s*2)", update):
        model = "logarithmic"
    elif input_bound and re.search(rf"(?:--\s*{re.escape(variable)}|{re.escape(variable)}\s*--|{re.escape(variable)}\s*-?=\s*1)", update):
        model = "linear"
    else:
        model = "unknown"
    return {"model": model, "variable": variable, "bound": None}


def _brace_body(source: str, opening: int) -> str:
    """Return a brace-delimited loop body, if one is present."""
    # In simple terms: Return a brace-delimited loop body, if one is present.
    # What the inputs mean:
    # - source: the C code being checked.
    # - opening: the opening used for this step.
    # What it gives back: It returns text.
    brace = source.find("{", opening)
    semicolon = source.find(";", opening)
    if brace < 0 or (semicolon >= 0 and semicolon < brace):
        return ""
    depth = 0
    for position in range(brace, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:position]
    return source[brace + 1:]


def _mask_comments_and_strings(source: str) -> str:
    """Replace comments and string/character contents while preserving lines."""
    # In simple terms: Replace comments and string/character contents while preserving lines.
    # What the inputs mean:
    # - source: the C code being checked.
    # What it gives back: It returns text.
    result = []
    index = 0
    state = "code"

    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if state == "code":
            if char == "/" and next_char == "/":
                result.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and next_char == "*":
                result.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char == '"':
                result.append(" ")
                index += 1
                state = "string"
                continue
            if char == "'":
                result.append(" ")
                index += 1
                state = "character"
                continue

            result.append(char)
            index += 1
            continue

        if state == "line_comment":
            if char == "\n":
                result.append("\n")
                state = "code"
            else:
                result.append(" ")
            index += 1
            continue

        if state == "block_comment":
            if char == "*" and next_char == "/":
                result.extend("  ")
                index += 2
                state = "code"
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if state in {"string", "character"}:
            closing = '"' if state == "string" else "'"
            if char == "\\" and next_char:
                result.extend("\n" if c == "\n" else " " for c in (char, next_char))
                index += 2
            elif char == closing:
                result.append(" ")
                index += 1
                state = "code"
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1

    return "".join(result)


def _invalid_result() -> dict[str, Any]:
    # In simple terms: Helps with invalid result.
    # This function takes no named inputs.
    # What it gives back: It returns a set of named results for the next step.
    return {
        "status": "invalid_request",
        "time_complexity": "unknown",
        "space_complexity": "unknown",
        "loop_count": 0,
        "max_loop_depth_estimate": 0,
        "recursive_functions": [],
        "dynamic_allocation_count": 0,
        "findings": [],
        "analysis_type": "static_heuristic",
        "confidence": "none",
        "proof_status": "not_proven",
        "input_size_model": "not_inferred",
    }


def estimate_complexity(source: str) -> dict[str, Any]:
    """Estimate complexity from source patterns; not a semantic proof."""
    # In simple terms: Estimate complexity from source patterns; not a semantic proof.
    # What the inputs mean:
    # - source: the C code being checked.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(source, str) or not source.strip():
        return _invalid_result()

    masked = _mask_comments_and_strings(source)
    original_lines = source.splitlines()
    masked_lines = masked.splitlines()
    findings: list[dict[str, Any]] = []

    loops = []
    for match in LOOP_HEADER_PATTERN.finditer(masked):
        line_number = masked.count("\n", 0, match.start()) + 1
        body = _brace_body(masked, match.end()) if match.group(1) == "while" else ""
        model = _loop_model(match.group(1), match.group(2), body)
        original = original_lines[line_number - 1] if line_number <= len(original_lines) else ""
        loops.append({
            "line": line_number,
            "kind": match.group(1),
            "header": " ".join(match.group(2).split())[:180],
            "evidence": original.strip()[:240],
            **model,
        })

    # Track active loop brace scopes. This is more conservative than treating
    # every enclosing function/if/switch brace as a loop nesting level.
    active_loops: list[tuple[int, int]] = []
    brace_depth = 0
    loop_depths = []

    for number, (original, code) in enumerate(
        zip(original_lines, masked_lines), start=1
    ):
        # Remove loop scopes whose opening brace has already closed.
        active_loops = [
            item for item in active_loops if item[1] <= brace_depth
        ]

        matches = list(LOOP_PATTERN.finditer(code))
        for match in matches:
            depth = len(active_loops) + 1
            loop_depths.append(depth)

        # A loop body beginning on this line opens a new loop scope.
        # Single-statement loops and unusual formatting remain limitations.
        if matches and "{" in code:
            active_loops.append((number, brace_depth + 1))

        brace_depth += code.count("{") - code.count("}")
        brace_depth = max(brace_depth, 0)
        active_loops = [
            item for item in active_loops if item[1] <= brace_depth
        ]

    max_loop_depth = max(loop_depths, default=0)

    # Function bodies are found heuristically. Only inspect code with comments
    # and literals masked, avoiding recursion matches in quoted text.
    recursive_functions = []
    recursive_details = []
    for match in FUNCTION_PATTERN.finditer(masked):
        name = match.group(1)
        if name in {"if", "for", "while", "switch"}:
            continue
        opening = match.end() - 1
        depth = 0
        closing = None

        for position in range(opening, len(masked)):
            if masked[position] == "{":
                depth += 1
            elif masked[position] == "}":
                depth -= 1
                if depth == 0:
                    closing = position
                    break

        if closing is None:
            continue

        body = masked[opening + 1:closing]
        calls = list(re.finditer(r"\b" + re.escape(name) + r"\s*\(", body))
        if calls:
            recursive_functions.append(name)
            recursive_details.append({
                "function": name,
                "recursive_calls_per_body": len(calls),
                "inside_loop": bool(LOOP_HEADER_PATTERN.search(body)),
                "body": body,
            })

    allocation_lines = []
    for number, (original, code) in enumerate(
        zip(original_lines, masked_lines), start=1
    ):
        if ALLOCATION_PATTERN.search(code):
            allocation_lines.append((number, original.strip()[:240]))

    recursive_factorial = any(
        item["inside_loop"] and any(loop["model"] == "linear" for loop in loops)
        for item in recursive_details
    )
    recursive_exponential = any(item["recursive_calls_per_body"] >= 2 for item in recursive_details)
    recursive_linear = any(
        item["recursive_calls_per_body"] == 1
        and re.search(r"\b\w+\s*\(\s*\w+\s*-\s*1\s*\)", item["body"])
        for item in recursive_details
    )
    recursive_logarithmic = any(
        item["recursive_calls_per_body"] == 1
        and re.search(r"\b\w+\s*\(\s*\w+\s*(?:/\s*2|>>\s*1)\s*\)", item["body"])
        for item in recursive_details
    )
    linear_loops = [item for item in loops if item["model"] == "linear"]
    logarithmic_loops = [item for item in loops if item["model"] == "logarithmic"]
    fixed_loops = [item for item in loops if item["model"] == "constant"]
    if recursive_factorial:
        time_estimate = "O(n!) candidate; recursive branching inside an input-sized loop is consistent with permutation search"
    elif recursive_exponential:
        time_estimate = "O(2^n) candidate; multiple self-calls per recursive body suggest branching recursion"
    elif recursive_linear:
        time_estimate = "O(n) candidate; one recursive call reduces its argument by one"
    elif recursive_logarithmic:
        time_estimate = "O(log n) candidate; one recursive call halves its argument"
    elif max_loop_depth >= 2 and linear_loops:
        time_estimate = f"O(n^{max_loop_depth}) candidate; nested input-sized loops detected"
    elif linear_loops and logarithmic_loops:
        time_estimate = "O(n log n) candidate; input-sized and halving loops detected"
    elif linear_loops:
        time_estimate = "O(n) candidate; a loop bound is tied to an input-size variable"
    elif logarithmic_loops:
        time_estimate = "O(log n) candidate; a loop repeatedly halves an input-sized value"
    elif loops and len(fixed_loops) == len(loops):
        time_estimate = "O(1) candidate; detected loop bounds are numeric constants"
    elif not loops and not recursive_functions:
        time_estimate = "O(1) candidate; no input-sized loop or direct recursion was recognized"
    else:
        time_estimate = "unknown; loop bounds or recursive recurrence were not recognized"

    loop_analysis = [
        {
            "line": item["line"],
            "kind": item["kind"],
            "header": item["header"],
            "model": item["model"],
            "variable": item["variable"],
            "bound": item["bound"],
            "evidence": item["evidence"],
        }
        for item in loops
    ]
    summary = time_estimate
    if loops or recursive_functions:
        summary += f". Found {len(loops)} loop(s) and {len(recursive_functions)} recursive function(s)."

    dynamic_size = re.search(
        r"\b(?:malloc|calloc|realloc)\s*\(([^;)]{1,180})\)", masked
    )
    vla = re.search(
        r"\b(?:char|short|int|long|float|double)\s+\w+\s*\[\s*(?:n|m|len|size|count)\s*\]", masked,
        re.IGNORECASE,
    )
    if recursive_functions:
        space_estimate = "O(n) candidate; recursive calls retain an input-dependent stack of frames"
    elif dynamic_size and re.search(r"\b(?:n|m|len|size|count)\b", dynamic_size.group(1), re.IGNORECASE):
        space_estimate = (
            "O(n^2) candidate; allocation size contains two input-sized factors"
            if dynamic_size.group(1).count("*") >= 2
            else "O(n) candidate; allocation size depends on an input-sized value"
        )
    elif vla:
        space_estimate = "O(n) candidate; a variable-length array uses an input-sized bound"
    elif allocation_lines:
        space_estimate = "dynamic allocation detected; its size expression was not recognized"
    else:
        space_estimate = "O(1) auxiliary-space candidate; no input-sized allocation or recursion was recognized"

    function_names = [
        match.group(1) for match in FUNCTION_PATTERN.finditer(masked)
        if match.group(1) not in {"if", "for", "while", "switch"}
    ]
    array_access_count = len(re.findall(r"\b[A-Za-z_]\w*\s*\[[^\]\n]+\]", masked))
    input_calls = len(re.findall(r"\b(?:scanf|fscanf|getchar|fgets)\s*\(", masked))

    return {
        "status": "completed",
        "time_complexity": time_estimate,
        "space_complexity": space_estimate,
        "summary": summary,
        "loop_analysis": loop_analysis,
        "recursive_analysis": [
            {
                "function": item["function"],
                "self_calls": item["recursive_calls_per_body"],
                "recursive_call_inside_loop": item["inside_loop"],
                "inference": (
                    "branching recursion candidate" if item["recursive_calls_per_body"] >= 2
                    else "linear-depth recursion candidate" if item["inside_loop"]
                    else "recurrence shape needs review"
                ),
            }
            for item in recursive_details
        ],
        "program_structure": {
            "function_names": function_names,
            "loop_count": len(loops),
            "maximum_brace_scoped_loop_depth": max_loop_depth,
            "array_access_count": array_access_count,
            "input_call_count": input_calls,
            "recursive_functions": sorted(set(recursive_functions)),
        },
        "loop_count": len(loops),
        "max_loop_depth_estimate": max_loop_depth,
        "recursive_functions": sorted(set(recursive_functions)),
        "dynamic_allocation_count": len(allocation_lines),
        "findings": findings,
        "analysis_type": "static_heuristic",
        "confidence": "low",
        "proof_status": "not_proven",
        "input_size_model": "not_inferred",
        "message": (
            "These are conservative source-pattern estimates, not measured "
            "runtime or proven asymptotic bounds."
        ),
        "limitations": [
            "C syntax and control flow are not fully parsed.",
            "Comments and string/character literals are excluded from pattern detection.",
            "Loop bounds and input-size relationships are not derived.",
            "Loop nesting is a brace-scope heuristic and can be wrong, especially for single-statement loops.",
            "Recursion detection is heuristic and may miss indirect or unusual recursion.",
            "Called functions, macros, compiler optimization, and data structure behavior are not modeled.",
            "Stack usage, variable-length arrays, and allocation-size relationships are not fully analyzed.",
            "Empirical timing and profiling are separate measurements.",
        ],
    }
