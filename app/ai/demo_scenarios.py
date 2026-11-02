"""Pinned, task-routed AI responses for the authenticated Demo workflow."""
from __future__ import annotations

from copy import deepcopy
import secrets
from typing import Any

from app.ai.base import AIProviderError
from app.ai.output_budget import (
    TASK_CODE_QUALITY,
    TASK_COMPLEXITY,
    TASK_EDGE_CASES,
    TASK_MATHEMATICAL_PROOF,
    TASK_RANDOM_GENERATOR,
    TASK_RECONSTRUCTION,
    TASK_REFERENCES,
)
from app.ai.guardrails import GuardedProvider
from analyzers.structured_input_schema import StructuredIntegerInputSchema


BINARY_STUDENT = r'''#include <stdio.h>
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 20000) return 1;
    int a[20000];
    for (int i = 0; i < n; ++i) if (scanf("%d", &a[i]) != 1) return 1;
    if (scanf("%d", &target) != 1) return 1;
    for (int i = 0; i < n; ++i) {
        if (a[i] == target) { printf("%d\n", i); return 0; }
    }
    puts("-1");
    return 0;
}'''

BINARY_EFFICIENT = r'''#include <stdio.h>
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 20000) return 1;
    int a[20000];
    for (int i = 0; i < n; ++i) if (scanf("%d", &a[i]) != 1) return 1;
    if (scanf("%d", &target) != 1) return 1;
    int low = 0, high = n;
    while (low < high) {
        int mid = low + (high - low) / 2;
        if (a[mid] < target) low = mid + 1;
        else high = mid;
    }
    if (low < n && a[low] == target) printf("%d\n", low);
    else puts("-1");
    return 0;
}'''

SUBSET_STUDENT = r'''#include <stdio.h>
static int search(const int a[], int n, int i, int rem) {
    if (rem == 0) return 1;
    if (i == n) return 0;
    if (search(a, n, i + 1, rem)) return 1;
    return a[i] <= rem && search(a, n, i + 1, rem - a[i]);
}
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 18) return 1;
    int a[18];
    for (int i = 0; i < n; ++i)
        if (scanf("%d", &a[i]) != 1 || a[i] < 0 || a[i] > 40) return 1;
    if (scanf("%d", &target) != 1 || target < 0 || target > 800) return 1;
    puts(search(a, n, 0, target) ? "YES" : "NO");
    return 0;
}'''

SUBSET_EFFICIENT = r'''#include <stdio.h>
int main(void) {
    int n, target;
    if (scanf("%d", &n) != 1 || n < 0 || n > 18) return 1;
    int a[18];
    for (int i = 0; i < n; ++i)
        if (scanf("%d", &a[i]) != 1 || a[i] < 0 || a[i] > 40) return 1;
    if (scanf("%d", &target) != 1 || target < 0 || target > 800) return 1;
    unsigned char dp[801] = {0};
    dp[0] = 1;
    for (int i = 0; i < n; ++i)
        for (int sum = target; sum >= a[i]; --sum)
            if (dp[sum - a[i]]) dp[sum] = 1;
    puts(dp[target] ? "YES" : "NO");
    return 0;
}'''

BINARY_SCHEMA = {"version": 1, "size_field": "values", "fields": [
    {"name": "n", "type": "int", "min": 0, "max": 20000},
    {"name": "values", "type": "int_array", "length_from": "n", "min": -1000000, "max": 1000000},
    {"name": "target", "type": "int", "min": -1000000, "max": 1000000},
]}
SUBSET_SCHEMA = {"version": 1, "size_field": "values", "fields": [
    {"name": "n", "type": "int", "min": 0, "max": 18},
    {"name": "values", "type": "int_array", "length_from": "n", "min": 0, "max": 40},
    {"name": "target", "type": "int", "min": 0, "max": 800},
]}

BINARY_GENERATOR = r'''import json, random, sys
rng=random.Random(int(sys.argv[1])); count=int(sys.argv[2]); cases=[]
small_end=count if count < 10 else count*70//100
medium_end=count if count < 10 else count*90//100
upper_ladder=[8000,14000,20000]
for i in range(count):
 if i < small_end: n=rng.randint(1,512)
 elif i < medium_end: n=rng.randint(513,4096)
 else: n=upper_ladder[min(len(upper_ladder)-1,(i-medium_end)*len(upper_ladder)//max(1,count-medium_end))]
 a=sorted(rng.randint(-999999,999999) for _ in range(n))
 mode=i%4; x=[a[0],a[-1],a[n//2],1000000][mode]
 cases.append({"input_size":n,"input":f"{n}\n{' '.join(map(str,a))}\n{x}\n","distribution":["first","last","middle","absent"][mode]})
print(json.dumps({"inputs":cases}))'''
SUBSET_GENERATOR = r'''import json, random, sys
rng=random.Random(int(sys.argv[1])); count=int(sys.argv[2]); cases=[]
small_end=count if count < 10 else count*70//100
medium_end=count if count < 10 else count*90//100
for i in range(count):
 if i < small_end: n=rng.randint(1,12)
 elif i < medium_end: n=rng.randint(13,16)
 else: n=rng.randint(17,18)
 a=[rng.randint(0,40) for _ in range(n)]; mode=i%4
 t=[0,a[0],sum(a)+1,sum(a[:min(3,n)])][mode]
 cases.append({"input_size":n,"input":f"{n}\n{' '.join(map(str,a))}\n{t}\n","distribution":["zero","single","unreachable","combination"][mode]})
print(json.dumps({"inputs":cases}))'''


