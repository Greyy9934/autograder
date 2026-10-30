from unittest.mock import patch

from analyzers.memory_safety import analyze_memory_safety, run_asan, run_valgrind


def test_invalid_source_is_rejected():
    result = analyze_memory_safety("")
    assert result["status"] == "invalid_request"


def test_unknown_tool_is_rejected():
    result = analyze_memory_safety(
        "int main(void){return 0;}", tools=("unknown",)
    )
    assert result["status"] == "invalid_request"


def test_asan_clean_result_is_cautious():
    with patch(
        "analyzers.memory_safety._compile_and_run",
        return_value={
            "status": "completed",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        },
    ):
        result = run_asan("int main(void){return 0;}")

    assert result["status"] == "no_issue_detected_on_this_input"
    assert "does not prove" in result["note"].lower()


def test_asan_reports_sanitizer_finding():
    with patch(
        "analyzers.memory_safety._compile_and_run",
        return_value={
            "status": "completed",
            "exit_code": 1,
            "stdout": "",
            "stderr": "ERROR: AddressSanitizer: heap-buffer-overflow",
        },
    ):
        result = run_asan("int main(void){return 0;}")

    assert result["status"] == "diagnostic_finding"
    assert result["findings"]
    assert result["findings"][0]["confirmed_bug"] is False


def test_valgrind_unavailable_is_reported():
    with patch("analyzers.memory_safety.shutil.which", return_value=None):
        result = run_valgrind("int main(void){return 0;}")

    assert result["status"] == "unavailable"


def test_memory_diagnostic_compilation_uses_bubblewrap(tmp_path):
    from analyzers.memory_safety import _compile_and_run

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return {
            "status": "completed",
            "exit_code": 1,
            "stderr": "intentional compile failure",
            "stdout": "",
        }

    with patch("analyzers.memory_safety._run_bounded", side_effect=fake_run):
        result = _compile_and_run(
            "int main(void){return 0;}",
            "",
            ["-fsanitize=address"],
            ["/work/submission"],
        )

    command = captured["command"]
    assert command[0] == "/usr/bin/bwrap"
    assert "/usr/bin/gcc" in command
    assert "/work/submission.c" in command
    assert "/work/submission" in command
    assert result["status"] == "compile_error"
