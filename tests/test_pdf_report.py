import pytest
from pypdf import PdfReader

from app.pdf_report import generate_pdf_report


def test_generates_valid_pdf(tmp_path):
    output = generate_pdf_report(
        {"status": "completed", "execution_status": "not_run"},
        tmp_path / "report.pdf",
    )
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF-")


def test_creates_parent_directories(tmp_path):
    output = generate_pdf_report(
        {"status": "completed"},
        tmp_path / "nested" / "reports" / "report.pdf",
    )
    assert output.exists()


def test_report_contains_all_major_sections(tmp_path):
    output = tmp_path / "report.pdf"
    generate_pdf_report({
        "status": "completed",
        "preflight": {"decision": "continue"},
        "reconstruction": {"status": "ready"},
        "references": {"references_trusted": False},
        "tests": {"passed": 8, "failed": 2, "inconclusive": 1},
        "complexity": {"loop_count": 2},
        "code_quality": {"score": 85},
        "verification": {
            "outcome": "proof_sketch",
            "reasoning": "Loop invariant reasoning.",
            "assumptions": ["Input is valid."],
            "limitations": ["Not formally verified."],
        },
        "grading": {"status": "provisional"},
        "limitations": ["AI ratings are advisory and require human interpretation."],
    }, output)

    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for section in (
        "EXECUTIVE SUMMARY", "PROBLEM RECONSTRUCTION",
        "REFERENCE SOLUTIONS", "TEST GENERATION", "TEST RESULT",
        "ALGORITHMIC COMPLEXITY", "CODE QUALITY",
        "MATHEMATICAL VERIFICATION", "GRADING",
    ):
        assert section in text.upper()
    assert "Decision: continue" not in text


def test_test_graphs_are_generated_from_real_counts(tmp_path):
    output = generate_pdf_report(
        {"tests": {"passed": 8, "failed": 2, "inconclusive": 1}},
        tmp_path / "graphs.pdf",
    )
    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Test outcome distribution" in text
    assert "80.0%" in text


def test_empty_evaluation_generates_report(tmp_path):
    output = generate_pdf_report({}, tmp_path / "empty.pdf")
    assert output.exists()
    assert len(PdfReader(str(output)).pages) >= 5


def test_non_dictionary_input_is_rejected(tmp_path):
    with pytest.raises(TypeError):
        generate_pdf_report([], tmp_path / "invalid.pdf")


def test_report_renders_agent4_curve_and_human_readable_edge_outcomes(tmp_path):
    output = generate_pdf_report({
        "status": "completed",
        "complexity_analysis": {
            "status": "analyzed",
            "ai_analysis": {
                "algorithm": {"name": "Linear scan", "input_size_model": "n is array length"},
                "time_complexity": {"best_case": "O(1)", "average_case": "O(n)", "worst_case": "O(n)", "derivation": "At most n elements are visited."},
                "space_complexity": {"auxiliary": "O(1)", "total": "O(n)", "derivation": "Input array dominates."},
                "confidence": 0.9,
                "evidence": [{"line_start": 3, "line_end": 7, "claim": "The loop scans the array.", "role": "loop"}],
                "limitations": ["Advisory analysis."],
            },
            "complexity_graphs": {
                "time_worst_case": {
                    "status": "completed", "original_notation": "O(n)",
                    "axis": {"y_label": "Representative growth"},
                    "points": [{"x": 2, "y": 2}, {"x": 10, "y": 10}, {"x": 100, "y": 100}],
                }
            },
        },
        "agent3b_execution": {
            "status": "completed",
            "differential_comparisons": [{
                "case": 1, "name": "edge", "outcomes": {
                    "student": {"execution_class": "program_success", "stdout": "wrong"},
                    "brute_force": {"execution_class": "program_success", "stdout": "right"},
                    "efficient": {"execution_class": "program_success", "stdout": "right"},
                },
            }],
        },
        "grading": {"status": "not_gradeable", "reproducibility": {
            "fingerprint": "f" * 64, "grading_version": "1.0",
            "rules_sha256": "r" * 64, "source_sha256": "s" * 64,
            "assignment_spec_fingerprint": "a" * 64,
            "test_suite_fingerprint": "t" * 64,
        }},
    }, tmp_path / "agent-results.pdf")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
    assert "AGENT 4 ANALYSIS" in text.upper()
    assert "O(n)" in text
    assert "wrong" in text
    assert "right" in text
    assert "Reproducibility ID" in text
    assert "f" * 64 in text
    assert "source_sha256" not in text
    assert "rules_sha256" not in text
    assert "test_suite_fingerprint" not in text
    assert '"execution_class":' not in text



