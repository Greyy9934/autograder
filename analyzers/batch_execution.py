"""Compile a C submission once, then execute a bounded batch of inputs."""
# It compares the student and reference programs fairly by giving them the same inputs and shared time limit.

import math
import os
import shutil
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


def benchmark_time_budget_for_case_count(case_count: int) -> float:
    """Scale the shared benchmark window with process-per-case overhead.

    Three separate C processes run for each input. A fixed two-second deadline
    leaves most of a 100-case batch unverified even when the inputs are small.
    Keep the window bounded so the request remains predictable on hosted servers.
    """
    # Chooses a fair shared time allowance based on how many cases are being run.
    # What the inputs mean:
    # - case_count: the case count used for this step.
    # What it gives back: It returns the float result.
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
        raise ValueError("case_count must be a positive integer.")
    return round(min(
        MAX_BENCHMARK_WINDOW_SECONDS,
        max(MIN_BENCHMARK_WINDOW_SECONDS, case_count * BENCHMARK_SECONDS_PER_CASE),
    ), 1)


def _classify_execution(run: dict[str, Any]) -> str:
    """Classify execution outcomes without confusing infrastructure with student errors."""
    # Handles classify execution as a supporting part of batch execution .
    # What the inputs mean:
    # - run: the run used for this step.
    # What it gives back: It returns text.
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


