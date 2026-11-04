from __future__ import annotations
# It compiles and runs C code with limits so a slow or noisy program cannot take over the server.

import os
import resource
import shutil
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


def is_bwrap_supported() -> bool:
    """Check if bubblewrap binary exists AND can create unprivileged namespaces."""
    if os.getenv("AUTOGRADER_FORCE_NO_BWRAP", "").lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("RENDER") == "true" or os.getenv("AUTOGRADER_CONTAINER_SANDBOX", "").lower() in {"1", "true", "yes"}:
        return False
    return True


def _get_gcc_bin() -> str:
    return "/usr/bin/gcc" if Path("/usr/bin/gcc").exists() else (shutil.which("gcc") or "/usr/bin/gcc")


def _get_prlimit_bin() -> str | None:
    found = "/usr/bin/prlimit" if Path("/usr/bin/prlimit").exists() else shutil.which("prlimit")
    return str(found) if found else None


def _set_compile_limits() -> None:
    """Apply basic resource limits to GCC and its immediate process."""
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (COMPILE_TIMEOUT_SECONDS, COMPILE_TIMEOUT_SECONDS + 1),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (COMPILE_MEMORY_LIMIT_BYTES, COMPILE_MEMORY_LIMIT_BYTES),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (OUTPUT_LIMIT_BYTES, OUTPUT_LIMIT_BYTES),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
    except (ValueError, OSError, AttributeError):
        pass


def _set_runtime_limits() -> None:
    """Apply basic resource limits to submission runtime."""
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS + 1),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (FILE_LIMIT_BYTES, FILE_LIMIT_BYTES),
        )
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
    except (ValueError, OSError, AttributeError):
        pass


