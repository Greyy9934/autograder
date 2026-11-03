"""Real, isolated, no-AI Two Sum demonstration using trusted built-in C programs."""
from __future__ import annotations
# Module role: Implements the demo runner subsystem used by the AutoGrader workflow.

import random
from typing import Any

from analyzers.batch_execution import benchmark_three_programs_parallel, run_c_batch


STUDENT_C = r"""
#include <stdio.h>
#include <stdlib.h>
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 10000) return 2;
    int *a = malloc((size_t)(n ? n : 1) * sizeof(int));
    if (!a) return 3;
    for (int i = 0; i < n; i++) {
        if (scanf("%d", &a[i]) != 1) { free(a); return 4; }
    }
    if (scanf("%d", &target) != 1) { free(a); return 5; }

    /* Deliberately simple student-style O(n^2) implementation. */
    int found = 0;
    for (int i = 0; i < n && !found; i++)
        for (int j = i + 1; j < n; j++)
            if ((long long)a[i] + a[j] == target) {
                found = 1;
                break;
            }
    puts(found ? "YES" : "NO");
    free(a);
    return 0;
}
"""

BRUTE_FORCE_C = r"""
#include <stdio.h>
#include <stdlib.h>
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 10000) return 2;
    int *a = malloc((size_t)(n ? n : 1) * sizeof(int));
    if (!a) return 3;
    for (int i = 0; i < n; i++)
        if (scanf("%d", &a[i]) != 1) { free(a); return 4; }
    if (scanf("%d", &target) != 1) { free(a); return 5; }

    int found = 0;
    for (int i = 0; i < n && !found; i++)
        for (int j = i + 1; j < n; j++)
            if ((long long)a[i] + a[j] == target) {
                found = 1;
                break;
            }
    puts(found ? "YES" : "NO");
    free(a);
    return 0;
}
"""

EFFICIENT_C = r"""
#include <stdio.h>
#include <stdlib.h>

static int compare_ints(const void *x, const void *y) {
    int a = *(const int *)x, b = *(const int *)y;
    return (a > b) - (a < b);
}

int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 10000) return 2;
    int *a = malloc((size_t)(n ? n : 1) * sizeof(int));
    if (!a) return 3;
    for (int i = 0; i < n; i++)
        if (scanf("%d", &a[i]) != 1) { free(a); return 4; }
    if (scanf("%d", &target) != 1) { free(a); return 5; }

    qsort(a, (size_t)n, sizeof(int), compare_ints);
    int left = 0, right = n - 1, found = 0;
    while (left < right) {
        long long sum = (long long)a[left] + a[right];
        if (sum == target) { found = 1; break; }
        if (sum < target) left++;
        else right--;
    }
    puts(found ? "YES" : "NO");
    free(a);
    return 0;
}
"""


# Function role: Implements the internal make input helper for demo runner.
# Same-file callers: _generate_benchmark_cases, _generate_edge_cases.
def _make_input(values: list[int], target: int) -> str:
    return f"{len(values)}\n{' '.join(map(str, values))}\n{target}\n"


# Function role: Implements the internal oracle helper for demo runner.
def _oracle(values: list[int], target: int) -> str:
    seen: set[int] = set()
    for value in values:
        if target - value in seen:
            return "YES"
        seen.add(value)
    return "NO"


# Function role: Reproducible progressive-size, no-solution inputs (seed 20261101).
# Same-file callers: build_real_demo_payload.
# Direct call references (conditional/branch-dependent): _make_input.
def _generate_benchmark_cases() -> list[dict[str, Any]]:
    """Reproducible progressive-size, no-solution inputs (seed 20261101)."""
    rng = random.Random(20261101)
    cases = []
    for size in (100, 300, 600, 1000, 1800):
        values = [rng.randint(-size, size) for _ in range(size)]
        target = 2 * size + 1  # Greater than the maximum possible pair sum.
        cases.append({
            "input_size": size,
            "input": _make_input(values, target),
            "expected_output": "NO",
            "distribution": "seeded_uniform_no_solution",
            "seed": 20261101,
        })
    return cases