def _edge(name: str, text: str, expected: str, rationale: str) -> dict[str, Any]:
    return {"name": name, "input": text, "expected_output": expected + "\n",
            "target": ["student", "brute_force", "efficient"], "rationale": rationale,
            "failure_hypothesis": "Exercise this contract boundary; actual execution determines the outcome.",
            "constraint_basis": "Predefined input conforms to the scenario contract."}

BINARY_EDGES = [
    _edge("empty", "0\n\n5\n", "-1", "No values are present."),
    _edge("one_match", "1\n7\n7\n", "0", "Single-element match."),
    _edge("below_first", "4\n-5 -1 3 8\n-9\n", "-1", "Target below all values."),
    _edge("above_last", "4\n-5 -1 3 8\n9\n", "-1", "Target above all values."),
    _edge("first", "5\n-8 -2 0 4 11\n-8\n", "0", "First position match."),
    _edge("last", "5\n-8 -2 0 4 11\n11\n", "4", "Last position match."),
    _edge("middle", "5\n-8 -2 0 4 11\n0\n", "2", "Middle position match."),
    _edge("between", "4\n-5 -1 3 8\n1\n", "-1", "Absent target between values."),
    _edge("duplicate_first", "6\n-2 3 3 3 9 12\n3\n", "1", "Duplicates allowed; first index required."),
    _edge("integer_bounds", "4\n-1000000 -1 2 1000000\n1000000\n", "3", "Permitted value endpoints."),
]
BINARY_EDGES.append(_edge(
    "large_sorted_array",
    f"256\n{' '.join(map(str, range(-128, 128)))}\n127\n",
    "255",
    "Large valid sorted input exercises the upper-array search path.",
))
SUBSET_EDGES = [
    _edge("empty_zero", "0\n\n0\n", "YES", "Empty subset reaches zero."),
    _edge("empty_positive", "0\n\n1\n", "NO", "No value can reach a positive target."),
    _edge("zero_target", "3\n4 0 9\n0\n", "YES", "Zero target is reachable."),
    _edge("single_match", "1\n7\n7\n", "YES", "One value exactly matches."),
    _edge("single_miss", "1\n7\n8\n", "NO", "One value does not reach target."),
    _edge("combination", "5\n2 4 7 9 12\n13\n", "YES", "4 and 9 combine to target."),
    _edge("unreachable", "3\n2 3 4\n20\n", "NO", "Target exceeds total sum."),
    _edge("repeats", "5\n3 3 3 3 3\n9\n", "YES", "Three repeated positions sum to target."),
    _edge("zeros", "4\n0 0 5 0\n5\n", "YES", "Zero values and positive match."),
    _edge("max_n", "18\n1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18\n171\n", "YES", "Maximum permitted n without unsafe shifts."),
]


def _refs(alg: str, code: str, time: str, space: str) -> dict[str, str]:
    return {"algorithm": alg, "code": code, "time_complexity": time, "space_complexity": space}


def _agent4(name: str, desc: str, model: str, best: str, avg: str, worst: str,
            aux: str, total: str, derivation: str, line: int) -> dict[str, Any]:
    # The scenario-specific source is available through the associated reference.
    quote_line, quote = line, ""
    return {"status": "analyzed", "algorithm": {"name": name, "description": desc, "input_size_model": model},
            "time_complexity": {"best_case": best, "average_case": avg, "worst_case": worst, "derivation": derivation},
            "space_complexity": {"auxiliary": aux, "total": total, "derivation": "Input storage is linear in n; the named algorithm uses the stated auxiliary space."},
            "evidence": [{"line_start": line, "line_end": line, "claim": desc, "role": "algorithm evidence"}],
            "assumptions": [model], "confidence": 0.98,
            "grading_assessment": {"rating": 3, "rationale": "The dominant time bound and auxiliary space are supported by the inspected implementation and its stated input model.", "evidence": [{"line": quote_line, "quote": quote}]},
            "limitations": ["Predefined simulated analysis; timings come from the real benchmark."], "unresolved_questions": []}


def _proof(theorem: str, strategy: str, steps: list[dict[str, str]]) -> dict[str, Any]:
    return {"outcome": "proof_sketch", "theorem": theorem,
            "preconditions": ["Inputs satisfy the scenario's stated bounds and contract."],
            "postconditions": ["Output matches the scenario's specified behavior."],
            "assumptions": ["The compiled source is executed under the stated input contract."],
            "proof_strategy": strategy, "proof_steps": steps, "conclusion": theorem,
            "counterexample": None, "limitations": ["Predefined simulated proof sketch; not mechanically checked."]}


def _step(claim: str, justification: str, equation: str) -> dict[str, str]:
    return {"claim": claim, "justification": justification, "equation": equation}


