"""Deterministic, heuristic code-quality analysis for C submissions."""
# Module role: Implements the code quality subsystem used by the AutoGrader workflow.

import re
from typing import Any

from app.ai.output_budget import TASK_CODE_QUALITY


# Function role: Implements analyze code quality for code quality using this module's input and result contracts.
# Direct call references (conditional/branch-dependent): add.
def analyze_code_quality(source: str) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_input",
            "score": None,
            "findings": [],
            "limitations": ["Non-empty C source is required."],
        }

    findings: list[dict[str, str]] = []

    # Function role: Adds one validated finding/case/issue to the result being assembled by analyze_code_quality.
    # Context: method/helper owned by analyze_code_quality; it is reached through that object's workflow.
    # Same-file callers: analyze_code_quality.
    def add(rule: str, severity: str, message: str) -> None:
        findings.append({
            "rule": rule,
            "severity": severity,
            "message": message,
        })

    clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    clean = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', clean)

    if not re.search(r"\bint\s+main\s*\(", clean):
        add("missing_main", "high", "No standard int main function was detected.")

    unsafe_functions = {
        "gets": "gets() is unsafe; use bounded input handling.",
        "strcpy": "strcpy() does not check destination capacity.",
        "sprintf": "sprintf() does not check destination capacity.",
        "scanf": "Check scanf() return values and bound string conversions.",
    }
    for name, message in unsafe_functions.items():
        if re.search(r"\b" + name + r"\s*\(", clean):
            add("unsafe_" + name, "medium", message)

    if re.search(r"\b(?:malloc|calloc|realloc)\s*\(", clean):
        if not re.search(r"\bfree\s*\(", clean):
            add("possible_unreleased_allocation", "medium",
                "Dynamic allocation detected without a visible free() call.")

    if re.search(r"\b(?:int|char|float|double)\s+\w+\s*\[[^\]]*\]", clean):
        if re.search(r"\b(?:scanf|gets)\s*\(", clean):
            add("array_input_review", "medium",
                "Array input handling detected; verify all input bounds.")

    lines = source.splitlines()
    long_lines = sum(1 for line in lines if len(line) > 120)
    if long_lines:
        add("long_lines", "low",
            f"{long_lines} line(s) exceed 120 characters.")

    function_count = len(re.findall(
        r"\b(?:void|int|char|float|double|long)\s+\w+\s*\([^;{}]*\)\s*\{",
        clean,
    ))
    if function_count <= 1:
        add("limited_function_decomposition", "low",
            "Only one or no function definitions were detected.")

    comment_count = len(re.findall(r"/\*|//", source))
    if len(clean.splitlines()) >= 30 and comment_count == 0:
        add("no_comments", "low",
            "No source comments were detected in a file of 30+ lines.")

    weights = {"high": 20, "medium": 10, "low": 3}
    score = max(0, 100 - sum(weights[item["severity"]] for item in findings))

    return {
        "status": "completed",
        "score": score,
        "score_type": "heuristic_code_quality_indicator",
        "finding_count": len(findings),
        "findings": findings,
        "metrics": {
            "source_lines": len(lines),
            "function_count_estimate": function_count,
            "long_lines": long_lines,
        },
        "limitations": [
            "This is heuristic static analysis, not a compiler or formal code review.",
            "Pattern matching may produce false positives and false negatives.",
            "The score is not a correctness score and must not be used alone for grading.",
        ],
    }


# AI-led Agent 6 review. The deterministic analyzer above remains available
# for legacy diagnostics; it is not the final code-quality assessment.
CODE_QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 500},
        "strengths": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 180}},
        "findings": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "maxLength": 80},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low", "info"],
                    },
                    "title": {"type": "string", "maxLength": 100},
                    "description": {"type": "string", "maxLength": 320},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "evidence": {"type": "string", "maxLength": 512},
                    "impact": {"type": "string", "maxLength": 220},
                    "recommendation": {"type": "string", "maxLength": 220},
                },
                "required": [
                    "category", "severity", "title", "description",
                    "line_start", "line_end", "evidence", "impact",
                    "recommendation",
                ],
            },
        },
        "rubric_ratings": {
            "type": "object",
            "properties": {
                name: {
                    "type": "object",
                    "properties": {
                        "rating": {"type": "integer", "minimum": 0, "maximum": 4},
                        "rationale": {"type": "string", "maxLength": 220},
                        "evidence": {"type": "array", "maxItems": 2, "items": {
                            "type": "object",
                            "properties": {"line": {"type": "integer", "minimum": 1}, "quote": {"type": "string", "maxLength": 180}},
                            "required": ["line", "quote"],
                        }},
                    },
                    "required": ["rating", "rationale", "evidence"],
                } for name in ("readability", "modularity", "design_originality")
            },
            "required": ["readability", "modularity", "design_originality"],
        },
        "limitations": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 220}},
    },
    "required": ["summary", "strengths", "findings", "rubric_ratings", "limitations"],
}


