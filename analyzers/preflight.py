"""Deterministic preflight checks for C submissions."""

import json
from pathlib import Path
from typing import Any

from app.runner import run_c_program

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = PROJECT_ROOT / "rules" / "preflight.json"


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """Load and minimally validate the external preflight configuration."""
    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as handle:
        rules = json.load(handle)

    for section in ("source_limits", "compiler", "execution", "policy"):
        if not isinstance(rules.get(section), dict):
            raise ValueError(f"Missing or invalid rules section: {section}")

    for key in ("max_source_bytes", "max_input_bytes"):
        value = rules["source_limits"].get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Invalid source limit: {key}")

    return rules


def extract_compiler_warnings(compiler_stderr: str) -> list[str]:
    """Extract GCC-style warning diagnostic lines from compiler stderr."""
    return [
        line for line in compiler_stderr.splitlines()
        if "warning:" in line.lower()
    ]


def preflight(
    source: str,
    stdin: str = "",
    rules_path: str | Path = DEFAULT_RULES_PATH,
) -> dict[str, Any]:
    """Check request validity, compile, and execute before deeper grading."""
    rules = load_rules(rules_path)

    if not isinstance(source, str) or not source.strip():
        return {
            "decision": "reject",
            "stage": "input_validation",
            "status": "invalid_request",
            "reasons": ["C source must be a non-empty string."],
            "stdout": "",
            "stderr": "",
        }

    if not isinstance(stdin, str):
        return {
            "decision": "reject",
            "stage": "input_validation",
            "status": "invalid_request",
            "reasons": ["Program input must be a string."],
            "stdout": "",
            "stderr": "",
        }

    source_bytes = len(source.encode("utf-8"))
    input_bytes = len(stdin.encode("utf-8"))

    if source_bytes > rules["source_limits"]["max_source_bytes"]:
        return {
            "decision": "reject",
            "stage": "input_validation",
            "status": "invalid_request",
            "reasons": ["Source exceeds the configured byte limit."],
            "stdout": "",
            "stderr": "",
        }

    if input_bytes > rules["source_limits"]["max_input_bytes"]:
        return {
            "decision": "reject",
            "stage": "input_validation",
            "status": "invalid_request",
            "reasons": ["Input exceeds the configured byte limit."],
            "stdout": "",
            "stderr": "",
        }

    result = run_c_program(source, stdin)
    status = result.get("status", "unknown")

    if status in {"invalid_request", "compile_error", "compiler_error"}:
        decision = "reject"
        stage = "compilation"
        reasons = [result.get("message", "Compilation did not succeed.")]
    elif status == "compile_timeout":
        decision = "block"
        stage = "compilation"
        reasons = ["Compilation exceeded its time limit."]
    elif status == "timeout":
        decision = "block"
        stage = "execution"
        reasons = ["Program exceeded its wall-clock time limit."]
    elif status == "sandbox_error":
        decision = "block"
        stage = "sandbox"
        reasons = ["The restricted execution environment failed."]
    elif status == "completed":
        decision = "continue"
        stage = "execution"
        reasons = []
    else:
        decision = "block"
        stage = "execution"
        reasons = [f"Unrecognized worker status: {status}"]

    compiler_stderr = result.get("compiler_stderr", "")
    compiler_stdout = result.get("compiler_stdout", "")
    diagnostic_lines = extract_compiler_warnings(compiler_stderr)

    return {
        "decision": decision,
        "stage": stage,
        "status": status,
        "reasons": reasons,
        "compiler_stdout": compiler_stdout,
        "compiler_stderr": compiler_stderr,
        "compiler_warnings": diagnostic_lines,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "exit_code": result.get("exit_code"),
        "compile_exit_code": result.get("compile_exit_code"),
        "compile_seconds": result.get("compile_seconds"),
        "run_seconds": result.get("run_seconds"),
        "stdout_truncated": result.get("stdout_truncated", False),
        "stderr_truncated": result.get("stderr_truncated", False),
    }
