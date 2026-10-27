from __future__ import annotations

import os
import resource
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent

COMPILE_TIMEOUT_SECONDS = 10
RUN_TIMEOUT_SECONDS = 2

MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
COMPILE_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
OUTPUT_LIMIT_BYTES = 1024 * 1024
FILE_LIMIT_BYTES = 1024 * 1024
CPU_LIMIT_SECONDS = 5
MAX_PROCESSES = 32
MAX_OPEN_FILES = 64


def _set_compile_limits() -> None:
    """Apply basic resource limits to GCC and its immediate process."""
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (COMPILE_TIMEOUT_SECONDS, COMPILE_TIMEOUT_SECONDS + 1),
    )
    resource.setrlimit(
        resource.RLIMIT_AS,
        (COMPILE_MEMORY_LIMIT_BYTES, COMPILE_MEMORY_LIMIT_BYTES),
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (OUTPUT_LIMIT_BYTES, OUTPUT_LIMIT_BYTES),
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the process group, then force-kill it if necessary."""
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _capture_bounded(
    stream: Any,
    storage: bytearray,
    state: dict[str, bool],
    key: str,
) -> None:
    """Drain a pipe fully but retain at most OUTPUT_LIMIT_BYTES."""
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break

            remaining = OUTPUT_LIMIT_BYTES - len(storage)
            if remaining > 0:
                storage.extend(chunk[:remaining])

            if len(chunk) > max(remaining, 0):
                state[key] = True
    finally:
        stream.close()


def _run_bounded(
    command: list[str],
    *,
    stdin_file: Any,
    timeout_seconds: int,
    cwd: Path,
    preexec_fn: Any = None,
) -> dict[str, Any]:
    """Run a process with bounded output and prompt process-group cleanup."""
    stdout_data = bytearray()
    stderr_data = bytearray()
    state = {"stdout_truncated": False, "stderr_truncated": False}

    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            stdin=stdin_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,
            preexec_fn=preexec_fn,
        )
    except OSError as exc:
        return {
            "status": "launch_error",
            "message": str(exc),
            "seconds": round(time.monotonic() - started, 4),
        }

    stdout_thread = threading.Thread(
        target=_capture_bounded,
        args=(process.stdout, stdout_data, state, "stdout_truncated"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_capture_bounded,
        args=(process.stderr, stderr_data, state, "stderr_truncated"),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    deadline = started + timeout_seconds
    timed_out = False
    output_exceeded = False

    while process.poll() is None:
        if state["stdout_truncated"] or state["stderr_truncated"]:
            output_exceeded = True
            _kill_process_group(process)
            break

        if time.monotonic() >= deadline:
            timed_out = True
            _kill_process_group(process)
            break

        time.sleep(0.01)

    # Allow pipe readers to observe final output and finish.
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)

    # The output-limit condition takes priority if both events happened
    # close together. Check again after the reader threads have drained.
    output_exceeded = (
        output_exceeded
        or state["stdout_truncated"]
        or state["stderr_truncated"]
    )

    seconds = round(time.monotonic() - started, 4)
    return_code = process.poll()

    if output_exceeded:
        status = "output_limit"
    elif timed_out:
        status = "timeout"
    elif return_code is not None and return_code < 0:
        status = "terminated_by_signal"
    elif return_code in (137, 152):
        status = "resource_limit_or_forced_kill"
    else:
        status = "completed"

    return {
        "status": status,
        "exit_code": return_code,
        "seconds": seconds,
        "stdout": stdout_data.decode("utf-8", errors="replace"),
        "stdout_truncated": state["stdout_truncated"],
        "stderr": stderr_data.decode("utf-8", errors="replace"),
        "stderr_truncated": state["stderr_truncated"],
    }


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure every worker response has consistent output fields."""
    result.setdefault("stdout", "")
    result.setdefault("stderr", "")
    result.setdefault("stdout_truncated", False)
    result.setdefault("stderr_truncated", False)
    return result


def _run_c_program(source: str, stdin: str = "") -> dict[str, Any]:
    """
    Compile and execute C code using a restricted Bubblewrap workspace.

    This is a development worker, not a security-certified public sandbox.
    Compilation is resource-limited but is not yet inside Bubblewrap.
    """
    if not isinstance(source, str) or not source.strip():
        return {
            "status": "invalid_request",
            "message": "C source must be a non-empty string.",
        }

    if not isinstance(stdin, str):
        return {
            "status": "invalid_request",
            "message": "Program input must be a string.",
        }

    # Keep request sizes bounded before writing temporary files.
    if len(source.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "message": "Source exceeds 256 KiB."}

    if len(stdin.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "message": "Input exceeds 256 KiB."}

    with tempfile.TemporaryDirectory(prefix="autograder-job-") as temp:
        work = Path(temp)
        source_path = work / "submission.c"
        executable_path = work / "submission"
        input_path = work / "stdin.txt"

        source_path.write_text(source, encoding="utf-8")
        input_path.write_text(stdin, encoding="utf-8")

        with input_path.open("rb") as program_input:
            compile_result = _run_bounded(
                [
                    "/usr/bin/gcc",
                    "-std=c17",
                    "-Wall",
                    "-Wextra",
                    "-O2",
                    str(source_path),
                    "-o",
                    str(executable_path),
                ],
                stdin_file=subprocess.DEVNULL,
                timeout_seconds=COMPILE_TIMEOUT_SECONDS,
                cwd=work,
                preexec_fn=_set_compile_limits,
            )

        if compile_result["status"] == "timeout":
            return {
                "status": "compile_timeout",
                "message": "Compilation exceeded its time limit.",
                "compiler_stderr": compile_result["stderr"],
            }

        if compile_result["status"] != "completed":
            return {
                "status": "compiler_error",
                "message": "Compiler process could not complete normally.",
                "compiler_stderr": compile_result.get("stderr", ""),
                "compiler_stdout": compile_result.get("stdout", ""),
                "compiler_status": compile_result["status"],
            }

        if compile_result["exit_code"] != 0:
            return {
                "status": "compile_error",
                "compile_exit_code": compile_result["exit_code"],
                "compiler_stderr": compile_result["stderr"],
                "compiler_stdout": compile_result["stdout"],
                "compiler_stderr_truncated": compile_result["stderr_truncated"],
                "compile_seconds": compile_result["seconds"],
            }

        sandbox_command = [
            "/usr/bin/bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", str(work), "/work",
            "--chdir", "/work",
            "/usr/bin/prlimit",
            f"--cpu={CPU_LIMIT_SECONDS}:{CPU_LIMIT_SECONDS}",
            f"--as={MEMORY_LIMIT_BYTES}:{MEMORY_LIMIT_BYTES}",
            f"--fsize={FILE_LIMIT_BYTES}:{FILE_LIMIT_BYTES}",
            f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
            f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
            "--",
            "/work/submission",
        ]

        with input_path.open("rb") as program_input:
            run_result = _run_bounded(
                sandbox_command,
                stdin_file=program_input,
                timeout_seconds=RUN_TIMEOUT_SECONDS,
                cwd=PROJECT_ROOT,
            )

        if run_result["status"] == "launch_error":
            return {
                "status": "sandbox_error",
                "message": run_result["message"],
                "compile_seconds": compile_result["seconds"],
            }

        return {
            "status": run_result["status"],
            "compile_exit_code": compile_result["exit_code"],
            "compile_seconds": compile_result["seconds"],
            "run_seconds": run_result["seconds"],
            "exit_code": run_result["exit_code"],
            "stdout": run_result["stdout"],
            "stdout_truncated": run_result["stdout_truncated"],
            "stderr": run_result["stderr"],
            "stderr_truncated": run_result["stderr_truncated"],
        }


def run_c_program(source: str, stdin: str = "") -> dict[str, Any]:
    """Public worker API with a consistent result shape."""
    result = _run_c_program(source, stdin)
    return _normalize_result(result)