def _quality(summary: str, strengths: list[str], source: str, ratings: tuple[int, int, int] = (3, 3, 3)) -> dict[str, Any]:
    lines = source.splitlines() or [""]
    chosen = {
        "readability": next((i for i, text in enumerate(lines, 1) if "printf" in text or "scanf" in text), 1),
        "modularity": next((i for i, text in enumerate(lines, 1) if "static " in text or text.startswith("int main")), 1),
        "design_originality": next((i for i, text in enumerate(lines, 1) if "while (" in text or "search(" in text or "dp[" in text or "for (" in text), 1),
    }
    rating_by_name = dict(zip(chosen, ratings))
    descriptions = {
        "readability": "The cited statement shows the input/output and control-flow style used by this implementation.",
        "modularity": "The cited routine boundary shows how the implementation divides responsibilities.",
        "design_originality": "The cited algorithmic step demonstrates the selected problem-specific design.",
    }
    rubric = {name: {"rating": rating_by_name[name], "rationale": descriptions[name],
                     "evidence": [{"line": chosen[name], "quote": lines[chosen[name] - 1].strip()}]}
              for name in chosen}
    return {"summary": summary, "strengths": strengths, "findings": [],
            "rubric_ratings": rubric,
            "limitations": ["Predefined Agent 6 response; no live AI review was performed."]}


BINARY_SEARCH = {
    "scenario_id": "binary_search", "name": "Binary Search",
    "statement": "Given n integers sorted in non-decreasing order and target x, print the zero-based index of the first occurrence of x, or -1 if absent. Duplicates are allowed. Input is n, then n values, then x.",
    "constraints": ["0 <= n <= 20000.", "Values and target are in [-1000000, 1000000].", "Values are sorted non-decreasingly; duplicates are permitted.", "Return the first matching zero-based index, or -1."],
    "input_schema": BINARY_SCHEMA, "generator_schema": BINARY_SCHEMA,
    "student": BINARY_STUDENT,
    "brute_force": _refs("Left-to-right scan; return the first match.", BINARY_STUDENT, "O(n)", "O(n) total, O(1) auxiliary"),
    "efficient": _refs("Lower-bound binary search.", BINARY_EFFICIENT, "O(log n)", "O(n) total, O(1) auxiliary"),
    "generator": {"language": "Python 3", "program": BINARY_GENERATOR, "seeded": True, "sorted_arrays": True},
    "edge_cases": BINARY_EDGES,
    "agent_responses": {
        "agent1": {"status": "ready", "candidates": [{"id": "binary_search", "title": "First occurrence in sorted array", "problem_statement": "Return the first zero-based index of target in a sorted integer array, or -1.", "input_format": "n, n sorted integers, target", "output_format": "First zero-based index or -1", "input_schema": BINARY_SCHEMA, "evidence": ["The program reads integer values and searches for a target."], "assumptions": ["The array is sorted and duplicates are allowed."], "confidence": 0.99}], "clarifying_questions": [], "constraints": ["0 <= n <= 20000.", "Values and target are in [-1000000, 1000000].", "Values are sorted non-decreasingly; duplicates are permitted.", "Return the first matching zero-based index, or -1."], "limitations": ["Simulated Binary Search reconstruction."]},
        "agent2": {"problem_summary": "Return the first matching target index in a sorted array, else -1.", "assumptions": ["Sorted non-decreasing input; first duplicate index."], "brute_force": _refs("Left-to-right scan; return the first match.", BINARY_STUDENT, "O(n)", "O(n) total, O(1) auxiliary"), "efficient": _refs("Lower-bound binary search.", BINARY_EFFICIENT, "O(log n)", "O(n) total, O(1) auxiliary"), "limitations": ["Candidate references are executed on real scenario cases."]},
        "agent3a": {"generator_program": BINARY_GENERATOR, "design_rationale": "Most sorted-array cases use small and medium sizes for complete comparisons; sparse upper probes preserve a useful input-size curve.", "distributions": ["first", "last", "middle", "absent"], "size_strategy": "70% n=1..512, 20% n=513..4096, and 10% sparse probes up to n=20000.", "limitations": ["Generator is predefined and its output is schema and sortedness validated."]},
        "agent3b": {"summary": "Check empty, boundary, duplicate, absent, and endpoint-value behavior.", "cases": BINARY_EDGES, "limitations": ["Predefined cases are validated and executed by the real pipeline."]},
        "agent4": _agent4("Linear scan and lower-bound search", "The student scans values in order; the efficient reference halves a sorted interval.", "n = number of values", "O(1)", "O(n)", "O(n)", "O(1)", "O(n)", "The scan examines at most n values; lower-bound binary search halves the interval each iteration.", 8),
        "agent5": _proof("The scan returns the least index matching target, or -1 if no match exists.", "Loop invariant over the already examined prefix.", [_step("No earlier position matches before iteration i.", "Each preceding value was tested and differed.", "For all j < i: a[j] != target"), _step("A match at i is the first match.", "Indices are visited in increasing order.", "a[i] = target and all earlier values differ"), _step("After n misses, target is absent.", "Every array position was inspected.", "For all 0 <= j < n: a[j] != target")]),
        "agent6": _quality("The implementation handles duplicates by returning the first match and checks the declared array bound.", ["Input length is bounded before array reads.", "The first matching index is returned.", "Absence has a consistent -1 result."], BINARY_STUDENT, (3, 2, 3)),
    },
}

