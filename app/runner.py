from __future__ import annotations
# Module role: Compiles and executes C in a Linux Bubblewrap namespace with prlimit resource bounds and bounded output capture.
# Core concept: Bubblewrap creates Linux namespaces and a narrow filesystem view; prlimit applies OS resource ceilings. Together these reduce access and runaway-process risk, but do not certify the worker as a secure multi-tenant sandbox.

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


# Function role: Apply basic resource limits to GCC and its immediate process.
def _set_compile_limits() -> None:
    """Apply basic resource limits to GCC and its immediate process."""
    # In-function documentation:
    # Parameters: none.
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: delegate work to a helper or external boundary.
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


# Function role: Terminate the process group, then force-kill it if necessary.
# Same-file callers: _run_bounded.
def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the process group, then force-kill it if necessary."""
    # In-function documentation:
    # Parameters:
    #   - process: child process handle whose status, pipes, and lifecycle are managed (type annotation: subprocess.Popen[bytes]).
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: branch on validation or workflow conditions; convert expected failures into controlled results.
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


# Function role: Drain a pipe fully but retain at most OUTPUT_LIMIT_BYTES.
def _capture_bounded(
    stream: Any,
    storage: bytearray,
    state: dict[str, bool],
    key: str,
) -> None:
    """Drain a pipe fully but retain at most OUTPUT_LIMIT_BYTES."""
    # In-function documentation:
    # Parameters:
    #   - stream: readable pipe connected to the child process, usually stdout or stderr (type annotation: Any).
    #   - storage: mutable output buffer retaining bounded captured data (type annotation: bytearray).
    #   - state: shared mutable status flags, including output truncation state (type annotation: dict[str, bool]).
    #   - key: mapping key naming the value to read or update (type annotation: str).
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: convert expected failures into controlled results.
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


# Function role: Runs one child process with a deadline, starts a separate process group, drains both pipes concurrently, caps retained output, and kills descendants on timeout or output overflow.
# Same-file callers: compile_c_source, _run_c_program.
# Direct call references (conditional/branch-dependent): _kill_process_group.
def _run_bounded(
    command: list[str],
    *,
    stdin_file: Any,
    timeout_seconds: int,
    cwd: Path,
    preexec_fn: Any = None,
) -> dict[str, Any]:
    """Run a process with bounded output and prompt process-group cleanup."""
    # In-function documentation:
    # Parameters:
    #   - command: the executable and arguments launched for this bounded process (type annotation: list[str]).
    #   - stdin_file: the stdin file value used by this operation (type annotation: Any).
    #   - timeout_seconds: the timeout seconds value used by this operation (type annotation: int).
    #   - cwd: the cwd value used by this operation (type annotation: Path).
    #   - preexec_fn: the preexec fn value used by this operation (type annotation: Any).
    # Returns: a value of declared type dict[str, Any].
    # Flow: derive or store intermediate values.
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


# Function role: Ensure every worker response has consistent output fields.
# Same-file callers: run_c_program.
def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure every worker response has consistent output fields."""
    # In-function documentation:
    # Parameters:
    #   - result: the result value used by this operation (type annotation: dict[str, Any]).
    # Returns: a value of declared type dict[str, Any].
    # Flow: delegate work to a helper or external boundary.
    result.setdefault("stdout", "")
    result.setdefault("stderr", "")
    result.setdefault("stdout_truncated", False)
    result.setdefault("stderr_truncated", False)
    return result