# Function role: Implements the internal generate edge cases helper for demo runner.
# Same-file callers: build_real_demo_payload.
# Direct call references (conditional/branch-dependent): _make_input.
def _generate_edge_cases() -> list[dict[str, Any]]:
    definitions = [
        ("empty_array", [], 5, "NO", "Minimum valid array length."),
        ("single_element", [5], 10, "NO", "A single position cannot be reused."),
        ("duplicate_pair", [3, 3, 3, 3], 6, "YES", "Two distinct equal-valued positions form a pair."),
        ("negative_values", [-8, 2, 5], -3, "YES", "Checks negative operands and target."),
        ("no_solution", [1, 4, 9], 30, "NO", "Checks a valid input with no matching pair."),
        ("integer_extremes", [-2147483648, 2147483647], -1, "YES", "Checks addition without 32-bit overflow."),
    ]
    return [
        {
            "name": name,
            "values": values,
            "target": target,
            "input": _make_input(values, target),
            "expected_output": expected,
            "rationale": rationale,
        }
        for name, values, target, expected, rationale in definitions
    ]


# Function role: Run only trusted demo code; accepts no user source or form data.
# Direct call references (conditional/branch-dependent): _generate_benchmark_cases, _generate_edge_cases.
def build_real_demo_payload() -> dict[str, Any]:
    """Run only trusted demo code; accepts no user source or form data."""
    cases = _generate_benchmark_cases()
    edge_cases = _generate_edge_cases()

    # Validate generated inputs against the scenario's input constraints.
    for case in cases:
        values = list(map(int, case["input"].split()[1:-1]))
        if len(values) != case["input_size"] or any(
            value < -case["input_size"] or value > case["input_size"]
            for value in values
        ):
            raise RuntimeError("Built-in demo generator produced an invalid input.")

    benchmark = benchmark_three_programs_parallel(
        STUDENT_C,
        BRUTE_FORCE_C,
        EFFICIENT_C,
        cases,
        time_budget_seconds=2.0,
    )

    # Convert runner token counts into the actual array sizes from the generator.
    for point in benchmark.get("chart_data", []):
        case_number = point.get("case", 0)
        if 1 <= case_number <= len(cases):
            point["input_size"] = cases[case_number - 1]["input_size"]

    # Independently check each successful program output against the Python oracle.
    for comparison, case in zip(
        benchmark.get("differential_comparisons", []), cases
    ):
        expected = case["expected_output"]
        comparison["oracle_expected_output"] = expected
        comparison["oracle_checks"] = {}
        for program, outcome in comparison.get("outcomes", {}).items():
            actual = outcome.get("stdout", "").strip()
            comparison["oracle_checks"][program] = (
                actual == expected
                if outcome.get("execution_class") == "program_success"
                else None
            )

    edge_batch = run_c_batch(
        STUDENT_C,
        [case["input"] for case in edge_cases],
    )
    edge_results = edge_batch.get("results", [])
    executed_edge_cases = []
    for index, case in enumerate(edge_cases):
        run = edge_results[index] if index < len(edge_results) else {}
        actual = run.get("stdout", "").strip()
        executed_edge_cases.append({
            **case,
            "execution_class": run.get("execution_class", "not_executed"),
            "exit_code": run.get("exit_code"),
            "actual_output": actual,
            "passed": (
                actual == case["expected_output"]
                and run.get("execution_class") == "program_success"
            ),
            "runtime_seconds": run.get("run_seconds"),
            "stderr": run.get("stderr", ""),
        })

    benchmark["generator"] = {
        "name": "seeded_progressive_integer_array_generator",
        "language": "Python",
        "seed": 20261101,
        "sizes": [case["input_size"] for case in cases],
        "distributions": ["seeded uniform", "no-solution target"],
        "inputs_validated": True,
        "sample_input": cases[0]["input"],
        "note": "Inputs are generated by the executable Python generator function in this module.",
    }

    return {
        "simulation": False,
        "mode": "REAL DEMO — PREDEFINED INPUTS, REAL EXECUTION",
        "notice": (
            "This demo uses built-in Two Sum examples only. Submitted form "
            "fields are not read. No AI provider is called. GCC compilation, "
            "sandbox execution, edge-case tests and benchmark timings are real."
        ),
        "agents": {
            "agent1": {
                "status": "ready",
                "problem_statement": "Given an integer array and target, determine whether two distinct array positions sum to the target.",
                "input_schema": "n; n space-separated integers; target.",
                "constraints": ["0 <= n <= 10000", "Each array position can be used at most once."],
                "assumptions": ["Output YES if a pair exists; otherwise NO."],
                "approval": "Predefined demo specification; no instructor approval is implied.",
            },
            "agent2": {
                "status": "real_demo_programs",
                "student": {"language": "C17", "time_complexity": "O(n^2)", "space_complexity": "O(n)", "code": STUDENT_C},
                "brute_force": {"language": "C17", "time_complexity": "O(n^2)", "space_complexity": "O(n)", "code": BRUTE_FORCE_C},
                "efficient": {"language": "C17", "time_complexity": "O(n log n)", "space_complexity": "O(n)", "code": EFFICIENT_C},
                "compilation": "All three programs are compiled by the benchmark runner before timing begins.",
            },
            "agent3a": {
                "status": benchmark.get("status", "unknown"),
                "benchmark": benchmark,
                "programs": ["student", "brute_force", "efficient"],
                "deadline_seconds": 2.0,
                "shared_deadline": True,
                "measured_values_only": True,
            },
            "agent3b": {
                "status": edge_batch.get("status", "unknown"),
                "execution_summary": edge_batch.get("summary", {}),
                "cases": executed_edge_cases,
                "passed": sum(case["passed"] is True for case in executed_edge_cases),
                "total": len(executed_edge_cases),
            },
            "agent4": {
                "status": "analysis_available",
                "theoretical": {
                    "student": {"time": "O(n^2)", "space": "O(n)"},
                    "brute_force": {"time": "O(n^2)", "space": "O(n)"},
                    "efficient": {"time": "O(n log n)", "space": "O(n)"},
                },
                "empirical_source": "Agent 3A real benchmark results",
                "benchmark_status": benchmark.get("status"),
                "caution": "Measured timings are observations, not a proof of asymptotic complexity.",
            },
            "agent5": {
                "status": "proof_sketch",
                "claim": "The two-pointer algorithm returns YES exactly when two distinct positions sum to the target.",
                "proof": [
                    "Sorting preserves the multiset of array values.",
                    "At each iteration, all pairs involving values smaller than the current left value cannot reach the target when the current sum is too small; advancing left is therefore safe.",
                    "When the current sum is too large, all pairs involving the current right value and any value at least as large as the current left value are too large; decreasing right is safe.",
                    "Each step strictly reduces the interval. If a matching pair exists, these eliminations cannot discard every matching pair. The algorithm terminates with a match or an empty interval.",
                ],
                "limitation": "This is a demo proof sketch, not a machine-checked proof.",
            },
            "agent6": {
                "status": "reviewed_demo_code",
                "findings": [
                    {"severity": "info", "finding": "All programs check input parsing and bound n before allocation."},
                    {"severity": "info", "finding": "Pair sums use long long to avoid signed 32-bit addition overflow."},
                    {"severity": "info", "finding": "The efficient implementation sorts then uses two pointers; qsort contributes O(n log n) time."},
                    {"severity": "note", "finding": "The three implementations allocate O(n) storage for the input array."},
                ],
            },
        },
        "pdf": {
            "status": "not_generated",
            "label": "Real Demo results; PDF generation remains a separate workflow step.",
        },
    }
