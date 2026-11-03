"""Compile a C submission once, then execute a bounded batch of inputs."""
# Module role: Compiles once per program and compares bounded C executions under shared deadlines.

import math
import subprocess
import tempfile
import time
import threading
from pathlib import Path
from typing import Any

from app import runner
from analyzers.output_contract import normalize_stdout

BRUTE_FORCE_BENCHMARK_CASE_TIMEOUT_SECONDS = 0.75
MAX_BENCHMARK_SIZE_LADDER_POINTS = 16
MIN_BENCHMARK_WINDOW_SECONDS = 2.0
MAX_BENCHMARK_WINDOW_SECONDS = 10.0
BENCHMARK_SECONDS_PER_CASE = 0.1


# Function role: Scale the shared benchmark window with process-per-case overhead.
def benchmark_time_budget_for_case_count(case_count: int) -> float:
    """Scale the shared benchmark window with process-per-case overhead.

    Three separate C processes run for each input. A fixed two-second deadline
    leaves most of a 100-case batch unverified even when the inputs are small.
    Keep the window bounded so the request remains predictable on hosted servers.
    """
    # In-function documentation:
    # Parameters:
    #   - case_count: the case count value used by this operation (type annotation: int).
    # Returns: a value of declared type float.
    # Flow: branch on validation or workflow conditions; return the stage result.
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
        raise ValueError("case_count must be a positive integer.")
    return round(min(
        MAX_BENCHMARK_WINDOW_SECONDS,
        max(MIN_BENCHMARK_WINDOW_SECONDS, case_count * BENCHMARK_SECONDS_PER_CASE),
    ), 1)


# Function role: Classify execution outcomes without confusing infrastructure with student errors.
# Same-file callers: _classify_benchmark_run.
def _classify_execution(run: dict[str, Any]) -> str:
    """Classify execution outcomes without confusing infrastructure with student errors."""
    # In-function documentation:
    # Parameters:
    #   - run: the run value used by this operation (type annotation: dict[str, Any]).
    # Returns: a value of declared type str.
    # Flow: derive or store intermediate values; branch on validation or workflow conditions.
    status = run.get("status")

    if status == "launch_error":
        return "infrastructure_error"
    if status == "timeout":
        return "time_limit_exceeded"
    if status == "output_limit":
        return "output_limit_exceeded"
    if status == "resource_limit_or_forced_kill":
        return "resource_limit_exceeded"
    if status == "terminated_by_signal":
        return "runtime_crash"
    if status == "completed":
        if run.get("exit_code") == 0:
            return "program_success"
        if run.get("exit_code") is not None:
            return "runtime_error"
    return "execution_unknown"


# Function role: Separate a global benchmark cutoff from a program's own time limit.
# Same-file callers: run_c_batch.
# Direct call references (conditional/branch-dependent): _classify_execution.
def _classify_benchmark_run(
    run: dict[str, Any],
    *,
    shared_budget_limited: bool,
) -> str:
    """Separate a global benchmark cutoff from a program's own time limit."""
    # In-function documentation:
    # Parameters:
    #   - run: the run value used by this operation (type annotation: dict[str, Any]).
    #   - shared_budget_limited: the shared budget limited value used by this operation (type annotation: bool).
    # Returns: a value of declared type str; alternate return paths may produce the result of the final transformation or check.
    # Flow: branch on validation or workflow conditions; return the stage result.
    if run.get("status") == "timeout" and shared_budget_limited:
        return "benchmark_time_budget_exhausted"
    return _classify_execution(run)


