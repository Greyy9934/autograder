from analyzers.output_contract import normalize_stdout, output_contract


def test_output_contract_carries_format_and_comparison_rule():
    contract = output_contract("Print one integer.")
    assert contract["format"] == "Print one integer."
    assert contract["representation"] == "stdout_text"
    assert "final newline" in contract["comparison_rule"]


def test_stdout_normalization_ignores_only_line_endings_and_trailing_space():
    assert normalize_stdout("5  6  \r\nword  \r\n") == "5  6\nword"
    assert normalize_stdout("5 6\nword") != normalize_stdout("5\n6 word")


def test_agent6_receives_the_same_approved_output_contract():
    from analyzers.code_quality import review_code_quality

    source = "int main(void) { return 0; }"
    response = {
        "summary": "Readable short program.",
        "strengths": [],
        "findings": [],
        "rubric_ratings": {
            dimension: {
                "rating": 3,
                "rationale": "Evidence-backed rating.",
                "evidence": [{"line": 1, "quote": source}],
            }
            for dimension in ("readability", "modularity", "design_originality")
        },
        "limitations": [],
    }

    class CapturingProvider:
        calls = []

        def generate_json(self, *, task, payload, schema):
            self.calls.append(payload)
            return response

    provider = CapturingProvider()
    problem = {
        "problem_statement": "Return zero.",
        "input_format": "One integer.",
        "output_format": "Print one integer.",
        "input_schema": {"version": 1, "fields": [
            {"name": "x", "type": "int", "min": 0, "max": 5}
        ]},
        "constraints": ["0 <= x <= 5"],
    }
    result = review_code_quality(
        source, provider, context={"approved_problem": problem}
    )

    assert result["status"] == "completed"
    assert provider.calls[0]["approved_problem_context"]["approved_io_contract"]["output_contract"]["format"] == problem["output_format"]
    assert provider.calls[0]["approved_problem_context"]["approved_io_contract"]["input_schema"] == problem["input_schema"]