# Function role: Run the AI-led final code-quality review and validate cited evidence.
# Numbered workflow order: 06.2c - Agent 6 source-cited maintainability and readability review.
def review_code_quality(
    source: str,
    provider: Any,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the AI-led final code-quality review and validate cited evidence."""
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_input",
            "review_type": "ai_led",
            "summary": "A non-empty source file is required.",
            "strengths": [],
            "findings": [],
            "rubric_ratings": {},
            "limitations": ["No source code was available for review."],
        }
    if provider is None:
        return {
            "status": "skipped",
            "review_type": "ai_led",
            "summary": "The AI review was not run because no provider is configured.",
            "strengths": [],
            "findings": [],
            "rubric_ratings": {},
            "limitations": ["Configure an AI provider to run Agent 6."],
        }

    from app.ai.base import AIProviderError

    approved_context = context or {}
    approved_problem = approved_context.get("approved_problem") if isinstance(approved_context, dict) else None
    if isinstance(approved_problem, dict) and approved_problem.get("output_format"):
        from analyzers.output_contract import output_contract
        try:
            approved_context = dict(approved_context)
            approved_context["approved_io_contract"] = {
                key: approved_problem.get(key)
                for key in ("problem_statement", "input_format", "output_format", "input_schema", "constraints")
            }
            approved_context["approved_io_contract"]["output_contract"] = output_contract(approved_problem["output_format"])
        except ValueError as exc:
            return {"status": "invalid_request", "review_type": "ai_led", "summary": "The approved output contract is invalid.", "strengths": [], "findings": [], "rubric_ratings": {}, "limitations": [str(exc)]}
    payload = {
        "submitted_source_code": source,
        "approved_problem_context": approved_context,
        "instructions": (
            "Review only meaningful readability, modularity, maintainability, and C "
            "practice issues. Return at most three genuine strengths and five actionable "
            "findings. Each finding needs exact verbatim source evidence, 1-based lines, "
            "impact, and a concise fix. Rate readability, modularity, and design originality "
            "from 0-4; cite up to two short exact lines per rating. Do not infer correctness "
            "or complexity, invent issues, repeat the code, or add generic praise. Use an "
            "empty findings list when appropriate. Keep every field concise."
        ),
    }
    try:
        response = provider.generate_json(
            task=TASK_CODE_QUALITY,
            payload=payload,
            schema=CODE_QUALITY_SCHEMA,
        )
    except AIProviderError as exc:
        return {
            "status": "provider_error",
            "review_type": "ai_led",
            "summary": "Agent 6 could not complete its AI review.",
            "strengths": [],
            "findings": [],
            "rubric_ratings": {},
            "limitations": [str(exc)],
        }

    if not isinstance(response, dict):
        return {
            "status": "inconclusive",
            "review_type": "ai_led",
            "summary": "The provider returned an invalid review structure.",
            "strengths": [],
            "findings": [],
            "rubric_ratings": {},
            "limitations": ["AI response did not match the expected schema."],
        }

    lines = source.splitlines()
    valid_ratings = {}
    rubric = response.get("rubric_ratings")
    rubric_errors = []
    if not isinstance(rubric, dict):
        rubric_errors.append("Rubric ratings were missing or malformed.")
    else:
        for dimension in ("readability", "modularity", "design_originality"):
            item = rubric.get(dimension)
            valid = isinstance(item, dict)
            rating = item.get("rating") if valid else None
            refs = item.get("evidence") if valid else None
            if isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 4 or not isinstance(refs, list) or not refs:
                valid = False
            checked_refs = []
            if valid:
                for ref in refs:
                    line = ref.get("line") if isinstance(ref, dict) else None
                    quote = ref.get("quote") if isinstance(ref, dict) else None
                    if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(lines) or not isinstance(quote, str) or not quote.strip() or quote != lines[line - 1].strip():
                        valid = False
                        break
                    checked_refs.append({"line": line, "quote": quote})
            if valid and isinstance(item.get("rationale"), str) and item["rationale"].strip():
                valid_ratings[dimension] = {"rating": rating, "rationale": item["rationale"].strip(), "evidence": checked_refs}
            else:
                rubric_errors.append(f"{dimension} rating omitted: rating or exact line evidence failed validation.")
    lines = source.splitlines()
    valid_findings = []
    rejected = 0
    for item in response.get("findings", []):
        if not isinstance(item, dict):
            rejected += 1
            continue
        start, end = item.get("line_start"), item.get("line_end")
        evidence = item.get("evidence")
        if (
            not isinstance(start, int) or not isinstance(end, int)
            or start < 1 or end < start or end > len(lines)
            or not isinstance(evidence, str) or not evidence.strip()
            or evidence not in "\n".join(lines[start - 1:end])
        ):
            rejected += 1
            continue
        valid_findings.append({
            **item,
            "rule": item.get("category", "code_quality"),
            "message": item.get("description", ""),
            "source_location": {"line_start": start, "line_end": end},
        })

    limitations = list(response.get("limitations", []))
    limitations.extend(rubric_errors)
    if rejected:
        limitations.append(
            f"{rejected} finding(s) were omitted because their source evidence "
            "or line references could not be validated."
        )
    return {
        "status": "completed",
        "review_type": "ai_led",
        "summary": str(response.get("summary", "")),
        "strengths": response.get("strengths", []),
        "rubric_ratings": valid_ratings,
        "finding_count": len(valid_findings),
        "findings": valid_findings,
        "limitations": limitations,
        "formally_verified": False,
    }