# Function role: Compiles C17 with GCC inside Bubblewrap: Linux namespaces isolate the job, read-only system mounts expose only required libraries, a temporary work mount holds source/binary, and prlimit bounds CPU, address space, file size, process count, and descriptors. This is defense-in-depth, not a certified hostile-code sandbox.
# Numbered workflow order: 02.1b - compile gate; also reused before local C execution.
# Direct call references (conditional/branch-dependent): _run_bounded.
def compile_c_source(source: str) -> dict[str, Any]:
    """Compile C in the restricted sandbox without executing the submission."""
    # In-function documentation:
    # Parameters:
    #   - source: the submitted or generated source text being analyzed or compiled (type annotation: str).
    # Returns: a value of declared type dict[str, Any].
    # Flow: branch on validation or workflow conditions; manage a scoped resource.
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "message": "C source must be a non-empty string."}
    if len(source.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "message": "Source exceeds 256 KiB."}

    with tempfile.TemporaryDirectory(prefix="autograder-compile-") as temp:
        work = Path(temp)
        (work / "submission.c").write_text(source, encoding="utf-8")
        command = [
            "/usr/bin/bwrap", "--unshare-all", "--die-with-parent",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--bind", str(work), "/work", "--chdir", "/work",
            "/usr/bin/prlimit",
            f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
            f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
            f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
            f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
            f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
            "--", "/usr/bin/gcc", "-std=gnu17", "-Wall", "-Wextra",
            "-Wformat=2", "-Warray-bounds=2", "-Wnull-dereference", "-fanalyzer",
            "-O2", "-lm",
            "/work/submission.c", "-o", "/work/submission",
        ]
        result = _run_bounded(
            command, stdin_file=subprocess.DEVNULL,
            timeout_seconds=COMPILE_TIMEOUT_SECONDS, cwd=PROJECT_ROOT,
        )

    if result["status"] == "launch_error":
        return {"status": "sandbox_error", "message": result.get("message", "Compiler sandbox could not be launched.")}
    if result["status"] == "timeout":
        return {"status": "compile_timeout", "compiler_stderr": result.get("stderr", "")}
    if result["status"] != "completed":
        return {
            "status": "compiler_error",
            "compiler_status": result["status"],
            "compiler_stderr": result.get("stderr", ""),
            "compiler_stdout": result.get("stdout", ""),
        }
    if result["exit_code"] != 0:
        return {
            "status": "compile_error",
            "compile_exit_code": result["exit_code"],
            "compiler_stderr": result["stderr"],
            "compiler_stdout": result["stdout"],
            "compile_seconds": result["seconds"],
        }
    return {
        "status": "compiled",
        "compile_exit_code": 0,
        "compile_seconds": result["seconds"],
        "compiler_stderr": result["stderr"],
        "compiler_stdout": result["stdout"],
    }


# Function role: Compiles and executes a submission in separate Bubblewrap namespaces, passes stdin through a file, and returns bounded stdout/stderr plus compile/run status and timing.
# Same-file callers: run_c_program.
# Direct call references (conditional/branch-dependent): _run_bounded.
def _run_c_program(source: str, stdin: str = "") -> dict[str, Any]:
    """
    Compile and execute C code using a restricted Bubblewrap workspace.

    This is a development worker, not a security-certified public sandbox.
    Compilation and execution run inside separate Bubblewrap namespaces.
    """
    # In-function documentation:
    # Parameters:
    #   - source: the submitted or generated source text being analyzed or compiled (type annotation: str).
    #   - stdin: the stdin value used by this operation (type annotation: str); defaults to '' when omitted.
    # Returns: a value of declared type dict[str, Any].
    # Flow: branch on validation or workflow conditions.
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

        compile_command = [
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
            f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
            f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
            f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
            f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
            f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
            "--",
            "/usr/bin/gcc",
            "-std=gnu17",
            "-Wall",
            "-Wextra",
            "-O2", "-lm",
            "/work/submission.c",
            "-o",
            "/work/submission",
        ]

        compile_result = _run_bounded(
            compile_command,
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=COMPILE_TIMEOUT_SECONDS,
            cwd=PROJECT_ROOT,
        )

        if compile_result["status"] == "launch_error":
            return {
                "status": "sandbox_error",
                "message": compile_result.get(
                    "message", "The compiler sandbox could not be launched."
                ),
            }

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


# Function role: Public worker API with a consistent result shape.
# Direct call references (conditional/branch-dependent): _run_c_program, _normalize_result.
def run_c_program(source: str, stdin: str = "") -> dict[str, Any]:
    """Public worker API with a consistent result shape."""
    # In-function documentation:
    # Parameters:
    #   - source: the submitted or generated source text being analyzed or compiled (type annotation: str).
    #   - stdin: the stdin value used by this operation (type annotation: str); defaults to '' when omitted.
    # Returns: a value of declared type dict[str, Any].
    # Flow: derive or store intermediate values; return the stage result.
    result = _run_c_program(source, stdin)
    return _normalize_result(result)
