"""Source-informed adversarial test planning; does not execute or grade tests."""

import hashlib
import random
import re
from typing import Any

from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema


def plan_adversarial_tests(
    source: str,
    spec: AssignmentSpec,
    schema: IntegerInputSchema,
    *,
    seed: int = 0,
    max_cases: int = 30,
    static_findings: list[dict[str, Any]] | None = None,
    reference_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "cases": []}
    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {"status": "rejected", "reason": "Confirmed assignment specification required.", "cases": []}
    if not isinstance(schema, IntegerInputSchema):
        return {"status": "invalid_request", "cases": []}
    if isinstance(seed, bool) or not isinstance(seed, int):
        return {"status": "invalid_request", "cases": []}
    if isinstance(max_cases, bool) or not isinstance(max_cases, int) or not 1 <= max_cases <= 100:
        return {"status": "invalid_request", "cases": []}

    findings = static_findings if isinstance(static_findings, list) else []
    refs = reference_metadata if isinstance(reference_metadata, dict) else {}
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(text: str, reason: str, priority: str, trigger: str):
        if len(candidates) >= max_cases or not schema.validate(text):
            return
        normalized = " ".join(text.split())
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        candidates.append({
            "input": text,
            "reason": reason,
            "priority": priority,
            "source_trigger": trigger,
            "expected_output": None,
            "execution_status": "not_executed",
        })

    low, high = schema.minimum, schema.maximum
    boundary_values = list(dict.fromkeys((
        low, min(low + 1, high), 0 if low <= 0 <= high else low,
        max(high - 1, low), high,
    )))

    # Always include constraint boundaries and zero where valid.
    for value in boundary_values:
        add(" ".join([str(value)] * schema.token_count) + "\n",
            "Boundary value repeated across all input positions.",
            "high", "input_constraints")

    if schema.token_count >= 2:
        add(f"{low} {high}" + (" " + str(low) * (schema.token_count - 2) if schema.token_count > 2 else "") + "\n",
            "Mixed minimum and maximum values can expose ordering and overflow assumptions.",
            "high", "input_constraints")
        add(" ".join(map(str, range(schema.token_count))) + "\n",
            "Distinct increasing values can expose accidental order assumptions.",
            "medium", "input_structure")
        add(" ".join(map(str, range(schema.token_count - 1, -1, -1))) + "\n",
            "Decreasing values can expose accidental sorted-input assumptions.",
            "medium", "input_structure")

    patterns = [
        (r"\bfor\s*\(", "Loop boundary and off-by-one behavior.", "loop"),
        (r"\bwhile\s*\(", "Loop termination and boundary behavior.", "loop"),
        (r"\[[^\]]+\]", "Array indexing and size-boundary behavior.", "array"),
        (r"\b(?:malloc|calloc|realloc|free)\s*\(", "Memory allocation and empty/small-input behavior.", "memory"),
        (r"/|%", "Division or modulo with zero and negative values.", "arithmetic"),
        (r"\b(?:int|long|short)\b", "Integer-width and signed-boundary behavior.", "integer"),
        (r"\b(?:scanf|fgets|getchar)\b", "Input parsing and whitespace behavior.", "input"),
        (r"\b(?:if|else|switch)\b", "Branch boundaries and mutually exclusive paths.", "control_flow"),
    ]

    for pattern, reason, trigger in patterns:
        match = re.search(pattern, source)
        if match:
            line = source.count("\n", 0, match.start()) + 1
            add(schema.generate(rng, "boundary_biased"), reason,
                "high" if trigger in ("array", "arithmetic", "integer") else "medium",
                f"{trigger}:line_{line}")

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        category = str(finding.get("category", "static_finding"))
        severity = str(finding.get("severity", "unknown"))
        line = finding.get("line")
        add(schema.generate(rng, "boundary_biased"),
            f"Targeted test suggested by static finding: {category}.",
            "high" if severity.lower() in ("high", "critical") else "medium",
            f"static_finding:{category}:line_{line}")

    # Add seeded cases so each run is reproducible.
    while len(candidates) < max_cases and len(seen) < max_cases:
        mode = rng.choice(("uniform", "duplicate_heavy", "sorted", "reverse_sorted"))
        add(schema.generate(rng, mode),
            f"Seeded {mode.replace('_', ' ')} input for additional adversarial coverage.",
            "low", f"seeded:{mode}")
        if len(seen) >= max_cases:
            break

    oracle_scope = refs.get("oracle_scope", "failure_evidence_only")
    if oracle_scope not in ("failure_evidence_only", "correctness_judgment_allowed"):
        oracle_scope = "failure_evidence_only"

    return {
        "status": "planned",
        "seed": seed,
        "spec_fingerprint": spec.fingerprint(),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "case_count": len(candidates),
        "cases": candidates,
        "reference_oracle_scope": oracle_scope,
        "reference_validation_status": refs.get("validation_status", "not_provided"),
        "limitations": [
            "Static source patterns are heuristic and may produce irrelevant tests.",
            "No test has been executed and no expected output has been established.",
            "Reference solutions are not trusted unless independently validated.",
        ],
    }
