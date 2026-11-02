"""Realistic, deterministic offline scenarios for provider-backed agents."""

from copy import deepcopy

from analyzers.problem_reconstruction import RECONSTRUCTION_SCHEMA
from analyzers.reference_solutions import REFERENCE_SCHEMA
from analyzers.mathematical_verification import VERIFICATION_SCHEMA
from analyzers.complexity_analysis import COMPLEXITY_ANALYSIS_SCHEMA


SCENARIOS = {
    "agent1": {
        "ready": {
            "status": "ready",
            "candidates": [{
                "id": "two-sum",
                "title": "Find Two Numbers with a Target Sum",
                "problem_statement": (
                    "Given an integer array and a target, determine whether "
                    "two distinct elements sum to the target."
                ),
                "input_format": "An integer n, followed by n integers and a target integer.",
                "output_format": "Print YES if a valid pair exists; otherwise print NO.",
                "input_schema": {
                    "version": 1,
                    "fields": [
                        {"name": "n", "type": "int", "min": 0, "max": 1000},
                        {"name": "values", "type": "int_array", "length_from": "n", "min": -1000000, "max": 1000000},
                        {"name": "target", "type": "int", "min": -2000000, "max": 2000000},
                    ],
                    "size_field": "values",
                },
                "evidence": ["scanf reads n, then n integers, then the target."],
                "assumptions": ["Each array element may be used at most once."],
                "confidence": 0.96,
            }],
            "clarifying_questions": [],
            "constraints": ["Array length is non-negative."],
            "limitations": ["Exact numeric bounds were not supplied."],
        },
        "needs_clarification": {
            "status": "needs_clarification",
            "candidates": [],
            "clarifying_questions": [
                "Can the same array element be used twice?",
                "Should the output be YES/NO or the matching indices?",
            ],
            "constraints": [],
            "limitations": ["The available description does not define output behavior."],
        },
    },
    "agent2": {
        "reference_solutions": {
            "problem_summary": "Determine whether two distinct array elements sum to a target.",
            "assumptions": ["Each element can be used at most once."],
            "limitations": [
                "The generated implementations require validation against the confirmed input constraints.",
                "Neither implementation is approved as a trusted test oracle until independently validated.",
            ],
            "brute_force": {
                "algorithm": "Check every pair of distinct indices.",
                "code": (
                    "#include <stdio.h>\n"
                    "int main(void) {\n"
                    "    int n, target, a[1000];\n"
                    "    if (scanf(\"%d\", &n) != 1) return 1;\n"
                    "    for (int i = 0; i < n; i++) scanf(\"%d\", &a[i]);\n"
                    "    scanf(\"%d\", &target);\n"
                    "    for (int i = 0; i < n; i++)\n"
                    "        for (int j = i + 1; j < n; j++)\n"
                    "            if (a[i] + a[j] == target) { puts(\"YES\"); return 0; }\n"
                    "    puts(\"NO\");\n"
                    "    return 0;\n"
                    "}\n"
                ),
                "time_complexity": "O(n^2)",
                "space_complexity": "O(n)",
                "limitations": ["The fixed array requires an input-size bound."],
            },
            "efficient": {
                "algorithm": "Sort the values and use two pointers.",
                "code": (
                    "#include <stdio.h>\n"
                    "#include <stdlib.h>\n"
                    "int cmp(const void *a, const void *b) {\n"
                    "    int x = *(const int *)a, y = *(const int *)b;\n"
                    "    return (x > y) - (x < y);\n"
                    "}\n"
                    "int main(void) {\n"
                    "    int n, target, a[1000];\n"
                    "    if (scanf(\"%d\", &n) != 1) return 1;\n"
                    "    for (int i = 0; i < n; i++) scanf(\"%d\", &a[i]);\n"
                    "    scanf(\"%d\", &target);\n"
                    "    qsort(a, n, sizeof(int), cmp);\n"
                    "    int i = 0, j = n - 1;\n"
                    "    while (i < j) {\n"
                    "        long long sum = (long long)a[i] + a[j];\n"
                    "        if (sum == target) { puts(\"YES\"); return 0; }\n"
                    "        if (sum < target) i++; else j--;\n"
                    "    }\n"
                    "    puts(\"NO\");\n"
                    "    return 0;\n"
                    "}\n"
                ),
                "time_complexity": "O(n log n)",
                "space_complexity": "O(n), including sorting storage if required by the implementation.",
                "limitations": ["The fixed array requires an input-size bound."],
            },
        },
    },
    "agent5": {
        "counterexample": {
            "outcome": "counterexample_found",
            "theorem": "The submitted two-pointer algorithm returns the correct pair-sum result for every valid input.",
            "preconditions": ["The input contains integers and a target sum."],
            "postconditions": ["The algorithm reports whether a pair sums to the target."],
            "assumptions": ["The input array is not guaranteed to be sorted."],
            "proof_strategy": "Disprove the universal claim with a concrete counterexample.",
            "proof_steps": [{
                "claim": "The two-pointer movement rule is not valid on an unsorted array.",
                "justification": "Pointer elimination relies on sorted order, which the input does not guarantee.",
                "equation": "a[left] + a[right] < target does not imply that a[left] can be discarded when the array is unsorted.",
            }],
            "conclusion": "The algorithm is not established as correct for all valid inputs.",
            "counterexample": {
                "input": "3\\n8 1 4\\n5\\n",
                "expected_behavior": "YES",
                "observed_or_predicted_behavior": "The submitted pointer strategy may report NO.",
                "explanation": "The pair 1 and 4 sums to 5, but pointer movement on unsorted input is invalid.",
            },
            "limitations": ["This reasoning-based counterexample still requires execution against the submitted implementation."],
        },
        "proof_sketch": {
            "outcome": "proof_sketch",
            "theorem": "For a sorted array, the two-pointer algorithm correctly determines whether a pair sums to the target.",
            "preconditions": ["The array is sorted in nondecreasing order."],
            "postconditions": ["The algorithm returns YES exactly when a valid pair exists."],
            "assumptions": ["Array comparisons and additions are correct and do not overflow."],
            "proof_strategy": "Maintain the invariant that any undiscovered valid pair lies within the current pointer interval.",
            "proof_steps": [
                {
                    "claim": "If the current sum is too small, the left value cannot form a valid pair with any remaining right-side value.",
                    "justification": "The array is sorted, so all remaining values are at most the current right value.",
                    "equation": "a[left] + a[right] < target",
                },
                {
                    "claim": "If the current sum is too large, the right value cannot form a valid pair with any remaining left-side value.",
                    "justification": "The array is sorted, so all remaining values are at least the current left value.",
                    "equation": "a[left] + a[right] > target",
                },
                {
                    "claim": "When the pointers meet, no undiscovered pair remains.",
                    "justification": "Each pointer movement eliminates only values that cannot participate in a valid pair.",
                    "equation": "left >= right",
                },
            ],
            "conclusion": "Under the stated preconditions, the pointer eliminations preserve the invariant and the algorithm returns the correct result.",
            "counterexample": None,
            "limitations": ["This is a proof sketch, not machine-checked formal verification.", "Input parsing and integer overflow require separate validation."],
        },
        "inconclusive": {
            "outcome": "inconclusive",
            "theorem": "The submitted algorithm correctly solves the specified problem.",
            "preconditions": ["The approved problem specification and complete algorithm behavior are available."],
            "postconditions": ["The algorithm produces the required output for every valid input."],
            "assumptions": [],
            "proof_strategy": "A proof cannot be completed without establishing the algorithm's required preconditions.",
            "proof_steps": [],
            "conclusion": "There is insufficient evidence to prove or disprove correctness.",
            "counterexample": None,
            "limitations": ["The sorting precondition is unknown.", "No complete mathematical proof or concrete counterexample is available."],
        },
    },

    "agent4": {
        "linear_scan": {
            "status": "analyzed",
            "algorithm": {
                "name": "Linear scan",
                "description": "Visits each input element once.",
                "input_size_model": "n is the number of array elements.",
            },
            "time_complexity": {
                "best_case": "O(1)",
                "average_case": "O(n)",
                "worst_case": "O(n)",
                "derivation": "The loop performs at most n iterations; an early match can terminate the scan.",
            },
            "space_complexity": {
                "auxiliary": "O(1)",
                "total": "O(1)",
                "derivation": "Only a fixed number of scalar variables are used.",
            },
            "evidence": [
                {"line_start": 3, "line_end": 5, "claim": "The loop advances the index once per iteration until n.", "role": "input-dependent loop"},
            ],
            "assumptions": ["Array access and comparison take constant time."],
            "confidence": 0.96,
            "limitations": [],
            "unresolved_questions": [],
        },
        "nested_loops": {
            "status": "analyzed",
            "algorithm": {
                "name": "Pair enumeration",
                "description": "Compares each element with the remaining elements.",
                "input_size_model": "n is the number of input elements.",
            },
            "time_complexity": {
                "best_case": "O(n^2)",
                "average_case": "O(n^2)",
                "worst_case": "O(n^2)",
                "derivation": "The nested loops enumerate a quadratic number of index pairs.",
            },
            "space_complexity": {
                "auxiliary": "O(1)",
                "total": "O(1)",
                "derivation": "The loops use a fixed number of index variables.",
            },
            "evidence": [
                {"line_start": 3, "line_end": 5, "claim": "The inner loop executes for a number of iterations proportional to the remaining input.", "role": "nested input-dependent loops"},
            ],
            "assumptions": ["The loop bounds depend on n as shown."],
            "confidence": 0.94,
            "limitations": [],
            "unresolved_questions": [],
        },
        "recursive_divide_and_conquer": {
            "status": "analyzed",
            "algorithm": {
                "name": "Binary recursive search",
                "description": "Halves the remaining search interval at each recursive call.",
                "input_size_model": "n is the size of the current search interval.",
            },
            "time_complexity": {
                "best_case": "O(1)",
                "average_case": "O(log n)",
                "worst_case": "O(log n)",
                "derivation": "Each call reduces the interval by approximately half, giving logarithmic recursion depth.",
            },
            "space_complexity": {
                "auxiliary": "O(log n)",
                "total": "O(log n)",
                "derivation": "The recursion stack contains one frame per level.",
            },
            "evidence": [
                {"line_start": 3, "line_end": 5, "claim": "The recursive call receives an interval approximately half the previous size.", "role": "recursive reduction"},
            ],
            "assumptions": ["The interval reduction and base case are implemented correctly."],
            "confidence": 0.91,
            "limitations": ["The recurrence depends on the actual recursive arguments."],
            "unresolved_questions": [],
        },
        "sorting": {
            "status": "analyzed",
            "algorithm": {
                "name": "Comparison sorting",
                "description": "Sorts n elements using a comparison-based sorting routine.",
                "input_size_model": "n is the number of elements sorted.",
            },
            "time_complexity": {
                "best_case": "O(n log n)",
                "average_case": "O(n log n)",
                "worst_case": "O(n log n)",
                "derivation": "Assumes the selected sorting implementation provides this bound.",
            },
            "space_complexity": {
                "auxiliary": "O(n)",
                "total": "O(n)",
                "derivation": "The implementation may use linear auxiliary storage.",
            },
            "evidence": [
                {"line_start": 3, "line_end": 5, "claim": "The source invokes a library sorting routine on n elements.", "role": "sorting operation"},
            ],
            "assumptions": ["The library routine has the stated complexity guarantee."],
            "confidence": 0.83,
            "limitations": ["The exact library implementation and version may affect guarantees."],
            "unresolved_questions": ["Which sorting implementation is used at runtime?"],
        },
        "inconclusive": {
            "status": "inconclusive",
            "algorithm": {
                "name": "Undetermined",
                "description": "The available source does not establish the algorithm.",
                "input_size_model": "The relevant input-size parameter cannot be identified.",
            },
            "time_complexity": {
                "best_case": None,
                "average_case": None,
                "worst_case": None,
                "derivation": "Insufficient source context to derive a defensible bound.",
            },
            "space_complexity": {
                "auxiliary": None,
                "total": None,
                "derivation": "Memory behaviour cannot be determined from the available source.",
            },
            "evidence": [],
            "assumptions": [],
            "confidence": 0.12,
            "limitations": ["The source is incomplete."],
            "unresolved_questions": ["What are the missing function definitions?"],
        },
        "plausible_but_wrong": {
            "status": "analyzed",
            "algorithm": {
                "name": "Claimed constant-time lookup",
                "description": "The AI incorrectly claims an input scan is constant time.",
                "input_size_model": "n is the number of array elements.",
            },
            "time_complexity": {
                "best_case": "O(1)",
                "average_case": "O(1)",
                "worst_case": "O(1)",
                "derivation": "Intentionally incorrect mock reasoning: it ignores the input-dependent loop.",
            },
            "space_complexity": {
                "auxiliary": "O(1)",
                "total": "O(1)",
                "derivation": "Only a fixed number of scalar variables are used.",
            },
            "evidence": [
                {"line_start": 3, "line_end": 5, "claim": "Intentionally misleading claim that the loop has constant cost.", "role": "deliberately incorrect reasoning test"},
            ],
            "assumptions": [],
            "confidence": 0.99,
            "limitations": [],
            "unresolved_questions": [],
        },
    },

}


SCHEMA_BY_AGENT = {
    "agent1": RECONSTRUCTION_SCHEMA,
    "agent2": REFERENCE_SCHEMA,
    "agent5": VERIFICATION_SCHEMA,
    "agent4": COMPLEXITY_ANALYSIS_SCHEMA,
}


def get_scenario(agent: str, name: str) -> dict:
    """Return an isolated, schema-current copy of one named scenario."""
    try:
        response = deepcopy(SCENARIOS[agent][name])
        if agent == "agent4" and "grading_assessment" not in response:
            response["grading_assessment"] = {
                "rating": 2,
                "rationale": "The fixed mock scenario demonstrates a plausible dominant bound but does not establish all required grading evidence.",
                "evidence": [{
                    "line": 3,
                    "quote": "for (int i = 0; i < n; i++) {",
                }],
            }
        return response
    except KeyError as exc:
        raise KeyError(f"Unknown mock scenario: {agent}/{name}") from exc