# Function role: Count each execution category for deterministic downstream reporting.
# Same-file callers: run_c_batch.
def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count each execution category for deterministic downstream reporting."""
    # In-function documentation:
    # Parameters:
    #   - results: collected outputs, statuses, or evidence produced by an earlier stage (type annotation: list[dict[str, Any]]).
    # Returns: a value of declared type dict[str, int].
    # Flow: derive or store intermediate values; return the stage result.
    categories = (
        "program_success",
        "runtime_error",
        "runtime_crash",
        "time_limit_exceeded",
        "benchmark_time_budget_exhausted",
        "output_limit_exceeded",
        "resource_limit_exceeded",
        "infrastructure_error",
        "execution_unknown",
    )
    return {
        category: sum(
            item.get("execution_class") == category for item in results
        )
        for category in categories
    }


class _SharedExecutionGate:
    """Start all benchmark workers against one wall-clock deadline."""

    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by _SharedExecutionGate; it is reached through that object's workflow.
    def __init__(self, workers: int, budget_seconds: float):
        # In-function documentation:
        # Parameters:
        #   - workers: the workers value used by this operation (type annotation: int).
        #   - budget_seconds: the budget seconds value used by this operation (type annotation: float).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: derive or store intermediate values.
        self.workers = workers
        self.budget_seconds = budget_seconds
        self.condition = threading.Condition()
        self.ready = 0
        self.started_at = None
        self.deadline = None
        self.aborted = False

    # Function role: Implements abort for batch execution using this module's input and result contracts.
    # Context: method/helper owned by _SharedExecutionGate; it is reached through that object's workflow.
    # Same-file callers: run_c_batch.
    def abort(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: manage a scoped resource.
        with self.condition:
            self.aborted = True
            self.condition.notify_all()

    # Function role: Implements wait until all ready for batch execution using this module's input and result contracts.
    # Context: method/helper owned by _SharedExecutionGate; it is reached through that object's workflow.
    # Same-file callers: run_c_batch.
    def wait_until_all_ready(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a tuple containing the operation results.
        # Flow: manage a scoped resource.
        with self.condition:
            self.ready += 1
            if self.ready == self.workers:
                if not self.aborted:
                    self.started_at = time.monotonic()
                    self.deadline = self.started_at + self.budget_seconds
                self.condition.notify_all()
            else:
                self.condition.wait_for(
                    lambda: self.deadline is not None or self.aborted,
                    timeout=15.0,
                )

            if self.aborted or self.deadline is None:
                self.aborted = True
                self.condition.notify_all()
                return None

            return self.started_at, self.deadline


# Function role: Implements run c batch for batch execution using this module's input and result contracts.
# Direct call references (conditional/branch-dependent): abort, wait_until_all_ready, _classify_benchmark_run, _summarize_results.
def run_c_batch(
    source: str,
    inputs: list[str],
    *,
    time_budget_seconds: float | None = 10.0,
    _shared_gate: _SharedExecutionGate | None = None,
    stop_after_timeout: bool = False,
    per_case_timeout_seconds: float | None = None,
) -> dict[str, Any]:

    # In-function documentation:
    # Parameters:
    #   - source: the submitted or generated source text being analyzed or compiled (type annotation: str).
    #   - inputs: values supplied to the current parser or program (type annotation: list[str]).
    #   - time_budget_seconds: the time budget seconds value used by this operation (type annotation: float | None).
    #   - _shared_gate: the shared gate value used by this operation (type annotation: _SharedExecutionGate | None).
    #   - stop_after_timeout: the stop after timeout value used by this operation (type annotation: bool).
    #   - per_case_timeout_seconds: the per case timeout seconds value used by this operation (type annotation: float | None).
    # Returns: a value of declared type dict[str, Any].
    # Flow: branch on validation or workflow conditions.
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "results": []}

    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 1000:
        return {"status": "invalid_request", "results": []}

    if any(not isinstance(value, str) for value in inputs):
        return {"status": "invalid_request", "results": []}

    if time_budget_seconds is not None and (
        isinstance(time_budget_seconds, bool)
        or not isinstance(time_budget_seconds, (int, float))
        or not 0.1 <= time_budget_seconds <= 10.0
    ):
        return {"status": "invalid_request", "results": []}

    if per_case_timeout_seconds is not None and (
        isinstance(per_case_timeout_seconds, bool)
        or not isinstance(per_case_timeout_seconds, (int, float))
        or not 0.1 <= per_case_timeout_seconds <= 10.0
    ):
        return {"status": "invalid_request", "results": []}

    if len(source.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "results": []}

    if any(len(value.encode("utf-8")) > 256 * 1024 for value in inputs):
        return {"status": "invalid_request", "results": []}

    results = []
    timeout_stopped_early = False

    with tempfile.TemporaryDirectory(prefix="autograder-batch-") as temp:
        work = Path(temp)
        source_path = work / "submission.c"
        executable_path = work / "submission"
        source_path.write_text(source, encoding="utf-8")

        compile_command = [
            "/usr/bin/bwrap",
            "--unshare-all", "--die-with-parent",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
            "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", str(work), "/work",
            "--chdir", "/work",
            "/usr/bin/prlimit",
            f"--cpu={runner.COMPILE_TIMEOUT_SECONDS}:{runner.COMPILE_TIMEOUT_SECONDS + 1}",
            f"--as={runner.COMPILE_MEMORY_LIMIT_BYTES}:{runner.COMPILE_MEMORY_LIMIT_BYTES}",
            f"--fsize={runner.OUTPUT_LIMIT_BYTES}:{runner.OUTPUT_LIMIT_BYTES}",
            f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
            f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
            "--",
            "/usr/bin/gcc", "-std=gnu17", "-Wall", "-Wextra", "-O2", "-lm",
            "/work/submission.c", "-o", "/work/submission",
        ]

        compile_result = runner._run_bounded(
            compile_command,
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=runner.COMPILE_TIMEOUT_SECONDS,
            cwd=runner.PROJECT_ROOT,
        )

        if compile_result["status"] != "completed":
            if _shared_gate is not None:
                _shared_gate.abort()

            return {
                "status": "infrastructure_error"
                if compile_result["status"] == "launch_error"
                else "compile_inconclusive",
                "compile_status": compile_result["status"],
                "compiler_stderr": compile_result.get("stderr", ""),
                "message": compile_result.get("message"),
                "results": [],
            }

        if compile_result["exit_code"] != 0:
            if _shared_gate is not None:
                _shared_gate.abort()

            return {
                "status": "compile_failed",
                "compile_status": "compile_error",
                "compile_exit_code": compile_result["exit_code"],
                "compiler_stderr": compile_result.get("stderr", ""),
                "results": [],
            }

        if not executable_path.is_file():
            if _shared_gate is not None:
                _shared_gate.abort()

            return {
                "status": "compile_failed",
                "compile_status": "missing_executable",
                "results": [],
            }

        executable_path.chmod(0o555)

        # Start timing only after every implementation has compiled.
        if _shared_gate is not None:
            shared_window = _shared_gate.wait_until_all_ready()
            if shared_window is None:
                return {
                    "status": "benchmark_aborted",
                    "message": "A program failed to compile or benchmark coordination timed out.",
                    "results": [],
                }
            benchmark_started_at, deadline = shared_window
        else:
            benchmark_started_at = time.monotonic()
            deadline = (
                benchmark_started_at + time_budget_seconds
                if time_budget_seconds is not None else None
            )

        for index, value in enumerate(inputs, start=1):
            remaining = (
                None if deadline is None
                else deadline - time.monotonic()
            )
            if remaining is not None and remaining <= 0:
                break
            input_path = work / f"stdin-{index}.txt"
            input_path.write_text(value, encoding="utf-8")

            command = [
                "/usr/bin/bwrap",
                "--unshare-all", "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/lib64", "/lib64",
                "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
                "--proc", "/proc", "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--ro-bind", str(work), "/work",
                "--chdir", "/work",
                "/usr/bin/prlimit",
                f"--cpu={runner.CPU_LIMIT_SECONDS}:{runner.CPU_LIMIT_SECONDS}",
                f"--as={runner.MEMORY_LIMIT_BYTES}:{runner.MEMORY_LIMIT_BYTES}",
                f"--fsize={runner.FILE_LIMIT_BYTES}:{runner.FILE_LIMIT_BYTES}",
                f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
                f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
                "--",
                "/work/submission",
            ]

            case_timeout = (
                runner.RUN_TIMEOUT_SECONDS
                if per_case_timeout_seconds is None
                else float(per_case_timeout_seconds)
            )
            effective_timeout = (
                case_timeout
                if remaining is None
                else max(0.01, min(case_timeout, remaining))
            )
            with input_path.open("rb") as program_input:
                run = runner._run_bounded(
                    command,
                    stdin_file=program_input,
                    timeout_seconds=effective_timeout,
                    cwd=runner.PROJECT_ROOT,
                )

            shared_budget_limited = (
                _shared_gate is not None
                and remaining is not None
                and remaining < case_timeout - 0.05
            )
            execution_class = _classify_benchmark_run(
                run,
                shared_budget_limited=shared_budget_limited,
            )

            results.append({
                "case": index,
                "input": value,
                "status": run["status"],
                "execution_class": execution_class,
                "timeout_source": (
                    "shared_benchmark_budget"
                    if run["status"] == "timeout" and shared_budget_limited
                    else None
                ),
                "exit_code": run.get("exit_code"),
                "stdout": run.get("stdout", ""),
                "stderr": run.get("stderr", ""),
                "stdout_truncated": run.get("stdout_truncated", False),
                "stderr_truncated": run.get("stderr_truncated", False),
                "run_seconds": run.get("seconds"),
            })

            # A brute-force timeout is a useful empirical boundary: larger
            # instances of this same workload are unlikely to finish within
            # the same cap. Stop that reference here instead of burning the
            # remaining wall-clock budget on known-infeasible cases.
            if stop_after_timeout and execution_class == "time_limit_exceeded":
                timeout_stopped_early = True
                break

    summary = _summarize_results(results)
    has_issues = any(
        item["execution_class"] != "program_success"
        for item in results
    )

    return {
        "status": (
            "completed_with_execution_issues" if has_issues else "completed"
        ),
        "compile_seconds": compile_result["seconds"],
        "compiled_once": True,
        "executed": len(results),
        "timeout_stopped_early": timeout_stopped_early,
        "time_budget_seconds": time_budget_seconds,
        "execution_elapsed_seconds": round(
            time.monotonic() - benchmark_started_at, 6
        ),
        "time_budget_exhausted": bool(
            deadline is not None and time.monotonic() >= deadline
        ),
        "summary": summary,
        "results": results,
    }



# Function role: Prioritize one validated case per geometrically spaced workload size.
# Same-file callers: benchmark_three_programs_parallel.
def _adaptive_benchmark_case_order(
    generated_cases: list[dict[str, Any]],
    *,
    max_ladder_points: int = MAX_BENCHMARK_SIZE_LADDER_POINTS,
) -> tuple[list[int], list[int]]:
    """Prioritize one validated case per geometrically spaced workload size.

    The ladder selects one case per logarithmically spaced size, then a bounded
    set of additional low-size cases, before the upper probes and remaining
    cases. The brute-force worker may stop after an actual per-case timeout.
    """
    # In-function documentation:
    # Parameters:
    #   - generated_cases: the generated cases value used by this operation (type annotation: list[dict[str, Any]]).
    #   - max_ladder_points: the max ladder points value used by this operation (type annotation: int).
    # Returns: a value of declared type tuple[list[int], list[int]].
    # Flow: derive or store intermediate values; branch on validation or workflow conditions.
    sizes = [case["input_size"] for case in generated_cases]
    unique_sizes = sorted(set(sizes))
    if not unique_sizes:
        return list(range(len(generated_cases))), []

    ladder_count = min(max_ladder_points, len(unique_sizes))
    if ladder_count == len(unique_sizes):
        ladder_sizes = unique_sizes
    elif ladder_count == 1:
        ladder_sizes = [unique_sizes[0]]
    else:
        low, high = unique_sizes[0], unique_sizes[-1]
        candidates = set(unique_sizes)
        selected = []
        for position in range(ladder_count):
            low_shifted, high_shifted = low + 1, high + 1
            target = low_shifted * (high_shifted / low_shifted) ** (
                position / (ladder_count - 1)
            )
            chosen = min(
                candidates,
                key=lambda size: abs(math.log((size + 1) / target)),
            )
            selected.append(chosen)
            candidates.remove(chosen)
        ladder_sizes = sorted(selected)

    representative_by_size = {}
    for index, size in enumerate(sizes):
        representative_by_size.setdefault(size, index)

    ladder_representatives = [
        representative_by_size[size]
        for size in ladder_sizes
    ]
    # Spend a few additional executions on low/medium workloads before probing
    # the expensive upper end. The output shapes differ across random inputs at
    # the same n, so these repetitions add correctness value without sacrificing
    # the sparse growth ladder.
    midpoint = (len(ladder_sizes) - 1) // 2
    small_size_ceiling = ladder_sizes[midpoint]
    representative_set = set(ladder_representatives)
    small_repeats = [
        index for index in range(len(generated_cases))
        if index not in representative_set and sizes[index] <= small_size_ceiling
    ]
    if len(small_repeats) > max_ladder_points:
        if max_ladder_points == 1:
            small_repeats = small_repeats[:1]
        else:
            last = len(small_repeats) - 1
            small_repeats = [
                small_repeats[position * last // (max_ladder_points - 1)]
                for position in range(max_ladder_points)
            ]
    split = midpoint + 1
    prioritized = (
        ladder_representatives[:split]
        + small_repeats
        + ladder_representatives[split:]
    )
    prioritized_set = set(prioritized)
    # After the growth ladder, use smaller workloads first. This retains broad
    # correctness coverage when the shared time budget cannot reach every
    # duplicate/randomized sample.
    remaining = sorted(
        (index for index in range(len(generated_cases))
         if index not in prioritized_set),
        key=lambda index: (sizes[index], index),
    )
    return prioritized + remaining, ladder_sizes


# Function role: Compile three programs, then execute them concurrently on one clock.
# Numbered workflow order: 06.1 - same-case student/brute-force/efficient empirical comparison.
# Direct call references (conditional/branch-dependent): _adaptive_benchmark_case_order.
def benchmark_three_programs_parallel(
    student_source: str,
    brute_force_source: str,
    efficient_source: str,
    generated_cases: list[dict[str, Any]],
    *,
    time_budget_seconds: float = 2.0,
) -> dict[str, Any]:
    """Compile three programs, then execute them concurrently on one clock."""
    # In-function documentation:
    # Parameters:
    #   - student_source: the student program source used as the comparison candidate (type annotation: str).
    #   - brute_force_source: the brute-force reference source used to check correctness (type annotation: str).
    #   - efficient_source: the efficient reference source used to check correctness and performance (type annotation: str).
    #   - generated_cases: the generated cases value used by this operation (type annotation: list[dict[str, Any]]).
    #   - time_budget_seconds: the time budget seconds value used by this operation (type annotation: float).
    # Returns: a value of declared type dict[str, Any].
    # Flow: branch on validation or workflow conditions; derive or store intermediate values.
    from concurrent.futures import ThreadPoolExecutor

    if not isinstance(generated_cases, list) or not 1 <= len(generated_cases) <= 200:
        return {"status": "invalid_request", "message": "Expected 1-200 cases."}

    if (
        isinstance(time_budget_seconds, bool)
        or not isinstance(time_budget_seconds, (int, float))
        or not 0.1 <= time_budget_seconds <= 10.0
    ):
        return {"status": "invalid_request", "message": "Invalid time budget."}

    inputs = [
        case.get("input") if isinstance(case, dict) else None
        for case in generated_cases
    ]
    if any(not isinstance(value, str) for value in inputs):
        return {"status": "invalid_request", "message": "Inputs must be strings."}

    input_sizes = []
    for index, case in enumerate(generated_cases, 1):
        size = case.get("input_size") if isinstance(case, dict) else None
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            return {
                "status": "invalid_request",
                "message": (
                    f"Generated case {index} must provide a non-negative integer "
                    "input_size."
                ),
            }
        input_sizes.append(size)

    case_order, size_ladder = _adaptive_benchmark_case_order(
        generated_cases,
        max_ladder_points=MAX_BENCHMARK_SIZE_LADDER_POINTS,
    )
    representative_indices = {
        next(index for index, case in enumerate(generated_cases)
             if case["input_size"] == size)
        for size in size_ladder
    }
    small_size_ceiling = (
        size_ladder[(len(size_ladder) - 1) // 2]
        if size_ladder else -1
    )
    small_repeat_count = sum(
        1 for index, case in enumerate(generated_cases)
        if index not in representative_indices
        and case["input_size"] <= small_size_ceiling
    )
    prioritized_case_count = len(size_ladder) + min(
        MAX_BENCHMARK_SIZE_LADDER_POINTS, small_repeat_count
    )
    inputs = [inputs[index] for index in case_order]
    input_sizes = [input_sizes[index] for index in case_order]
    source_case_numbers = [index + 1 for index in case_order]

    programs = {
        "student": student_source,
        "brute_force": brute_force_source,
        "efficient": efficient_source,
    }
    if any(
        not isinstance(source, str)
        or not source.strip()
        or len(source.encode("utf-8")) > 256 * 1024
        for source in programs.values()
    ):
        return {"status": "invalid_request", "message": "Invalid C source."}

    if any(len(value.encode("utf-8")) > 256 * 1024 for value in inputs):
        return {"status": "invalid_request", "message": "Input too large."}

    gate = _SharedExecutionGate(3, float(time_budget_seconds))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            name: pool.submit(
                run_c_batch,
                source,
                inputs,
                time_budget_seconds=float(time_budget_seconds),
                _shared_gate=gate,
                stop_after_timeout=(name == "brute_force"),
                per_case_timeout_seconds=(
                    BRUTE_FORCE_BENCHMARK_CASE_TIMEOUT_SECONDS
                    if name == "brute_force" else None
                ),
            )
            for name, source in programs.items()
        }
        batches = {}
        for name, future in futures.items():
            try:
                batches[name] = future.result()
            except Exception as exc:
                batches[name] = {
                    "status": "worker_error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "results": [],
                }

    chart_data = []
    for name, batch in batches.items():
        for index, result in enumerate(batch.get("results", [])):
            if result.get("execution_class") == "program_success":
                chart_data.append({
                    "program": name,
                    "input_size": input_sizes[index],
                    "runtime_seconds": result.get("run_seconds"),
                    "case": source_case_numbers[index],
                    "benchmark_sequence": index + 1,
                })

    comparisons = []
    for index, input_value in enumerate(inputs):
        outcomes = {}
        for name in ("student", "brute_force", "efficient"):
            batch = batches[name]
            case_results = batch.get("results", [])
            if index < len(case_results):
                item = case_results[index]
                outcomes[name] = {
                    "execution_class": item.get("execution_class"),
                    "timeout_source": item.get("timeout_source"),
                    "exit_code": item.get("exit_code"),
                    "stdout": item.get("stdout", ""),
                    "stderr": item.get("stderr", ""),
                    "run_seconds": item.get("run_seconds"),
                }
            else:
                outcomes[name] = {
                    "execution_class": (
                        ("not_run_after_brute_force_timeout"
                         if name == "brute_force"
                         and batches[name].get("timeout_stopped_early")
                         else "not_executed_before_deadline")
                        if batch.get("compiled_once") is True
                        else batch.get("status") or "not_executed"
                    ),
                    "exit_code": None,
                    "stdout": "",
                    "stderr": batch.get("message", ""),
                    "run_seconds": None,
                }

        successful = all(
            outcomes[name]["execution_class"] == "program_success"
            for name in outcomes
        )
        outputs = [
            normalize_stdout(outcomes[name]["stdout"])
            for name in ("student", "brute_force", "efficient")
        ]
        comparisons.append({
            "case": source_case_numbers[index],
            "benchmark_sequence": index + 1,
            "input_size": input_sizes[index],
            "outcomes": outcomes,
            "outputs_agree": (
                len(set(outputs)) == 1 if successful else None
            ),
        })

    all_compiled = all(
        batch.get("compiled_once") is True for batch in batches.values()
    )
    all_batches_usable = all(
        batch.get("status") in (
            "completed", "completed_with_execution_issues"
        )
        for batch in batches.values()
    )

    return {
        "status": (
            "completed" if all_compiled and all_batches_usable
            else "incomplete"
        ),
        "time_budget_seconds": float(time_budget_seconds),
        "shared_execution_window": True,
        "case_order_strategy": "low_size_growth_ladder_with_small_repeats_then_upper_probes",
        "brute_force_case_timeout_seconds": BRUTE_FORCE_BENCHMARK_CASE_TIMEOUT_SECONDS,
        "prioritized_size_ladder": size_ladder,
        "prioritized_case_count": prioritized_case_count,
        "execution_elapsed_seconds": max(
            (batch.get("execution_elapsed_seconds", 0)
             for batch in batches.values()),
            default=0,
        ),
        "batches": batches,
        "chart_data": chart_data,
        "differential_comparisons": comparisons,
        "all_three_agreed_cases": sum(
            item["outputs_agree"] is True for item in comparisons
        ),
        "all_three_compiled": all_compiled,
        "all_batches_usable": all_batches_usable,
    }
