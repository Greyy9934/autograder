"""Controlled empirical runtime measurements for C submissions.

Measurements reuse the isolated batch runner. They are observations, not
proofs of asymptotic complexity.
"""
# Module role: Implements the complexity benchmark subsystem used by the AutoGrader workflow.

import hashlib
import math
import statistics
from typing import Any

from analyzers.batch_execution import run_c_batch


MAX_BENCHMARK_CASES = 100
MAX_REPETITIONS = 10
MAX_TOTAL_RUNS = 1000


# Function role: Measure runtime for explicitly supplied input sizes and inputs.
def benchmark_complexity(
    source: str,
    benchmark_cases: list[dict[str, Any]],
    repetitions: int = 3,
) -> dict[str, Any]:
    """Measure runtime for explicitly supplied input sizes and inputs.

    Each benchmark case must contain:
      - input_size: a positive integer describing the problem size
      - input: the exact stdin string for that size

    The caller is responsible for ensuring that input_size meaningfully
    describes the supplied input. No inputs are generated automatically.
    """
    invalid = {
        "status": "invalid_request",
        "results": [],
        "chart_data": [],
        "growth_observations": [],
        "message": "Provide valid source, benchmark cases, and repetitions.",
    }

    if not isinstance(source, str) or not source.strip():
        return invalid

    if (
        not isinstance(repetitions, int)
        or isinstance(repetitions, bool)
        or not 1 <= repetitions <= MAX_REPETITIONS
    ):
        return invalid

    if (
        not isinstance(benchmark_cases, list)
        or not 1 <= len(benchmark_cases) <= MAX_BENCHMARK_CASES
    ):
        return invalid

    if len(benchmark_cases) * repetitions > MAX_TOTAL_RUNS:
        return invalid

    normalized_cases = []
    seen_sizes = set()

    for case in benchmark_cases:
        if not isinstance(case, dict):
            return invalid

        size = case.get("input_size")
        input_text = case.get("input")

        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size in seen_sizes
            or not isinstance(input_text, str)
        ):
            return invalid

        seen_sizes.add(size)
        normalized_cases.append({
            "input_size": size,
            "input": input_text,
        })

    normalized_cases.sort(key=lambda item: item["input_size"])

    flattened_inputs = []
    run_metadata = []

    for case in normalized_cases:
        for repetition in range(1, repetitions + 1):
            flattened_inputs.append(case["input"])
            run_metadata.append({
                "input_size": case["input_size"],
                "repetition": repetition,
            })

    batch = run_c_batch(source, flattened_inputs)

    if not isinstance(batch, dict):
        return {
            **invalid,
            "status": "execution_unknown",
            "message": "The batch runner returned an invalid response.",
        }

    if batch.get("status") not in {
        "completed",
        "completed_with_execution_issues",
    }:
        return {
            "status": batch.get("status", "execution_unknown"),
            "compile_status": batch.get("compile_status"),
            "compiler_stderr": batch.get("compiler_stderr", ""),
            "compiled_once": batch.get("compiled_once", False),
            "compile_seconds": batch.get("compile_seconds"),
            "results": [],
            "chart_data": [],
            "growth_observations": [],
            "message": (
                "Benchmark execution did not complete. No runtime growth "
                "conclusion is available."
            ),
            "limitations": [
                "Compilation or infrastructure failure prevents runtime comparison."
            ],
        }

    batch_results = batch.get("results")
    if not isinstance(batch_results, list) or len(batch_results) != len(run_metadata):
        return {
            **invalid,
            "status": "execution_unknown",
            "message": "The batch runner returned incomplete execution results.",
        }

    grouped = {
        case["input_size"]: {
            "input_size": case["input_size"],
            "successful_times": [],
            "runs": [],
        }
        for case in normalized_cases
    }

    for metadata, run in zip(run_metadata, batch_results):
        if not isinstance(run, dict):
            run = {}

        execution_class = run.get("execution_class", "execution_unknown")
        seconds = run.get("run_seconds")

        valid_time = (
            isinstance(seconds, (int, float))
            and not isinstance(seconds, bool)
            and math.isfinite(seconds)
            and seconds >= 0
        )
        successful = (
            execution_class == "program_success"
            and run.get("exit_code") == 0
            and valid_time
        )

        observation = {
            "input_size": metadata["input_size"],
            "repetition": metadata["repetition"],
            "execution_class": execution_class,
            "exit_code": run.get("exit_code"),
            "run_seconds": float(seconds) if valid_time else None,
            "included_in_timing": successful,
        }

        grouped[metadata["input_size"]]["runs"].append(observation)

        if successful:
            grouped[metadata["input_size"]]["successful_times"].append(
                float(seconds)
            )

    results = []
    chart_data = []

    for size in sorted(grouped):
        group = grouped[size]
        times = group["successful_times"]

        item = {
            "input_size": size,
            "requested_repetitions": repetitions,
            "successful_runs": len(times),
            "failed_runs": repetitions - len(times),
            "median_runtime_seconds": statistics.median(times) if times else None,
            "minimum_runtime_seconds": min(times) if times else None,
            "maximum_runtime_seconds": max(times) if times else None,
            "runs": group["runs"],
        }
        results.append(item)

        if times:
            chart_data.append({
                "input_size": size,
                "median_runtime_seconds": statistics.median(times),
            })

    growth_observations = []
    for previous, current in zip(results, results[1:]):
        previous_time = previous["median_runtime_seconds"]
        current_time = current["median_runtime_seconds"]

        growth_observations.append({
            "from_input_size": previous["input_size"],
            "to_input_size": current["input_size"],
            "input_size_ratio": (
                current["input_size"] / previous["input_size"]
            ),
            "runtime_ratio": (
                current_time / previous_time
                if previous_time is not None
                and current_time is not None
                and previous_time > 0
                else None
            ),
            "interpretation": (
                "Observed ratio only; not an asymptotic complexity proof."
            ),
        })

    has_failures = any(item["failed_runs"] for item in results)

    return {
        "status": (
            "completed_with_execution_issues" if has_failures else "completed"
        ),
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "compiled_once": batch.get("compiled_once", False),
        "compile_seconds": batch.get("compile_seconds"),
        "repetitions_per_size": repetitions,
        "results": results,
        "chart_data": chart_data,
        "growth_observations": growth_observations,
        "measurement_method": "isolated_process_wall_clock",
        "measurement_scope": (
            "Elapsed process time includes sandbox/process startup overhead; "
            "it is not CPU-only algorithm time."
        ),
        "interpretation": (
            "Empirical observations for the supplied inputs only. "
            "They do not prove Big-O complexity or correctness."
        ),
        "limitations": [
            "Input sizes and matching input strings are supplied by the caller.",
            "The benchmark does not verify that input_size accurately describes the input.",
            "Process and sandbox startup overhead is included in each measurement.",
            "Short runtimes are sensitive to operating-system scheduling and timing noise.",
            "Only successful executions with valid elapsed times enter timing statistics.",
            "Compilation time is reported separately and excluded from runtime statistics.",
            "Observed runtime ratios are not proofs of asymptotic complexity.",
        ],
        "message": (
            "Benchmark measurements completed. Review execution failures, "
            "input construction, and timing limitations before interpretation."
        ),
    }
