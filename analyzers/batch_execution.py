"""Compile a C submission once, then execute a bounded batch of inputs."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app import runner


def run_c_batch(source: str, inputs: list[str]) -> dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "results": []}

    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 1000:
        return {"status": "invalid_request", "results": []}

    if any(not isinstance(value, str) for value in inputs):
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
            "/usr/bin/gcc", "-std=c17", "-Wall", "-Wextra", "-O2",
            "/work/submission.c", "-o", "/work/submission",
        ]

        compile_result = runner._run_bounded(
            compile_command,
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=runner.COMPILE_TIMEOUT_SECONDS,
            cwd=runner.PROJECT_ROOT,
        )

        if compile_result["status"] != "completed":
            return {
                "status": "compile_failed",
                "compile_status": compile_result["status"],
                "compiler_stderr": compile_result.get("stderr", ""),
                "results": [],
            }

        if compile_result["exit_code"] != 0:
            return {
                "status": "compile_failed",
                "compile_status": "compile_error",
                "compile_exit_code": compile_result["exit_code"],
                "compiler_stderr": compile_result.get("stderr", ""),
                "results": [],
            }

        if not executable_path.is_file():
            return {
                "status": "compile_failed",
                "compile_status": "missing_executable",
                "results": [],
            }

        if not executable_path.is_file():
            return {
                "status": "compile_failed",
                "compile_status": "missing_executable",
                "results": [],
            }

        executable_path.chmod(0o555)

        for index, value in enumerate(inputs, start=1):
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

            with input_path.open("rb") as program_input:
                run = runner._run_bounded(
                    command,
                    stdin_file=program_input,
                    timeout_seconds=runner.RUN_TIMEOUT_SECONDS,
                    cwd=runner.PROJECT_ROOT,
                )

            results.append({
                "case": index,
                "input": value,
                "status": run["status"],
                "exit_code": run.get("exit_code"),
                "stdout": run.get("stdout", ""),
                "stderr": run.get("stderr", ""),
                "stdout_truncated": run.get("stdout_truncated", False),
                "stderr_truncated": run.get("stderr_truncated", False),
                "run_seconds": run.get("seconds"),
            })

    return {
        "status": "completed",
        "compile_seconds": compile_result["seconds"],
        "compiled_once": True,
        "executed": len(results),
        "results": results,
    }