SUBSET_SUM = {
    "scenario_id": "subset_sum", "name": "Subset Sum",
    "statement": "Given n non-negative integers and target T, print YES if some subset sums exactly to T, otherwise NO. Each position can be used once; the empty subset is allowed. Input is n, then n values, then T.",
    "constraints": ["0 <= n <= 18; this bounds brute-force recursion depth.", "Each value is in [0, 40]; zero and repeats are allowed.", "0 <= T <= 800; total sum is at most 720."],
    "input_schema": SUBSET_SCHEMA, "generator_schema": SUBSET_SCHEMA,
    "student": SUBSET_STUDENT,
    "brute_force": _refs("Recursive include/exclude enumeration; depth <= 18.", SUBSET_STUDENT, "O(2**n)", "O(n) input and recursion stack"),
    "efficient": _refs("One-dimensional dynamic programming over reachable sums.", SUBSET_EFFICIENT, "O(n*T)", "O(T) auxiliary plus O(n) input"),
    "generator": {"language": "Python 3", "program": SUBSET_GENERATOR, "seeded": True, "max_n": 18, "max_target": 800},
    "edge_cases": SUBSET_EDGES,
    "agent_responses": {
        "agent1": {"status": "ready", "candidates": [{"id": "subset_sum", "title": "Bounded non-negative subset sum", "problem_statement": "Determine if a subset of non-negative integers reaches the target; each position may be used once and the empty subset is allowed.", "input_format": "n, n non-negative integers, target", "output_format": "YES or NO", "input_schema": SUBSET_SCHEMA, "evidence": ["The program reads a bounded integer list and target."], "assumptions": ["Each position can be selected once."], "confidence": 0.99}], "clarifying_questions": [], "constraints": ["0 <= n <= 18; this bounds brute-force recursion depth.", "Each value is in [0, 40]; zero and repeats are allowed.", "0 <= T <= 800; total sum is at most 720."], "limitations": ["Simulated Subset Sum reconstruction."]},
        "agent2": {"problem_summary": "Determine whether a subset of bounded non-negative values sums to target.", "assumptions": ["Each position is used at most once; empty subset is allowed."], "brute_force": _refs("Recursive include/exclude enumeration; depth <= 18.", SUBSET_STUDENT, "O(2**n)", "O(n) input and recursion stack"), "efficient": _refs("One-dimensional dynamic programming over reachable sums.", SUBSET_EFFICIENT, "O(n*T)", "O(T) auxiliary plus O(n) input"), "limitations": ["The safe n bound keeps exhaustive reference execution finite."]},
        "agent3a": {"generator_program": SUBSET_GENERATOR, "design_rationale": "Most seeded instances stay within small/medium sizes for broad comparisons; only a small share approaches the exponential upper range.", "distributions": ["zero", "single", "unreachable", "combination"], "size_strategy": "70% n=1..12, 20% n=13..16, and 10% n=17..18.", "limitations": ["Every case obeys the schema and safe brute-force bounds; upper probes may reach the runtime cap."]},
        "agent3b": {"summary": "Exercise empty input, zero, exact matches, repeated values, impossible targets, and combinations.", "cases": SUBSET_EDGES, "limitations": ["Predefined cases are validated and executed by the real pipeline."]},
        "agent4": _agent4("Include/exclude recursion and sum dynamic programming", "The student branches on excluding or including each value; the reference records reachable sums.", "n = number of values; T = target", "O(1)", "O(2**n)", "O(2**n)", "O(n)", "O(n)", "The recursive search has a binary include/exclude tree; the DP reference runs O(n*T).", 2),
        "agent5": _proof("The recursion returns YES exactly when a subset of the remaining suffix reaches the remaining target.", "Induction on the suffix length.", [_step("Remaining sum zero is reachable.", "The chosen values already meet target; exclude the rest.", "sum(chosen) = T"), _step("A positive remainder at the final index is unreachable.", "No values remain.", "i = n and rem > 0 => false"), _step("Every solution either excludes or includes the current value.", "Both branches are explored and inclusion advances the index.", "Reach(i,r) = Reach(i+1,r) OR Reach(i+1,r-a[i])")]),
        "agent6": _quality("The bounded recursive implementation models the include/exclude choices directly.", ["Input values and target are range-checked.", "Recursion depth is capped at 18.", "Each input position is used at most once."], SUBSET_STUDENT, (3, 3, 3)),
    },
}


FIBONACCI_STUDENT = r'''#include <stdio.h>
static long long fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
int main(void) {
    int n;
    if (scanf("%d", &n) != 1 || n < 0 || n > 40) return 1;
    printf("%lld\n", fib(n));
    return 0;
}'''

FIBONACCI_EFFICIENT = r'''#include <stdio.h>
int main(void) {
    int n;
    if (scanf("%d", &n) != 1 || n < 0 || n > 40) return 1;
    long long previous = 0, current = 1;
    for (int i = 0; i < n; ++i) {
        long long next = previous + current;
        previous = current;
        current = next;
    }
    printf("%lld\n", previous);
    return 0;
}'''