def _get_runner_preexec(is_compile: bool = False):
    def _preexec():
        if is_compile:
            _set_compile_limits()
        else:
            _set_runtime_limits()
        try:
            import pwd
            if os.geteuid() == 0:
                user_info = pwd.getpwnam("runner_user")
                os.setgroups([])
                os.setgid(user_info.pw_gid)
                os.setuid(user_info.pw_uid)
        except (KeyError, PermissionError, OSError, AttributeError):
            pass
    return _preexec


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the process group, then force-kill it if necessary."""
    # Handles kill process group as a supporting part of runner .
    # What the inputs mean:
    # - process: the process used for this step.
    # What it gives back: It does its work and does not return a value.
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
    # Reads program output while keeping only a safe amount in memory.
    # What the inputs mean:
    # - stream: the stream used for this step.
    # - storage: the storage used for this step.
    # - state: the state used for this step.
    # - key: the label used to find an item in a collection.
    # What it gives back: It does its work and does not return a value.
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
    # Starts a program with limits and stops it if it runs too long or produces too much output.
    # What the inputs mean:
    # - command: the command used to start a program.
    # - stdin_file: the stdin file used for this step.
    # - timeout_seconds: the maximum time allowed for this run.
    # - cwd: the cwd used for this step.
    # - preexec_fn: the preexec fn used for this step.
    # What it gives back: It returns a set of named results for the next step.
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
    # Cleans up result.
    # What the inputs mean:
    # - result: the result used for this step.
    # What it gives back: It returns a set of named results for the next step.
    result.setdefault("stdout", "")
    result.setdefault("stderr", "")
    result.setdefault("stdout_truncated", False)
    result.setdefault("stderr_truncated", False)
    return result


def compile_c_source(source: str) -> dict[str, Any]:
    """Compile C in the restricted sandbox without executing the submission."""
    # Handles compile c source as a supporting part of runner .
    # What the inputs mean:
    # - source: the C code being checked.
    # What it gives back: It returns a set of named results for the next step.
    if not isinstance(source, str) or not source.strip():
        return {"status": "invalid_request", "message": "C source must be a non-empty string."}
    if len(source.encode("utf-8")) > 256 * 1024:
        return {"status": "invalid_request", "message": "Source exceeds 256 KiB."}

    gcc_bin = _get_gcc_bin()
    prlimit_bin = _get_prlimit_bin()

    with tempfile.TemporaryDirectory(prefix="autograder-compile-") as temp:
        work = Path(temp)
        source_path = work / "submission.c"
        executable_path = work / "submission"
        source_path.write_text(source, encoding="utf-8")

        if is_bwrap_supported():
            bwrap_bin = shutil.which("bwrap") or "/usr/bin/bwrap"
            command = [
                bwrap_bin, "--unshare-all", "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                *(["--ro-bind", "/lib64", "/lib64"] if Path("/lib64").exists() else []),
                *(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"] if Path("/etc/ld.so.cache").exists() else []),
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                "--bind", str(work), "/work", "--chdir", "/work",
                prlimit_bin or "/usr/bin/prlimit",
                f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
                f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
                f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
                f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                "--", gcc_bin, "-std=gnu17", "-Wall", "-Wextra",
                "-Wformat=2", "-Warray-bounds=2", "-Wnull-dereference", "-fanalyzer",
                "-O2", "-lm",
                "/work/submission.c", "-o", "/work/submission",
            ]
            compile_preexec = None
            compile_cwd = PROJECT_ROOT
        else:
            if prlimit_bin:
                command = [
                    prlimit_bin,
                    f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
                    f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
                    f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
                    f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                    f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                    "--", gcc_bin, "-std=gnu17", "-Wall", "-Wextra",
                    "-Wformat=2", "-Warray-bounds=2", "-Wnull-dereference", "-fanalyzer",
                    "-O2", "-lm",
                    str(source_path), "-o", str(executable_path),
                ]
                compile_preexec = None
            else:
                command = [
                    gcc_bin, "-std=gnu17", "-Wall", "-Wextra",
                    "-Wformat=2", "-Warray-bounds=2", "-Wnull-dereference", "-fanalyzer",
                    "-O2", "-lm",
                    str(source_path), "-o", str(executable_path),
                ]
                compile_preexec = _set_compile_limits
            compile_cwd = work

        result = _run_bounded(
            command, stdin_file=subprocess.DEVNULL,
            timeout_seconds=COMPILE_TIMEOUT_SECONDS, cwd=compile_cwd,
            preexec_fn=compile_preexec,
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


def _run_c_program(source: str, stdin: str = "") -> dict[str, Any]:
    """
    Compile and execute C code using a restricted Bubblewrap workspace.

    This is a development worker, not a security-certified public sandbox.
    Compilation and execution run inside separate Bubblewrap namespaces.
    """
    # Runs c program.
    # What the inputs mean:
    # - source: the C code being checked.
    # - stdin: the stdin used for this step.
    # What it gives back: It returns a set of named results for the next step.
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

    gcc_bin = _get_gcc_bin()
    prlimit_bin = _get_prlimit_bin()

    with tempfile.TemporaryDirectory(prefix="autograder-job-") as temp:
        work = Path(temp)
        source_path = work / "submission.c"
        executable_path = work / "submission"
        input_path = work / "stdin.txt"

        source_path.write_text(source, encoding="utf-8")
        input_path.write_text(stdin, encoding="utf-8")

        if is_bwrap_supported():
            bwrap_bin = shutil.which("bwrap") or "/usr/bin/bwrap"
            compile_command = [
                bwrap_bin,
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                *(["--ro-bind", "/lib64", "/lib64"] if Path("/lib64").exists() else []),
                *(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"] if Path("/etc/ld.so.cache").exists() else []),
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--bind", str(work), "/work",
                "--chdir", "/work",
                prlimit_bin or "/usr/bin/prlimit",
                f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
                f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
                f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
                f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                "--",
                gcc_bin,
                "-std=gnu17",
                "-Wall",
                "-Wextra",
                "-O2", "-lm",
                "/work/submission.c",
                "-o",
                "/work/submission",
            ]
            compile_preexec = None
            compile_cwd = PROJECT_ROOT
        else:
            if prlimit_bin:
                compile_command = [
                    prlimit_bin,
                    f"--cpu={COMPILE_TIMEOUT_SECONDS}:{COMPILE_TIMEOUT_SECONDS + 1}",
                    f"--as={COMPILE_MEMORY_LIMIT_BYTES}:{COMPILE_MEMORY_LIMIT_BYTES}",
                    f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
                    f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                    f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                    "--",
                    gcc_bin,
                    "-std=gnu17",
                    "-Wall",
                    "-Wextra",
                    "-O2", "-lm",
                    str(source_path),
                    "-o",
                    str(executable_path),
                ]
                compile_preexec = None
            else:
                compile_command = [
                    gcc_bin,
                    "-std=gnu17",
                    "-Wall",
                    "-Wextra",
                    "-O2", "-lm",
                    str(source_path),
                    "-o",
                    str(executable_path),
                ]
                compile_preexec = _set_compile_limits
            compile_cwd = work

        compile_result = _run_bounded(
            compile_command,
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=COMPILE_TIMEOUT_SECONDS,
            cwd=compile_cwd,
            preexec_fn=compile_preexec,
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

        if is_bwrap_supported():
            bwrap_bin = shutil.which("bwrap") or "/usr/bin/bwrap"
            sandbox_command = [
                bwrap_bin,
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                *(["--ro-bind", "/lib64", "/lib64"] if Path("/lib64").exists() else []),
                *(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"] if Path("/etc/ld.so.cache").exists() else []),
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--bind", str(work), "/work",
                "--chdir", "/work",
                prlimit_bin or "/usr/bin/prlimit",
                f"--cpu={CPU_LIMIT_SECONDS}:{CPU_LIMIT_SECONDS}",
                f"--as={MEMORY_LIMIT_BYTES}:{MEMORY_LIMIT_BYTES}",
                f"--fsize={FILE_LIMIT_BYTES}:{FILE_LIMIT_BYTES}",
                f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                "--",
                "/work/submission",
            ]
            run_preexec = None
            run_cwd = PROJECT_ROOT
        else:
            try:
                os.chmod(executable_path, 0o755)
            except OSError:
                pass
            run_preexec = _get_runner_preexec(is_compile=False)
            if prlimit_bin:
                sandbox_command = [
                    prlimit_bin,
                    f"--cpu={CPU_LIMIT_SECONDS}:{CPU_LIMIT_SECONDS}",
                    f"--as={MEMORY_LIMIT_BYTES}:{MEMORY_LIMIT_BYTES}",
                    f"--fsize={FILE_LIMIT_BYTES}:{FILE_LIMIT_BYTES}",
                    f"--nproc={MAX_PROCESSES}:{MAX_PROCESSES}",
                    f"--nofile={MAX_OPEN_FILES}:{MAX_OPEN_FILES}",
                    "--",
                    str(executable_path),
                ]
            else:
                sandbox_command = [str(executable_path)]
            run_cwd = work

        with input_path.open("rb") as program_input:
            run_result = _run_bounded(
                sandbox_command,
                stdin_file=program_input,
                timeout_seconds=RUN_TIMEOUT_SECONDS,
                cwd=run_cwd,
                preexec_fn=run_preexec,
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
    # Runs c program.
    # What the inputs mean:
    # - source: the C code being checked.
    # - stdin: the stdin used for this step.
    # What it gives back: It returns a set of named results for the next step.
    result = _run_c_program(source, stdin)
    return _normalize_result(result)