def _classify_benchmark_run(
    run: dict[str, Any],
    *,
    shared_budget_limited: bool,
) -> str:
    """Separate a global benchmark cutoff from a program's own time limit."""
    # Handles classify benchmark run as a supporting part of batch execution .
    # What the inputs mean:
    # - run: the run used for this step.
    # - shared_budget_limited: the shared budget limited used for this step.
    # What it gives back: It returns text.
    if run.get("status") == "timeout" and shared_budget_limited:
        return "benchmark_time_budget_exhausted"
    return _classify_execution(run)


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count each execution category for deterministic downstream reporting."""
    # Summarizes results.
    # What the inputs mean:
    # - results: the outcomes from an earlier step.
    # What it gives back: It returns a set of named results for the next step.
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

    def __init__(self, workers: int, budget_seconds: float):
        # Helps with init inside init.
        # What the inputs mean:
        # - workers: the workers used for this step.
        # - budget_seconds: the budget seconds used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.workers = workers
        self.budget_seconds = budget_seconds
        self.condition = threading.Condition()
        self.ready = 0
        self.started_at = None
        self.deadline = None
        self.aborted = False

    def abort(self):
        # Handles init as a supporting part of batch execution .
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        with self.condition:
            self.aborted = True
            self.condition.notify_all()

    def wait_until_all_ready(self):
        # Handles abort as a supporting part of batch execution .
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
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


def run_c_batch(
    source: str,
    inputs: list[str],
    *,
    time_budget_seconds: float | None = 10.0,
    _shared_gate: _SharedExecutionGate | None = None,
    stop_after_timeout: bool = False,
    per_case_timeout_seconds: float | None = None,
) -> dict[str, Any]:

    # Compiles one C program and runs it on each input while recording its output and timeouts.
    # What the inputs mean:
    # - source: the C code being checked.
    # - inputs: the inputs used for this step.
    # - time_budget_seconds: the shared time allowance for comparing the programs.
    # - _shared_gate: the shared gate used for this step.
    # - stop_after_timeout: the stop after timeout used for this step.
    # - per_case_timeout_seconds: the per case timeout seconds used for this step.
    # What it gives back: It returns a set of named results for the next step.
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
        try:
            os.chmod(work, 0o755)
        except OSError:
            pass
        source_path = work / "submission.c"
        executable_path = work / "submission"
        source_path.write_text(source, encoding="utf-8")

        gcc_bin = runner._get_gcc_bin()
        prlimit_bin = runner._get_prlimit_bin()

        if runner.is_bwrap_supported():
            bwrap_bin = shutil.which("bwrap") or "/usr/bin/bwrap"
            compile_command = [
                bwrap_bin,
                "--unshare-all", "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                *(["--ro-bind", "/lib64", "/lib64"] if Path("/lib64").exists() else []),
                *(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"] if Path("/etc/ld.so.cache").exists() else []),
                "--proc", "/proc", "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--bind", str(work), "/work",
                "--chdir", "/work",
                prlimit_bin or "/usr/bin/prlimit",
                f"--cpu={runner.COMPILE_TIMEOUT_SECONDS}:{runner.COMPILE_TIMEOUT_SECONDS + 1}",
                f"--as={runner.COMPILE_MEMORY_LIMIT_BYTES}:{runner.COMPILE_MEMORY_LIMIT_BYTES}",
                f"--fsize={runner.OUTPUT_LIMIT_BYTES}:{runner.OUTPUT_LIMIT_BYTES}",
                f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
                f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
                "--",
                gcc_bin, "-std=gnu17", "-Wall", "-Wextra", "-O2", "-lm",
                "/work/submission.c", "-o", "/work/submission",
            ]
            compile_preexec = None
            compile_cwd = runner.PROJECT_ROOT
        else:
            if prlimit_bin:
                compile_command = [
                    prlimit_bin,
                    f"--cpu={runner.COMPILE_TIMEOUT_SECONDS}:{runner.COMPILE_TIMEOUT_SECONDS + 1}",
                    f"--as={runner.COMPILE_MEMORY_LIMIT_BYTES}:{runner.COMPILE_MEMORY_LIMIT_BYTES}",
                    f"--fsize={runner.OUTPUT_LIMIT_BYTES}:{runner.OUTPUT_LIMIT_BYTES}",
                    f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
                    f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
                    "--",
                    gcc_bin, "-std=gnu17", "-Wall", "-Wextra", "-O2", "-lm",
                    str(source_path), "-o", str(executable_path),
                ]
                compile_preexec = None
            else:
                compile_command = [
                    gcc_bin, "-std=gnu17", "-Wall", "-Wextra", "-O2", "-lm",
                    str(source_path), "-o", str(executable_path),
                ]
                compile_preexec = runner._set_compile_limits
            compile_cwd = work

        compile_result = runner._run_bounded(
            compile_command,
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=runner.COMPILE_TIMEOUT_SECONDS,
            cwd=compile_cwd,
            preexec_fn=compile_preexec,
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

        try:
            executable_path.chmod(0o755)
        except OSError:
            pass

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

            if runner.is_bwrap_supported():
                bwrap_bin = shutil.which("bwrap") or "/usr/bin/bwrap"
                command = [
                    bwrap_bin,
                    "--unshare-all", "--die-with-parent",
                    "--ro-bind", "/usr", "/usr",
                    "--ro-bind", "/lib", "/lib",
                    *(["--ro-bind", "/lib64", "/lib64"] if Path("/lib64").exists() else []),
                    *(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"] if Path("/etc/ld.so.cache").exists() else []),
                    "--proc", "/proc", "--dev", "/dev",
                    "--tmpfs", "/tmp",
                    "--ro-bind", str(work), "/work",
                    "--chdir", "/work",
                    prlimit_bin or "/usr/bin/prlimit",
                    f"--cpu={runner.CPU_LIMIT_SECONDS}:{runner.CPU_LIMIT_SECONDS}",
                    f"--as={runner.MEMORY_LIMIT_BYTES}:{runner.MEMORY_LIMIT_BYTES}",
                    f"--fsize={runner.FILE_LIMIT_BYTES}:{runner.FILE_LIMIT_BYTES}",
                    f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
                    f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
                    "--",
                    "/work/submission",
                ]
                run_preexec = None
                run_cwd = runner.PROJECT_ROOT
            else:
                run_preexec = runner._get_runner_preexec(is_compile=False)
                if prlimit_bin:
                    command = [
                        prlimit_bin,
                        f"--cpu={runner.CPU_LIMIT_SECONDS}:{runner.CPU_LIMIT_SECONDS}",
                        f"--as={runner.MEMORY_LIMIT_BYTES}:{runner.MEMORY_LIMIT_BYTES}",
                        f"--fsize={runner.FILE_LIMIT_BYTES}:{runner.FILE_LIMIT_BYTES}",
                        f"--nproc={runner.MAX_PROCESSES}:{runner.MAX_PROCESSES}",
                        f"--nofile={runner.MAX_OPEN_FILES}:{runner.MAX_OPEN_FILES}",
                        "--",
                        str(executable_path),
                    ]
                else:
                    command = [str(executable_path)]
                run_cwd = work

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
                    cwd=run_cwd,
                    preexec_fn=run_preexec,
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
    # Chooses a useful run order: representative sizes first, more small and medium cases next, then remaining cases.
    # What the inputs mean:
    # - generated_cases: the test inputs produced for this run.
    # - max_ladder_points: the max ladder points used for this step.
    # What it gives back: It returns a small group of related values.
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


def benchmark_three_programs_parallel(
    student_source: str,
    brute_force_source: str,
    efficient_source: str,
    generated_cases: list[dict[str, Any]],
    *,
    time_budget_seconds: float = 2.0,
) -> dict[str, Any]:
    """Compile three programs, then execute them concurrently on one clock."""
    # Runs the student, brute-force, and efficient programs on the same inputs under one shared time limit.
    # What the inputs mean:
    # - student_source: the student’s C code.
    # - brute_force_source: the slow reference C code used on small cases.
    # - efficient_source: the faster reference C code.
    # - generated_cases: the test inputs produced for this run.
    # - time_budget_seconds: the shared time allowance for comparing the programs.
    # What it gives back: It returns a set of named results for the next step.
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