FIBONACCI_SCHEMA = {"version": 1, "size_field": "n", "fields": [
    {"name": "n", "type": "int", "min": 0, "max": 40},
]}
FIBONACCI_GENERATOR = r'''import json, random, sys
rng=random.Random(int(sys.argv[1])); count=int(sys.argv[2]); cases=[]
small_end=count if count < 10 else count*70//100
medium_end=count if count < 10 else count*90//100
upper_ladder=[27,29,31,33,35,37,39,40]
for i in range(count):
 if i < small_end: n=rng.randint(1,14)
 elif i < medium_end: n=rng.randint(15,25)
 else: n=upper_ladder[min(len(upper_ladder)-1,(i-medium_end)*len(upper_ladder)//max(1,count-medium_end))]
 cases.append({"input_size":n,"input":f"{n}\n","distribution":"seeded_small_medium" if i < medium_end else "sparse_upper_growth_probe"})
print(json.dumps({"inputs":cases}))'''
FIBONACCI_EDGES = [
    _edge("zero", "0\n", "0", "The base value F(0) is zero."),
    _edge("one", "1\n", "1", "The base value F(1) is one."),
    _edge("second_recurrence", "2\n", "1", "Checks the first recurrence step."),
    _edge("third_recurrence", "3\n", "2", "Checks the next recurrence step."),
    _edge("small_recurrence", "10\n", "55", "Checks a short recurrence sequence."),
    _edge("medium_value", "20\n", "6765", "Checks a medium-sized recurrence value."),
    _edge("large_value", "30\n", "832040", "Checks the exponential implementation at a larger input."),
    _edge("upper_value", "40\n", "102334155", "Largest supported input remains within signed 32-bit output."),
]

FIBONACCI = {
    "scenario_id": "fibonacci", "name": "Fibonacci (recursive vs iterative)",
    "statement": "Given n, print the n-th Fibonacci number with F(0)=0, F(1)=1, and F(n)=F(n-1)+F(n-2). Input is one integer n.",
    "constraints": ["0 <= n <= 40.", "The answer fits in a signed 32-bit integer."],
    "input_schema": FIBONACCI_SCHEMA, "generator_schema": FIBONACCI_SCHEMA,
    "student": FIBONACCI_STUDENT,
    "brute_force": _refs("Naive recursive Fibonacci.", FIBONACCI_STUDENT, "O(2**n)", "O(n) recursion stack"),
    "efficient": _refs("Iterative Fibonacci recurrence.", FIBONACCI_EFFICIENT, "O(n)", "O(1) auxiliary"),
    "generator": {"language": "Python 3", "program": FIBONACCI_GENERATOR, "seeded": True, "max_n": 40},
    "edge_cases": FIBONACCI_EDGES,
    "agent_responses": {
        "agent1": {"status": "ready", "candidates": [{"id": "fibonacci", "title": "Nth Fibonacci number", "problem_statement": "Compute F(n), where F(0)=0, F(1)=1, and F(n)=F(n-1)+F(n-2).", "input_format": "One integer n", "output_format": "The exact integer F(n)", "input_schema": FIBONACCI_SCHEMA, "evidence": ["The program reads one integer and evaluates the Fibonacci recurrence."], "assumptions": ["The input is in the declared range."], "confidence": 0.99}], "clarifying_questions": [], "constraints": ["0 <= n <= 40.", "The result fits in a signed 32-bit integer."], "limitations": ["Simulated Fibonacci reconstruction."]},
        "agent2": {"problem_summary": "Compute the n-th Fibonacci number with the standard zero-based recurrence.", "assumptions": ["F(0)=0 and F(1)=1."], "brute_force": _refs("Naive recursive Fibonacci.", FIBONACCI_STUDENT, "O(2**n)", "O(n) recursion stack"), "efficient": _refs("Iterative Fibonacci recurrence.", FIBONACCI_EFFICIENT, "O(n)", "O(1) auxiliary"), "limitations": ["Both references implement the same recurrence."]},
        "agent3a": {"generator_program": FIBONACCI_GENERATOR, "design_rationale": "Most seeded cases stay in small and medium n for complete three-way comparisons; a sparse upper ladder probes the exponential boundary.", "distributions": ["seeded_small_medium", "sparse_upper_growth_probe"], "size_strategy": "70% n=1..14, 20% n=15..25, and 10% sparse probes from n=27..40.", "limitations": ["Input generation is deterministic and schema validated; upper probes may reach the explicit brute-force benchmark cap."]},
        "agent3b": {"summary": "Check both base cases, an interior recurrence value, and the upper supported value.", "cases": FIBONACCI_EDGES, "limitations": ["Predefined cases are validated and executed by the real pipeline."]},
        "agent4": _agent4("Naive recursion and iterative recurrence", "The student recomputes overlapping Fibonacci subproblems; the reference advances two state values once per index.", "n = requested Fibonacci index", "O(1)", "O(2**n)", "O(2**n)", "O(n)", "O(n)", "The naive recursion forms a binary call tree; the iterative reference performs n transitions.", 2),
        "agent5": _proof("The iterative program prints F(n) for every supported n.", "Loop invariant over the two consecutive Fibonacci values.", [_step("Before iteration i, previous=F(i) and current=F(i+1).", "The invariant holds initially for i=0.", "previous=F(0)=0; current=F(1)=1"), _step("One iteration advances the pair to F(i+1),F(i+2).", "The update uses the Fibonacci recurrence.", "next=F(i)+F(i+1)=F(i+2)"), _step("After n iterations, previous equals F(n).", "The loop advances exactly n times.", "previous=F(n)")]),
        "agent6": _quality("The reference uses constant auxiliary memory and avoids repeated recursive work.", ["Both implementations validate the input range.", "The iterative state update follows the recurrence directly.", "The maximum result fits the declared integer type."], FIBONACCI_STUDENT, (3, 2, 3)),
    },
}