def test_report_renders_actual_evaluation_schema(tmp_path):
    output = tmp_path / "actual-schema.pdf"
    generate_pdf_report({
        "status": "completed",
        "execution_status": "completed",
        "preflight": {"decision": "continue"},
        "test_evaluation": {
            "status": "completed",
            "batch_status": "completed",
            "passed": 1,
            "failed": 1,
            "inconclusive": 1,
            "determinate_total": 2,
            "total": 3,
            "results": [
                {
                    "passed": True,
                    "failed": False,
                    "inconclusive": False,
                    "status": "passed",
                    "execution_class": "program_success",
                    "input": "4",
                    "expected_output": "16",
                    "actual_output": "16",
                    "exit_code": 0,
                    "explanation": "Output matched.",
                },
                {
                    "passed": False,
                    "failed": True,
                    "inconclusive": False,
                    "status": "failed",
                    "execution_class": "program_success",
                    "input": "5",
                    "expected_output": "25",
                    "actual_output": "20",
                    "exit_code": 0,
                    "explanation": "Output differed.",
                },
                {
                    "passed": False,
                    "failed": False,
                    "inconclusive": True,
                    "status": "inconclusive",
                    "execution_class": "infrastructure_error",
                    "input": "6",
                    "explanation": "Runner unavailable.",
                },
            ],
        },
        "execution_evidence_summary": {
            "random_tests": {
                "status": "completed",
                "executed": 4,
                "outcome_counts": {"program_success": 3, "runtime_error": 1},
            },
            "adversarial_tests": {
                "status": "completed",
                "executed": 2,
                "outcome_counts": {"program_success": 1, "time_limit_exceeded": 1},
            },
            "correctness_score_contribution": None,
            "interpretation": "Observations only; no trusted expected outputs.",
        },
        "complexity_estimate": {
            "status": "completed",
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
            "loop_count": 2,
            "max_loop_depth_estimate": 1,
            "dynamic_allocation_count": 0,
            "recursive_functions": [],
            "findings": [{
                "rule_id": "LOOP-001",
                "line": 12,
                "evidence": "for (i = 0; i < n; i++)",
                "message": "Loop iterates over input length.",
            }],
            "limitations": ["Loop bounds are heuristic."],
        },
        "code_quality": {
            "status": "completed",
            "score": 82,
            "score_type": "heuristic_code_quality_indicator",
            "finding_count": 1,
            "findings": [{
                "rule": "LONG-LINE",
                "severity": "medium",
                "message": "Line exceeds the configured length.",
            }],
            "metrics": {
                "source_lines": 30,
                "function_count_estimate": 2,
                "long_lines": 1,
            },
            "limitations": ["Heuristic analysis only."],
        },
        "metric_scores": {
            "correctness": 50,
            "edge_cases": None,
            "code_quality": None,
        },
        "grading": {
            "status": "provisional",
            "score": 50,
            "score_scale": "0-100",
            "included_weight": 50,
            "excluded_metrics": ["edge_cases", "code_quality"],
            "message": "Some metrics are unavailable.",
            "breakdown": {
                "correctness": {
                    "weight": 50,
                    "score": 100,
                    "weighted_contribution": 50,
                    "status": "included",
                    "reason": "Explicit tests were evaluated.",
                },
                "edge_cases": {
                    "weight": 10,
                    "score": None,
                    "weighted_contribution": None,
                    "status": "excluded",
                    "reason": "No eligible evidence.",
                },
            },
        },
    }, output)

    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Confirmed failing cases" in text
    assert "25" in text and "20" in text
    for expected in (
        "Confirmed failing cases",
        "inconclusive",
        "Expected",
        "Student output",
        "Random tests",
        "Adversarial tests",
        "O(n)",
        "O(1)",
        "Weighted grading breakdown",
        "Some metrics are unavailable",
    ):
        assert expected.lower() in text.lower(), expected


