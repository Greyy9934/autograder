"""Propose edge cases without assuming undocumented input constraints."""

from typing import Any


def analyze_edge_cases(problem: dict[str, Any]) -> dict[str, Any]:
    """Return test ideas classified by how strongly constraints support them."""
    if not isinstance(problem, dict):
        return {
            "status": "invalid_request",
            "cases": [],
            "message": "Problem must be a structured object.",
        }

    statement = problem.get("problem_statement")
    if not isinstance(statement, str) or not statement.strip():
        return {
            "status": "invalid_request",
            "cases": [],
            "message": "A selected problem statement is required.",
        }

    constraints = problem.get("constraints")
    if not isinstance(constraints, list):
        constraints = []

    constraint_text = " ".join(
        item.lower() for item in constraints if isinstance(item, str)
    )
    statement_text = statement.lower()
    evidence_text = f"{statement_text} {constraint_text}"

    cases = []

    def add(case_id: str, idea: str, condition: str, category: str) -> None:
        cases.append({
            "id": case_id,
            "idea": idea,
            "condition": condition,
            "category": category,
            "concrete_input": None,
            "reason": (
                "This analyzer proposes test ideas; concrete input generation "
                "requires a known input format."
            ),
        })

    # These are ideas only. No input is fabricated from a guessed grammar.
    add(
        "minimum_size",
        "Smallest permitted input",
        "Minimum input size or lower bound must be known.",
        "applicable" if any(
            token in evidence_text
            for token in ("n >= 1", "n≥1", "minimum", "at least one")
        ) else "needs_clarification",
    )

    add(
        "maximum_size",
        "Largest permitted input",
        "Maximum input size and resource limits must be known.",
        "applicable" if any(
            token in evidence_text
            for token in ("maximum", "n <=", "n≤", "up to")
        ) else "needs_clarification",
    )

    add(
        "empty_input",
        "Empty input or empty collection",
        "Only applicable if empty input is allowed by the problem.",
        "conditional",
    )

    add(
        "singleton",
        "Input containing one element",
        "Only applicable if the input format permits a one-element collection.",
        "conditional",
    )

    add(
        "duplicates",
        "Repeated equal values",
        "Only applicable if duplicates are permitted and relevant.",
        "conditional",
    )

    add(
        "ordering",
        "Already sorted and reverse-sorted values",
        "Only applicable to problems where input order matters.",
        "conditional",
    )

    add(
        "numeric_boundaries",
        "Values at documented numeric bounds",
        "Numeric type, bounds, and overflow behavior must be established.",
        "applicable" if any(
            token in evidence_text
            for token in ("int", "integer", "10^", "1e", "overflow", "range")
        ) else "needs_clarification",
    )

    add(
        "termination",
        "Input that stresses loop termination and progress",
        "Requires identifying loops and their input-dependent conditions.",
        "conditional",
    )

    needs_clarification = any(
        item["category"] == "needs_clarification" for item in cases
    )

    return {
        "status": "needs_clarification" if needs_clarification else "ready",
        "cases": cases,
        "count": len(cases),
        "concrete_inputs_generated": False,
        "message": (
            "Some constraints need clarification before these ideas can "
            "be converted into valid test inputs."
            if needs_clarification
            else "Candidate edge-case ideas generated; input validity must "
                 "still be checked."
        ),
        "limitations": [
            "Keyword matching is a preliminary heuristic, not semantic proof.",
            "These are test ideas, not executable inputs.",
            "A valid edge case depends on the selected problem's input contract.",
        ],
    }