TSP_BRUTE = r'''#include <limits.h>
#include <stdio.h>
#define MAX_N 12
static int n, distance_matrix[MAX_N][MAX_N], used[MAX_N];
static long long best = LLONG_MAX;
static void search(int city, int visited, long long cost) {
    if (visited == n) {
        long long tour = cost + distance_matrix[city][0];
        if (tour < best) best = tour;
        return;
    }
    for (int next = 1; next < n; ++next) {
        if (!used[next]) {
            used[next] = 1;
            search(next, visited + 1, cost + distance_matrix[city][next]);
            used[next] = 0;
        }
    }
}
int main(void) {
    int entries;
    if (scanf("%d %d", &n, &entries) != 2 ||
        n < 2 || n > MAX_N || entries != n * n) return 1;
    for (int i = 0; i < n; ++i)
        for (int j = 0; j < n; ++j)
            if (scanf("%d", &distance_matrix[i][j]) != 1 ||
                distance_matrix[i][j] < 0 || distance_matrix[i][j] > 1000)
                return 1;
    used[0] = 1;
    search(0, 1, 0);
    printf("%lld", best);
    putchar(10);
    return 0;
}'''

TSP_HELD_KARP = r'''#include <limits.h>
#include <stdio.h>
#define MAX_N 12
#define MAX_MASK (1 << MAX_N)
#define INF (LLONG_MAX / 4)
static int distance_matrix[MAX_N][MAX_N];
static long long dp[MAX_MASK][MAX_N];
int main(void) {
    int n, entries;
    if (scanf("%d %d", &n, &entries) != 2 ||
        n < 2 || n > MAX_N || entries != n * n) return 1;
    for (int i = 0; i < n; ++i)
        for (int j = 0; j < n; ++j)
            if (scanf("%d", &distance_matrix[i][j]) != 1 ||
                distance_matrix[i][j] < 0 || distance_matrix[i][j] > 1000)
                return 1;

    int limit = 1 << n;
    for (int mask = 0; mask < limit; ++mask)
        for (int last = 0; last < n; ++last)
            dp[mask][last] = INF;
    dp[1][0] = 0;

    for (int mask = 1; mask < limit; ++mask) {
        if (!(mask & 1)) continue;
        for (int last = 0; last < n; ++last) {
            if (!(mask & (1 << last)) || dp[mask][last] == INF) continue;
            for (int next = 1; next < n; ++next) {
                if (mask & (1 << next)) continue;
                int next_mask = mask | (1 << next);
                long long candidate =
                    dp[mask][last] + distance_matrix[last][next];
                if (candidate < dp[next_mask][next])
                    dp[next_mask][next] = candidate;
            }
        }
    }

    long long answer = INF;
    int full = limit - 1;
    for (int last = 1; last < n; ++last) {
        long long candidate = dp[full][last] + distance_matrix[last][0];
        if (candidate < answer) answer = candidate;
    }
    printf("%lld", answer);
    putchar(10);
    return 0;
}'''

TSP_SCHEMA = {"version": 1, "size_field": "n", "fields": [
    {"name": "n", "type": "int", "min": 2, "max": 12},
    {"name": "m", "type": "int", "min": 4, "max": 144},
    {"name": "weights", "type": "int_array", "length_from": "m", "min": 0, "max": 1000},
]}
TSP_GENERATOR = r'''import json, random, sys
rng=random.Random(int(sys.argv[1])); count=int(sys.argv[2]); cases=[]
small_end=count if count < 10 else count*70//100
medium_end=count if count < 10 else count*90//100
upper_ladder=[10,11,12]
for i in range(count):
 if i < small_end: n=rng.randint(2,7)
 elif i < medium_end: n=rng.randint(8,9)
 else: n=upper_ladder[min(len(upper_ladder)-1,(i-medium_end)*len(upper_ladder)//max(1,count-medium_end))]
 matrix=[[0]*n for _ in range(n)]
 for u in range(n):
  for v in range(u+1,n):
   matrix[u][v]=matrix[v][u]=rng.randint(1,1000)
 flat=[value for row in matrix for value in row]
 text=f"{n} {n*n}" + chr(10) + " ".join(map(str,flat)) + chr(10)
 cases.append({"input_size":n,"input":text,"distribution":"seeded_small_medium_complete_graph" if i < medium_end else "sparse_upper_growth_probe"})
print(json.dumps({"inputs":cases}))'''

def _tsp_input(matrix: list[list[int]]) -> str:
    n = len(matrix)
    flat = " ".join(str(value) for row in matrix for value in row)
    return f"{n} {n*n}" + chr(10) + flat + chr(10)