def test_report_renders_static_confidence_and_empirical_benchmark(tmp_path):
    output = tmp_path / "benchmark-report.pdf"
    generate_pdf_report({
        "complexity_estimate": {
            "status": "completed",
            "analysis_type": "static_heuristic",
            "confidence": "low",
            "proof_status": "not_proven",
            "input_size_model": "not_inferred",
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
        },
        "complexity_benchmark": {
            "status": "completed",
            "measurement_method": "isolated_process_wall_clock",
            "measurement_scope": "Includes sandbox/process startup overhead.",
            "repetitions_per_size": 3,
            "compile_seconds": 0.12,
            "results": [
                {
                    "input_size": 10,
                    "successful_runs": 3,
                    "failed_runs": 0,
                    "median_runtime_seconds": 0.001,
                    "minimum_runtime_seconds": 0.0009,
                    "maximum_runtime_seconds": 0.0011,
                },
                {
                    "input_size": 100,
                    "successful_runs": 2,
                    "failed_runs": 1,
                    "median_runtime_seconds": 0.004,
                    "minimum_runtime_seconds": 0.003,
                    "maximum_runtime_seconds": 0.005,
                },
            ],
            "chart_data": [
                {"input_size": 10, "median_runtime_seconds": 0.001},
                {"input_size": 100, "median_runtime_seconds": 0.004},
            ],
            "growth_observations": [{
                "from_input_size": 10,
                "to_input_size": 100,
                "input_size_ratio": 10.0,
                "runtime_ratio": 4.0,
                "interpretation": "Observed ratio only; not an asymptotic complexity proof.",
            }],
            "interpretation": "Empirical observations only; not a Big-O proof.",
            "limitations": ["Process startup overhead is included."],
        },
    }, output)

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
    for expected in (
        "Empirical runtime benchmark",
        "Median elapsed runtime",
        "Successful",
        "Failed",
        "O(n)",
        "O(1)",
    ):
        assert expected.lower() in text.lower(), expected
    assert "isolated_process_wall_clock" not in text
    assert "measurement method" not in text.lower()


def test_report_without_benchmark_remains_supported(tmp_path):
    output = generate_pdf_report({
        "complexity_estimate": {
            "status": "completed",
            "time_complexity": "O(n)",
        },
    }, tmp_path / "without-benchmark.pdf")

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
    assert "O(n)" in text
    assert "Empirical runtime benchmark" not in text




def test_agent3a_report_plots_three_programs_by_actual_input_size(tmp_path):
    output = generate_pdf_report({
        "agent3a_benchmark": {
            "status": "completed_with_execution_issues",
            "chart_data": [
                {"program": "student", "input_size": 100, "runtime_seconds": 0.001},
                {"program": "student", "input_size": 500, "runtime_seconds": 0.008},
                {"program": "brute_force", "input_size": 100, "runtime_seconds": 0.0012},
                {"program": "brute_force", "input_size": 500, "runtime_seconds": 0.009},
                {"program": "efficient", "input_size": 100, "runtime_seconds": 0.0011},
                {"program": "efficient", "input_size": 500, "runtime_seconds": 0.002},
            ],
            "differential_comparisons": [{
                "case": 2,
                "input_size": 500,
                "outcomes": {
                    "student": {"execution_class": "time_limit_exceeded"},
                },
            }],
        },
    }, tmp_path / "agent3a-runtime-graph.pdf")

    text = "\\n".join(
        page.extract_text() or "" for page in PdfReader(str(output)).pages
    )
    assert "Measured runtime by actual input size" in text
    assert "Input size (n)" in text
    assert "Student" in text
    assert "Brute-force" in text
    assert "Efficient" in text
    assert "Only successful measured runs are plotted" in text


def test_final_reproducible_scorecard_is_last_page(tmp_path):
    output = generate_pdf_report({
        "grading": {
            "status": "graded", "score": 88, "grade_band": "B",
            "score_scale": {"minimum": 0, "maximum": 100},
            "breakdown": {
                "correctness": {"weight": 45, "score": 100, "status": "included"},
                "design_originality": {"weight": 5, "score": 75, "status": "included"},
            },
            "reproducibility": {"fingerprint": "f" * 64, "rules_version": "2.0", "test_suite_fingerprint": "t" * 64, "ai_metric_snapshot_key": "a" * 64},
        }
    }, tmp_path / "scorecard.pdf")
    pages = PdfReader(str(output)).pages
    final_text = pages[-1].extract_text() or ""
    assert "FINAL GRADE / REPRODUCIBLE SCORECARD" in final_text
    assert "Novelty of thought" in final_text
    assert "88 / 100" in final_text
    assert "Reproducibility ID" in final_text
    assert "FINAL GRADE / REPRODUCIBLE SCORECARD" not in (pages[-2].extract_text() or "")
