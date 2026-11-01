from analyzers.code_quality import analyze_code_quality


def test_empty_source_is_rejected():
    result = analyze_code_quality("")
    assert result["status"] == "invalid_input"
    assert result["score"] is None


def test_basic_c_program_returns_quality_report():
    result = analyze_code_quality(
        "#include <stdio.h>\nint main(void) {\n    printf(\"Hello\\n\");\n    return 0;\n}\n"
    )
    assert result["status"] == "completed"
    assert 0 <= result["score"] <= 100
    assert result["score_type"] == "heuristic_code_quality_indicator"


def test_unsafe_functions_are_flagged():
    result = analyze_code_quality(
        '#include <stdio.h>\n#include <string.h>\n'
        'int main(void) { char s[10]; gets(s); strcpy(s, "abc"); return 0; }\n'
    )
    rules = {item["rule"] for item in result["findings"]}
    assert "unsafe_gets" in rules
    assert "unsafe_strcpy" in rules


def test_allocation_without_free_is_flagged():
    result = analyze_code_quality(
        "#include <stdlib.h>\nint main(void) { int *p = malloc(10); return 0; }\n"
    )
    rules = {item["rule"] for item in result["findings"]}
    assert "possible_unreleased_allocation" in rules


def test_comments_and_string_literals_do_not_trigger_unsafe_checks():
    result = analyze_code_quality(
        'int main(void) {\n'
        '    // gets(buffer) is mentioned in a comment\n'
        '    char *s = "strcpy(buffer, input)";\n'
        '    return 0;\n}\n'
    )
    rules = {item["rule"] for item in result["findings"]}
    assert "unsafe_gets" not in rules
    assert "unsafe_strcpy" not in rules


def test_quality_score_is_bounded_and_limitations_are_explicit():
    result = analyze_code_quality("int main(void) { return 0; }")
    assert 0 <= result["score"] <= 100
    assert result["limitations"]
    assert "correctness score" in " ".join(result["limitations"])