TSP_EDGES = [
    _edge("two_cities", _tsp_input([[0, 7], [7, 0]]), "14", "The only round trip visits both cities."),
    _edge("triangle", _tsp_input([[0, 1, 8], [1, 0, 2], [8, 2, 0]]), "11", "Checks the cheaper of the two triangle tours."),
    _edge("square", _tsp_input([[0, 10, 15, 20], [10, 0, 35, 25], [15, 35, 0, 30], [20, 25, 30, 0]]), "80", "Known four-city optimum."),
    _edge("equal_edges", _tsp_input([[0, 5, 5, 5], [5, 0, 5, 5], [5, 5, 0, 5], [5, 5, 5, 0]]), "20", "All tours have the same cost."),
    _edge("five_city_cycle", _tsp_input([[0, 1, 9, 9, 1], [1, 0, 1, 9, 9], [9, 1, 0, 1, 9], [9, 9, 1, 0, 1], [1, 9, 9, 1, 0]]), "5", "A unique cheap cycle is surrounded by expensive edges."),
    _edge("six_city_equal", _tsp_input([[0 if i == j else 10 for j in range(6)] for i in range(6)]), "60", "Checks equal-cost tours at a larger size."),
    _edge("asymmetric_route_costs", _tsp_input([[0, 2, 20, 20], [2, 0, 3, 20], [20, 3, 0, 4], [20, 20, 4, 0]]), "29", "Checks a tour whose low-cost route follows a chain."),
    _edge("ten_city_upper_edge", _tsp_input([[0 if i == j else 1 for j in range(10)] for i in range(10)]), "10", "Exercises a larger bounded brute-force instance."),
]

TSP = {
    "scenario_id": "traveling_salesman", "name": "Traveling Salesman (brute force vs Held–Karp)",
    "statement": "Given a complete undirected weighted graph with n cities, find the minimum-cost tour that starts at city 0, visits every other city exactly once, and returns to city 0. Input is n, m=n*n, followed by the flattened n-by-n distance matrix. Distances are symmetric, the diagonal is zero, and off-diagonal weights are positive.",
    "constraints": ["2 <= n <= 12.", "m must equal n*n.", "0 <= distance[i][j] <= 1000.", "The matrix must be symmetric with a zero diagonal and positive off-diagonal entries."],
    "input_schema": TSP_SCHEMA, "generator_schema": TSP_SCHEMA,
    "student": TSP_BRUTE,
    "brute_force": _refs("Enumerate every permutation of cities 1..n-1 and return to city 0.", TSP_BRUTE, "O(n!)", "O(n) recursion stack"),
    "efficient": _refs("Held–Karp dynamic programming over visited-city subsets.", TSP_HELD_KARP, "O(n**2 * 2**n)", "O(n * 2**n) auxiliary"),
    "generator": {"language": "Python 3", "program": TSP_GENERATOR, "seeded": True, "max_n": 12, "symmetric_complete_graphs": True},
    "edge_cases": TSP_EDGES,
    "agent_responses": {
        "agent1": {"status": "ready", "candidates": [{"id": "traveling_salesman", "title": "Minimum-cost Hamiltonian tour", "problem_statement": "Find the least-cost tour through every city exactly once and back to city 0 in a complete weighted undirected graph.", "input_format": "n, m=n*n, then n*n row-major matrix entries", "output_format": "Minimum tour cost", "input_schema": TSP_SCHEMA, "evidence": ["The input contains a city count and a complete distance matrix."], "assumptions": ["Distances are symmetric, diagonal entries are zero, and off-diagonal weights are positive."], "confidence": 0.99}], "clarifying_questions": [], "constraints": ["2 <= n <= 12.", "m=n*n.", "The distance matrix is symmetric with a zero diagonal."], "limitations": ["Simulated Traveling Salesman reconstruction."]},
        "agent2": {"problem_summary": "Return the minimum Hamiltonian cycle cost starting and ending at city 0.", "assumptions": ["The graph is complete and undirected; each city is visited once."], "brute_force": _refs("Enumerate every permutation of cities 1..n-1.", TSP_BRUTE, "O(n!)", "O(n) recursion stack"), "efficient": _refs("Held–Karp subset dynamic programming.", TSP_HELD_KARP, "O(n**2 * 2**n)", "O(n * 2**n) auxiliary"), "limitations": ["Both implementations compute an exact optimum."]},
        "agent3a": {"generator_program": TSP_GENERATOR, "design_rationale": "Most seeded graphs stay in small and medium n for complete three-way comparisons; only a sparse upper ladder probes factorial growth.", "distributions": ["seeded_small_medium_complete_graph", "sparse_upper_growth_probe"], "size_strategy": "70% n=2..7, 20% n=8..9, and 10% probes at n=10..12.", "limitations": ["Generated matrices are schema checked and validated for symmetry; upper probes may reach the explicit brute-force benchmark cap."]},
        "agent3b": {"summary": "Check two-city tours, known small optima, equal weights, a planted cheap cycle, and a larger bounded graph.", "cases": TSP_EDGES, "limitations": ["Each proposed matrix is validated against the complete-graph contract before execution."]},
        "agent4": _agent4("Permutation enumeration and Held–Karp dynamic programming", "Brute force enumerates tours; Held–Karp caches best partial paths by visited subset and endpoint.", "n = number of cities", "O(n!)", "O(n!)", "O(n!)", "O(n)", "O(n)", "There are (n-1)! fixed-start tours; subset DP has O(n*2**n) states and O(n) transitions per state.", 1),
        "agent5": _proof("Held–Karp returns the minimum-cost tour that visits each city exactly once and returns to city 0.", "Induction on the number of visited cities in each subset state.", [_step("The base state has cost zero at city 0 with only city 0 visited.", "No edge has been traversed yet.", "dp[{0}][0] = 0"), _step("A state ending at j is the best prior state ending at some i followed by edge i-to-j.", "Every path to j has a unique penultimate city i.", "dp[S][j] = min_i(dp[S\\{j}][i] + w[i][j])"), _step("Closing each full-set state with its edge back to city 0 yields all valid tours.", "Every Hamiltonian cycle has one final city before returning to 0.", "answer = min_j(dp[All][j] + w[j][0])")]),
        "agent6": _quality("The exact reference implementations validate dimensions and weights, while Held–Karp avoids enumerating every complete tour.", ["The matrix dimensions are checked before indexing.", "The brute-force recursion fixes city 0 to avoid duplicate rotations.", "The DP uses explicit infinity and bounded subset masks."], TSP_BRUTE, (3, 3, 4)),
    },
}

