"""Compile a C submission once, then execute a bounded batch of inputs."""

import math
import subprocess
import tempfile
import time
import threading
from pathlib import Path
from typing import Any

from app import runner



def _classify_execution(run: dict[str, Any]) -> str:
    """Classify execution outcomes without confusing infrastructure with student errors."""
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
    if run.get("status") == "timeout" and shared_budget_limited:
        return "benchmark_time_budget_exhausted"
    return _classify_execution(run)


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count each execution category for deterministic downstream reporting."""
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
        self.workers = workers
        self.budget_seconds = budget_seconds
        self.condition = threading.Condition()
        self.ready = 0
        self.started_at = None
        self.deadline = None
        self.aborted = False

    def abort(self):
        with self.condition:
            self.aborted = True
            self.condition.notify_all()

    def wait_until_all_ready(self):
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
) -> dict[str, Any]:

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

    if len(source.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "results": []}

    if any(len(value.encode("utf-8")) > 256 * 1024 for value in inputs):
        return {"status": "invalid_request", "results": []}

    results = []

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

            effective_timeout = (
                runner.RUN_TIMEOUT_SECONDS
                if remaining is None
                else max(0.01, min(runner.RUN_TIMEOUT_SECONDS, remaining))
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
                and remaining < runner.RUN_TIMEOUT_SECONDS - 0.05
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
        "time_budget_seconds": time_budget_seconds,
        "execution_elapsed_seconds": round(
            time.monotonic() - benchmark_started_at, 6
        ),
        "time_budget_exhausted": bool(
            deadline is not None and (
                time.monotonic() >= deadline
                or len(results) < len(inputs)
            )
        ),
        "summary": summary,
        "results": results,
    }



def _adaptive_benchmark_case_order(
    generated_cases: list[dict[str, Any]],
    *,
    max_ladder_points: int = 16,
) -> tuple[list[int], list[int]]:
    """Prioritize one validated case per geometrically spaced workload size.

    All generated cases remain in the run. The ladder only changes execution
    order so a shared wall-clock cap samples the full size range before
    repeated cases consume the budget.
    """
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

    prioritized = [
        representative_by_size[size]
        for size in ladder_sizes
    ]
    prioritized_set = set(prioritized)
    remaining = [
        index for index in range(len(generated_cases))
        if index not in prioritized_set
    ]
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

    case_order, size_ladder = _adaptive_benchmark_case_order(generated_cases)
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
                        "not_executed_before_deadline"
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
            outcomes[name]["stdout"].strip()
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
        "case_order_strategy": "geometric_size_ladder_then_remaining_generated_cases",
        "prioritized_size_ladder": size_ladder,
        "prioritized_case_count": len(size_ladder),
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
