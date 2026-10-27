"""Optional memory diagnostics; findings are evidence, not proof of safety."""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.runner import (
    COMPILE_TIMEOUT_SECONDS,
    MEMORY_LIMIT_BYTES,
    OUTPUT_LIMIT_BYTES,
    PROJECT_ROOT,
    RUN_TIMEOUT_SECONDS,
    _normalize_result,
    _run_bounded,
    _set_compile_limits,
)


def _tool_result(status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "findings": [],
        **extra,
    }


def _compile_and_run(
    source: str,
    stdin: str,
    compiler_flags: list[str],
    runtime_command: list[str],
) -> dict[str, Any]:
    """Compile a temporary diagnostic binary and run it with bounded resources."""
    with tempfile.TemporaryDirectory(prefix="autograder-memory-") as directory:
        work = Path(directory)
        source_path = work / "submission.c"
        executable_path = work / "submission"
        input_path = work / "stdin.txt"
        source_path.write_text(source, encoding="utf-8")
        input_path.write_text(stdin, encoding="utf-8")

        compile_result = _run_bounded(
            [
                "/usr/bin/gcc",
                "-std=c17",
                "-Wall",
                "-Wextra",
                "-g",
                *compiler_flags,
                str(source_path),
                "-o",
                str(executable_path),
            ],
            stdin_file=subprocess.DEVNULL,
            timeout_seconds=COMPILE_TIMEOUT_SECONDS,
            cwd=work,
            preexec_fn=_set_compile_limits,
        )

        if compile_result["status"] != "completed" or compile_result.get("exit_code") != 0:
            return {
                "status": "compile_error",
                "compile_status": compile_result["status"],
                "compiler_stderr": compile_result.get("stderr", ""),
                "compiler_stdout": compile_result.get("stdout", ""),
                "findings": [],
            }

        # Diagnostics run inside the same Bubblewrap isolation used by the
        # normal worker. The tool executable and its runtime libraries must
        # be present in the read-only /usr and /lib mounts.
        command = [
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
            f"--cpu={5}:{5}",
            f"--as={MEMORY_LIMIT_BYTES}:{MEMORY_LIMIT_BYTES}",
            f"--fsize={OUTPUT_LIMIT_BYTES}:{OUTPUT_LIMIT_BYTES}",
            "--nproc=32:32",
            "--nofile=64:64",
            "--",
            *runtime_command,
        ]

        with input_path.open("rb") as program_input:
            run_result = _run_bounded(
                command,
                stdin_file=program_input,
                timeout_seconds=RUN_TIMEOUT_SECONDS,
                cwd=PROJECT_ROOT,
            )

        run_result = _normalize_result(run_result)
        if run_result.get("status") == "launch_error":
            return _tool_result(
                "sandbox_error",
                run_result.get("message", "Diagnostic sandbox could not start."),
            )

        return {
            "status": run_result["status"],
            "exit_code": run_result.get("exit_code"),
            "seconds": run_result.get("seconds"),
            "stdout": run_result.get("stdout", ""),
            "stderr": run_result.get("stderr", ""),
            "stdout_truncated": run_result.get("stdout_truncated", False),
            "stderr_truncated": run_result.get("stderr_truncated", False),
            "compiler_stderr": compile_result.get("stderr", ""),
            "findings": [],
        }


def run_asan(source: str, stdin: str = "") -> dict[str, Any]:
    """Run GCC AddressSanitizer and UndefinedBehaviorSanitizer diagnostics."""
    if not isinstance(source, str) or not source.strip() or not isinstance(stdin, str):
        return _tool_result("invalid_request", "Source and input must be strings.")

    if shutil.which("gcc") is None or not Path("/usr/bin/bwrap").exists():
        return _tool_result("unavailable", "GCC or Bubblewrap is unavailable.")

    result = _compile_and_run(
        source,
        stdin,
        ["-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
        ["/work/submission"],
    )

    stderr = result.get("stderr", "")
    if result.get("status") == "completed" and result.get("exit_code") == 0:
        result["status"] = "no_issue_detected_on_this_input"
    elif "AddressSanitizer" in stderr or "runtime error:" in stderr:
        result["status"] = "diagnostic_finding"
        result["findings"] = [
            {
                "tool": "asan_ubsan",
                "severity": "warning",
                "evidence": line[:300],
                "confirmed_bug": False,
            }
            for line in stderr.splitlines()
            if "AddressSanitizer" in line or "runtime error:" in line
        ]
    result["note"] = (
        "A clean sanitizer run on one input does not prove memory safety. "
        "Findings depend on the tested path and sanitizer coverage."
    )
    return result


def run_valgrind(source: str, stdin: str = "") -> dict[str, Any]:
    """Run Valgrind Memcheck when available."""
    if not isinstance(source, str) or not source.strip() or not isinstance(stdin, str):
        return _tool_result("invalid_request", "Source and input must be strings.")

    if shutil.which("valgrind") is None or not Path("/usr/bin/bwrap").exists():
        return _tool_result("unavailable", "Valgrind or Bubblewrap is unavailable.")

    # Valgrind's runtime overhead can exceed the ordinary worker's memory
    # budget. Keep the same hard cap and report resource failures explicitly.
    result = _compile_and_run(
        source,
        stdin,
        ["-O0"],
        [
            "/usr/bin/valgrind",
            "--quiet",
            "--leak-check=full",
            "--show-leak-kinds=all",
            "--error-exitcode=99",
            "/work/submission",
        ],
    )

    stderr = result.get("stderr", "")
    if result.get("exit_code") == 99 or "Invalid read" in stderr or "Invalid write" in stderr:
        result["status"] = "diagnostic_finding"
        result["findings"] = [
            {
                "tool": "valgrind",
                "severity": "warning",
                "evidence": line[:300],
                "confirmed_bug": False,
            }
            for line in stderr.splitlines()
            if any(term in line for term in (
                "Invalid read", "Invalid write", "definitely lost",
                "indirectly lost", "possibly lost", "uninitialised",
            ))
        ]
    elif result.get("status") == "completed" and result.get("exit_code") == 0:
        result["status"] = "no_issue_detected_on_this_input"

    result["note"] = (
        "Valgrind results cover only this execution. Memory limits may prevent "
        "the diagnostic from completing on large programs."
    )
    return result


def analyze_memory_safety(
    source: str,
    stdin: str = "",
    *,
    tools: tuple[str, ...] = ("asan", "valgrind"),
) -> dict[str, Any]:
    """Run explicitly selected memory diagnostics independently."""
    if not isinstance(source, str) or not source.strip() or not isinstance(stdin, str):
        return {
            "status": "invalid_request",
            "results": {},
            "message": "Source must be non-empty text and input must be text.",
        }

    runners = {"asan": run_asan, "valgrind": run_valgrind}
    if not isinstance(tools, (tuple, list)) or any(
        not isinstance(name, str) or name not in runners for name in tools
    ):
        return {
            "status": "invalid_request",
            "results": {},
            "message": "Tools must contain only 'asan' and/or 'valgrind'.",
        }

    results = {name: runners[name](source, stdin) for name in tools}
    return {
        "status": "completed",
        "results": results,
        "all_tools_clean": bool(results) and all(
            item.get("status") == "no_issue_detected_on_this_input"
            for item in results.values()
        ),
        "message": (
            "Diagnostics are input-dependent and do not establish general memory safety."
        ),
    }