def _bind_complexity_rubric_evidence(scenario: dict[str, Any]) -> None:
    response = scenario["agent_responses"]["agent4"]
    lines = scenario["student"].splitlines()
    line = next((i for i, text in enumerate(lines, 1) if "for (" in text or "while (" in text or "search(" in text or "dp[" in text), 1)
    response["grading_assessment"]["evidence"] = [{"line": line, "quote": lines[line - 1].strip()}]


for _scenario in (BINARY_SEARCH, SUBSET_SUM, FIBONACCI, TSP):
    _bind_complexity_rubric_evidence(_scenario)


SCENARIO_IDS = ("binary_search", "subset_sum", "fibonacci", "traveling_salesman")
DEMO_SCENARIOS = {
    "binary_search": BINARY_SEARCH,
    "subset_sum": SUBSET_SUM,
    "fibonacci": FIBONACCI,
    "traveling_salesman": TSP,
}
TASK_TO_AGENT = {
    TASK_RECONSTRUCTION: "agent1",
    TASK_REFERENCES: "agent2",
    TASK_RANDOM_GENERATOR: "agent3a",
    TASK_EDGE_CASES: "agent3b",
    TASK_COMPLEXITY: "agent4",
    TASK_MATHEMATICAL_PROOF: "agent5",
    TASK_CODE_QUALITY: "agent6",
}


def get_demo_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        return deepcopy(DEMO_SCENARIOS[scenario_id])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unknown Demo scenario: {scenario_id!r}") from exc


def select_demo_scenario(scenario_id: str | None = None) -> dict[str, Any]:
    """Pin a requested scenario, or select one for the whole submission."""
    return get_demo_scenario(scenario_id or secrets.choice(SCENARIO_IDS))


def validate_demo_input(scenario_id: str, text: str) -> bool:
    try:
        schema = StructuredIntegerInputSchema.from_dict(DEMO_SCENARIOS[scenario_id]["input_schema"])
        values = schema.parse(text)
    except (KeyError, TypeError, ValueError):
        return False
    if scenario_id == "binary_search":
        return values["values"] == sorted(values["values"])
    if scenario_id == "traveling_salesman":
        n, count, weights = values["n"], values["m"], values["weights"]
        if count != n * n:
            return False
        matrix = [weights[row * n:(row + 1) * n] for row in range(n)]
        return all(
            matrix[i][i] == 0
            and all(
                matrix[i][j] == matrix[j][i]
                and (i == j or matrix[i][j] > 0)
                for j in range(n)
            )
            for i in range(n)
        )
    return True


class _ResponseAdapter:
    def __init__(self, provider: "DemoScenarioProvider") -> None:
        self.provider = provider

    def generate_json(self, task: str, payload: dict, schema: dict) -> dict:
        return self.provider._response(task)


class DemoScenarioProvider:
    """Scenario-pinned provider with strict task routing and no live fallback."""
    mock_mode = True
    provider_name = "demo_scenario"

    def __init__(self, scenario_id: str) -> None:
        if scenario_id not in DEMO_SCENARIOS:
            raise AIProviderError(f"Unknown Demo scenario: {scenario_id!r}", category="demo_scenario_not_found")
        self.scenario_id = scenario_id
        self.scenario = DEMO_SCENARIOS[scenario_id]
        self.calls: list[str] = []
        self._guarded = GuardedProvider(_ResponseAdapter(self))

    def _response(self, task: str) -> dict[str, Any]:
        agent = TASK_TO_AGENT.get(task)
        if agent is None:
            raise AIProviderError(f"No Demo response is registered for task: {task}", category="demo_task_unmapped")
        response = self.scenario["agent_responses"].get(agent)
        if not isinstance(response, dict):
            raise AIProviderError(f"Demo response {agent} is missing for {self.scenario_id}.", category="demo_response_missing")
        self.calls.append(agent)
        response = deepcopy(response)
        if agent == "agent3b":
            response["cases"] = response.get("cases", [])[:8]
        return response

    def generate_json(self, task: str, payload: dict, schema: dict) -> dict:
        return self._guarded.generate_json(task, payload, schema)
