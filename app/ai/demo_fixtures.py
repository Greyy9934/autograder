"""Isolated, clearly labelled AutoGrader demo fixtures.

These examples are synthetic. They never inspect submissions, invoke an AI
provider, compile code, or execute programs.
"""
# Module role: Implements the demo fixtures subsystem used by the AutoGrader workflow.
from copy import deepcopy
from random import SystemRandom

_rng = SystemRandom()

_FIXTURES = {
    "agent1": [
        {
            "status": "ready",
            "summary": "Simulated reconstruction: determine whether two distinct array elements sum to a target.",
            "problem_statement": "Given an integer array and a target, report whether two distinct elements sum to the target.",
            "input_schema": "n, followed by n integers and a target integer.",
            "constraints": ["Each element may be used at most once.", "Illustrative constraints only."],
            "clarifying_questions": [],
        },
        {
            "status": "needs_clarification",
            "summary": "Simulated ambiguity: the problem does not specify whether indices or a YES/NO result are required.",
            "problem_statement": "Find two values related to a target.",
            "input_schema": "Undetermined.",
            "constraints": [],
            "clarifying_questions": [
                "Can the same element be used twice?",
                "Should the output contain indices or only YES/NO?",
            ],
        },
        {
            "status": "ready_with_assumptions",
            "summary": "Simulated reconstruction with explicit assumptions and unresolved bounds.",
            "problem_statement": "Count the number of occurrences of a target value in an integer array.",
            "input_schema": "n, n integers, then target.",
            "constraints": ["Array length and integer bounds were not supplied."],
            "clarifying_questions": [],
        },
    ],
    "agent2": [
        {
            "status": "simulated",
            "problem_summary": "Two-sum decision problem.",
            "brute_force": {"algorithm": "Enumerate all distinct index pairs.", "time_complexity": "O(n^2)", "space_complexity": "O(1)"},
            "efficient": {"algorithm": "Sort and use two pointers.", "time_complexity": "O(n log n)", "space_complexity": "O(n)"},
            "limitations": ["Illustrative descriptions only; implementations are not compiled or validated."],
        },
        {
            "status": "simulated",
            "problem_summary": "Count target occurrences.",
            "brute_force": {"algorithm": "Scan every array element.", "time_complexity": "O(n)", "space_complexity": "O(1)"},
            "efficient": {"algorithm": "Frequency table, when the value range permits it.", "time_complexity": "O(n + k)", "space_complexity": "O(k)"},
            "limitations": ["The value range and memory constraints are unknown."],
        },
    ],
    "agent3a": [
        {
            "status": "simulated",
            "generator": "Illustrative progressive integer-array generator.",
            "input_distributions": ["uniform", "boundary-biased", "duplicate-heavy", "sorted", "reverse-sorted"],
            "benchmark": {
                "status": "simulated_not_measured",
                "deadline_seconds": 2,
                "shared_deadline": True,
                "series": [
                    {"input_size": 100, "student_runtime_seconds": 0.001, "brute_force_runtime_seconds": 0.002, "efficient_runtime_seconds": 0.001},
                    {"input_size": 500, "student_runtime_seconds": 0.004, "brute_force_runtime_seconds": 0.018, "efficient_runtime_seconds": 0.003},
                    {"input_size": 1000, "student_runtime_seconds": 0.009, "brute_force_runtime_seconds": 0.071, "efficient_runtime_seconds": 0.007},
                ],
                "note": "All values are fabricated for interface demonstration; no program was run.",
            },
        },
        {
            "status": "simulated_warning",
            "generator": "Illustrative boundary-focused generator.",
            "input_distributions": ["minimum", "maximum", "repeated values", "alternating extremes"],
            "benchmark": {
                "status": "simulated_timeout_example",
                "deadline_seconds": 2,
                "shared_deadline": True,
                "series": [
                    {"input_size": 100, "student_runtime_seconds": 0.002, "brute_force_runtime_seconds": 0.006, "efficient_runtime_seconds": 0.002},
                    {"input_size": 500, "student_runtime_seconds": 0.014, "brute_force_runtime_seconds": None, "efficient_runtime_seconds": 0.005},
                ],
                "timeouts": ["Brute-force example marked as a simulated timeout."],
                "note": "No timing or timeout was actually measured.",
            },
        },
    ],
    "agent3b": [
        {
            "status": "simulated",
            "edge_cases": [
                {"name": "empty array", "stdin": "0\n5\n", "rationale": "Checks minimum-length handling.", "expected_output": "NO"},
                {"name": "duplicate values", "stdin": "4\n3 3 3 3\n6\n", "rationale": "Checks whether two distinct positions can be used.", "expected_output": "YES"},
                {"name": "negative values", "stdin": "3\n-8 2 5\n-3\n", "rationale": "Checks negative-number handling.", "expected_output": "YES"},
            ],
            "execution": "Not run; these are illustrative suggestions.",
        },
        {
            "status": "simulated_warning",
            "edge_cases": [
                {"name": "integer boundary", "stdin": "2\n2147483647 -2147483648\n-1\n", "rationale": "May expose overflow or type-width assumptions.", "expected_output": "YES"},
                {"name": "no matching pair", "stdin": "3\n1 2 4\n20\n", "rationale": "Checks the negative result path.", "expected_output": "NO"},
            ],
            "execution": "Not run; validate against the actual problem constraints.",
        },
    ],
    "agent4": [
        {"status": "simulated", "algorithm": "Nested pair enumeration", "time_complexity": {"best_case": "O(n^2)", "average_case": "O(n^2)", "worst_case": "O(n^2)"}, "space_complexity": "O(1)", "note": "Theoretical illustration, not a source-linked analysis."},
        {"status": "simulated", "algorithm": "Sort plus binary search", "time_complexity": {"best_case": "O(n log n)", "average_case": "O(n log n)", "worst_case": "O(n log n)"}, "space_complexity": "O(n)", "note": "Theoretical illustration, not a source-linked analysis."},
        {"status": "inconclusive", "algorithm": "Undetermined", "time_complexity": {"best_case": None, "average_case": None, "worst_case": None}, "space_complexity": "Undetermined", "note": "Simulated missing-evidence state."},
    ],
    "agent5": [
        {"outcome": "proof_sketch", "theorem": "Two-pointer search is correct on a sorted array.", "conclusion": "A proof sketch follows from the sorted-order pointer invariant.", "limitations": ["Not machine-checked; requires the sorted-input precondition."]},
        {"outcome": "counterexample_found", "theorem": "Two-pointer search is correct on every input order.", "counterexample": {"input": "3\n8 1 4\n5\n", "expected_behavior": "YES"}, "conclusion": "The universal claim fails when the input is not sorted."},
        {"outcome": "inconclusive", "theorem": "The submitted algorithm is correct for all valid inputs.", "conclusion": "Insufficient specification and implementation evidence to prove or disprove correctness."},
    ],
    "agent6": [
        {"status": "simulated_review", "summary": "Generally readable implementation with input-validation concerns.", "findings": [{"severity": "warning", "finding": "Input conversion return values are not checked.", "evidence": "Illustrative finding; no submitted source was inspected."}, {"severity": "info", "finding": "Consider separating parsing and algorithm logic.", "evidence": "General maintainability suggestion."}]},
        {"status": "simulated_review", "summary": "Potential integer-overflow and boundary-handling risks.", "findings": [{"severity": "high", "finding": "Intermediate arithmetic may exceed the chosen integer type.", "evidence": "Illustrative finding; not linked to source."}, {"severity": "warning", "finding": "Array bounds should be checked before indexing.", "evidence": "General defensive-programming recommendation."}]},
        {"status": "inconclusive", "summary": "Insufficient source evidence for a meaningful quality review.", "findings": [], "limitations": ["This is a simulated inconclusive state."]},
    ],
}


# Function role: Return independent random fixtures; never accepts user input.
def build_demo_payload():
    """Return independent random fixtures; never accepts user input."""
    # In-function documentation:
    # Parameters: none.
    # Returns: a structured mapping assembled for the caller.
    # Flow: derive or store intermediate values; return the stage result.
    selected = {
        agent: deepcopy(_rng.choice(variants))
        for agent, variants in _FIXTURES.items()
    }
    return {
        "simulation": True,
        "mode": "DEMO — SIMULATED DATA",
        "notice": (
            "Every result below is fabricated for interface demonstration. "
            "No submitted input was read, no AI provider was called, and no "
            "program was compiled or executed. Benchmark values are not measurements."
        ),
        "agents": selected,
        "pdf": {
            "available": True,
            "label": "SIMULATED DEMO REPORT",
            "note": "This demo payload is intended for a separately labelled mock PDF.",
        },
    }
