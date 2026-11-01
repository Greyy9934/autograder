"""Application-level coordination for AutoGrader."""

import hashlib
from typing import Any

from analyzers.preflight import preflight
from analyzers.reference_validation import validate_reference_pair
from analyzers.mathematical_verification import verify_algorithm
from analyzers.edge_cases import analyze_edge_cases
from analyzers.differential_testing import generate_integer_list_edge_cases
from analyzers.complexity_estimator import estimate_complexity
from analyzers.problem_reconstruction import reconstruct_problem
from analyzers.source_risks import analyze_source_risks
from analyzers.test_cases import analyze_test_cases
from analyzers.memory_safety import analyze_memory_safety
from app.ai.base import AIProviderError
from app.ai.config import create_ai_provider
from app.grading import grade_submission
from app.metric_scoring import derive_metric_scores
from app.runner import compile_c_source


def _attach_grading(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a conservative, rule-driven grade to any evaluation result."""
    try:
        scores = derive_metric_scores(result)
        result["metric_scores"] = scores
        result["grading"] = grade_submission(result, scores)
    except (ValueError, OSError) as exc:
        result["metric_scores"] = {}
        result["grading"] = {
            "status": "grading_error",
            "score": None,
            "message": str(exc),
        }
    return result




def evaluate_execution_evidence(
    source: str,
    prepared_result: dict[str, Any],
    test_cases: list[dict[str, Any]] | None = None,
    *,
    run_memory_diagnostics: bool = False,
    memory_diagnostic_stdin: str = "",
    provider: Any = None,
    adversarial_plan: dict[str, Any] | None = None,
    random_test_inputs: list[str] | None = None,
    generated_test_plans: dict[str, Any] | None = None,
    run_complexity_analysis: bool = False,
    agent3b_execution: dict[str, Any] | None = None,
    complexity_benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run execution-dependent checks after preparation is complete."""
    import copy

    result = copy.deepcopy(prepared_result)
    if complexity_benchmark is not None:
        result['complexity_benchmark'] = copy.deepcopy(complexity_benchmark)

    expected_hash = result.get("source_sha256")
    actual_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

    if not expected_hash or expected_hash != actual_hash:
        result["execution_status"] = "not_run"
        result["execution_reason"] = (
            "Prepared result does not match the submitted source."
        )
        return _attach_grading(result)

    result["test_evaluation"] = None
    result["memory_safety"] = None
    result["reference_validation"] = None
    result["adversarial_execution"] = None
    result["random_test_execution"] = None
    result["complexity_analysis"] = None
    result["complexity_reconciliation"] = None

    if generated_test_plans is not None:
        if not isinstance(generated_test_plans, dict):
            result["execution_status"] = "not_run"
            result["execution_reason"] = "Generated test plans must be an object."
            return _attach_grading(result)

        generated_source_hash = generated_test_plans.get("source_sha256")
        if generated_source_hash != actual_hash:
            result["execution_status"] = "not_run"
            result["execution_reason"] = "Generated test plans do not match submitted source."
            return _attach_grading(result)

        random_plan = generated_test_plans.get("random_tests")
        adversarial_plan = generated_test_plans.get("adversarial_tests")

        if (
            not isinstance(random_plan, dict)
            or random_plan.get("status") != "generated"
            or not isinstance(adversarial_plan, dict)
            or adversarial_plan.get("status") != "planned"
        ):
            result["execution_status"] = "not_run"
            result["execution_reason"] = "Both generated test plans must be valid."
            return _attach_grading(result)

        fingerprint = generated_test_plans.get("spec_fingerprint")
        if (
            not fingerprint
            or random_plan.get("spec_fingerprint") != fingerprint
            or adversarial_plan.get("spec_fingerprint") != fingerprint
        ):
            result["execution_status"] = "not_run"
            result["execution_reason"] = "Generated plans have inconsistent specification fingerprints."
            return _attach_grading(result)

        random_test_inputs = random_plan.get("inputs")
        if not isinstance(random_test_inputs, list) or not random_test_inputs:
            result["execution_status"] = "not_run"
            result["execution_reason"] = "Random test plan contains no valid inputs."
            return _attach_grading(result)

    if result.get("status") != "reconstruction_ready":
        result["execution_status"] = "not_run"
        result["execution_reason"] = (
            "Problem preparation is incomplete or requires clarification."
        )
        return _attach_grading(result)

    if result.get("preflight", {}).get("decision") != "continue":
        result["execution_status"] = "not_run"
        result["execution_reason"] = "Source validation did not pass."
        return _attach_grading(result)

    if test_cases is not None:
        result["test_evaluation"] = analyze_test_cases(source, test_cases)

    if adversarial_plan is not None:
        from analyzers.adversarial_execution import execute_adversarial_candidates

        result["adversarial_execution"] = execute_adversarial_candidates(
            source, adversarial_plan
        )

    if random_test_inputs is not None:
        from analyzers.random_test_execution import execute_random_test_inputs

        result["random_test_execution"] = execute_random_test_inputs(
            source, random_test_inputs
        )

    if run_memory_diagnostics:
        result["memory_safety"] = analyze_memory_safety(
            source, stdin=memory_diagnostic_stdin
        )

    references = result.get("reference_solutions") or {}
    if (
        references.get("status") == "generated_unverified"
        and isinstance(test_cases, list)
        and test_cases
    ):
        brute = references.get("brute_force", {})
        efficient = references.get("efficient", {})
        validation = validate_reference_pair(
            brute.get("code", ""),
            efficient.get("code", ""),
            test_cases,
        )
        result["reference_validation"] = validation
        references["validation"] = {
            **references.get("validation", {}),
            "supplied_cases_checked": True,
            "compiled_and_passed_supplied_cases": (
                validation["brute_force"]["passed"]
                and validation["efficient"]["passed"]
            ),
            "differentially_tested": bool(validation["comparisons"])
            and all(item["outputs_agree"] for item in validation["comparisons"]),
        }

    # Agent 4: AI-primary complexity analysis, explicitly opt-in so existing
    # provider call sequences and paid-usage behaviour remain unchanged.
    if run_complexity_analysis:
        if provider is None:
            result["complexity_analysis"] = {
                "status": "skipped",
                "reason": "No AI provider was supplied; no provider was created automatically.",
            }
        else:
            from analyzers.complexity_analysis import analyze_complexity
            from analyzers.complexity_reconciliation import (
                reconcile_complexity_evidence,
            )

            complexity_result = analyze_complexity(
                source,
                provider,
                static_analysis=result.get("complexity_estimate"),
                benchmark=result.get("complexity_benchmark"),
            )
            result["complexity_analysis"] = complexity_result
            result["complexity_reconciliation"] = (
                reconcile_complexity_evidence(
                    complexity_result,
                    static_analysis=result.get("complexity_estimate"),
                    benchmark=result.get("complexity_benchmark"),
                )
            )

    # Agent 5: review the student's algorithm only after execution evidence.
    reconstruction = result.get("reconstruction") or {}
    candidates = reconstruction.get("candidates", [])

    if provider is not None and len(candidates) == 1:
        selected_problem = dict(candidates[0])
        selected_problem["constraints"] = reconstruction.get("constraints", [])

        result["mathematical_verification"] = verify_algorithm(
            selected_problem,
            {
                "code": source,
                "algorithm": (
                    "Infer the algorithm directly from the student's C source. "
                    "Do not assume an externally supplied algorithm description."
                ),
                "supporting_evidence": {
                    "complexity_analysis": result.get("complexity_analysis"),
                    "complexity_reconciliation": result.get("complexity_reconciliation"),
                    "complexity_benchmark": result.get("complexity_benchmark"),
                    "execution_evidence_summary": result.get("execution_evidence_summary"),
                    "adversarial_execution": result.get("adversarial_execution"),
                    "random_test_execution": result.get("random_test_execution"),
                    "agent3b_execution": agent3b_execution,
                },
            },
            provider,
        )

    from app.execution_summary import summarize_execution_evidence

    result["execution_evidence_summary"] = summarize_execution_evidence(result)
    result["execution_status"] = "completed"
    return _attach_grading(result)


def generate_reference_solutions_for_confirmed_spec(
    spec: Any,
    provider: Any = None,
) -> dict[str, Any]:
    """Run Agent 2 only after explicit instructor approval."""
    from analyzers.assignment_spec import AssignmentSpec
    from analyzers.reference_solutions import generate_reference_solutions

    if not isinstance(spec, AssignmentSpec) or not spec.confirmed:
        return {
            "status": "rejected",
            "message": "An instructor-confirmed assignment specification is required.",
            "references_trusted": False,
        }

    if provider is None:
        try:
            provider = create_ai_provider()
        except AIProviderError as exc:
            return {
                "status": "provider_error",
                "message": str(exc),
                "references_trusted": False,
            }

    problem = spec.to_dict()
    result = generate_reference_solutions(problem, provider)
    result["spec_fingerprint"] = spec.fingerprint()
    result["instructor_confirmed"] = True
    return result


def evaluate_submission(
    source: str,
    problem_statement: str | None = None,
    test_cases: list[dict[str, Any]] | None = None,
    *,
    provider: Any = None,
    rules_path: str | None = None,
    run_memory_diagnostics: bool = False,
    generate_edge_case_inputs: bool = False,
    edge_case_input_bounds: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Run preflight and heuristic source-risk analysis, then optional
    problem reconstruction. Source-risk findings are not confirmed bugs.
    """
    source_risks = analyze_source_risks(source)

    preflight_result = (
        preflight(source, rules_path=rules_path)
        if rules_path is not None
        else preflight(source)
    )

    result: dict[str, Any] = {
        "status": "preflight_blocked",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "grading": None,
        "metric_scores": {},
        "preflight": preflight_result,
        "compilation": None,
        "source_risks": source_risks,
        "complexity_estimate": estimate_complexity(source),
        "memory_safety": None,
        "reconstruction": None,
        "edge_cases": None,
        "generated_edge_case_inputs": None,
        "test_evaluation": None,
        "reference_solutions": None,
        "reference_validation": None,
        "mathematical_verification": None,
        "correctness_assessed": False,
        "message": None,
    }

    if preflight_result.get("decision") != "continue":
        result["message"] = (
            "Preflight did not allow further analysis. "
            "Correctness has not been assessed."
        )
        return _attach_grading(result)

    try:
        compilation = compile_c_source(source)
    except Exception as exc:
        compilation = {"status": "compiler_error", "message": str(exc)}
    result["compilation"] = compilation
    if compilation.get("status") != "compiled":
        result["status"] = "compile_blocked"
        result["message"] = (
            "Compilation did not succeed in the sandbox. "
            "Agent 1 was not started; correctness has not been assessed."
        )
        return _attach_grading(result)

    if provider is None:
        try:
            provider = create_ai_provider()
        except AIProviderError as exc:
            result["status"] = "ai_configuration_error"
            result["message"] = str(exc)
            return _attach_grading(result)

    try:
        reconstruction = reconstruct_problem(
            source=source,
            problem_statement=problem_statement,
            test_cases=test_cases,
            provider=provider,
        )
    except AIProviderError as exc:
        result["status"] = "ai_provider_error"
        result["message"] = str(exc)
        return _attach_grading(result)

    result["reconstruction"] = reconstruction

    if reconstruction.get("status") == "provider_error":
        result["status"] = "ai_unavailable"
        result["message"] = (
            "Preflight passed, but problem reconstruction was unavailable. "
            "No correctness conclusion has been made."
        )
    elif reconstruction.get("status") == "needs_clarification":
        result["status"] = "needs_clarification"
        result["message"] = (
            "Please clarify the intended problem before correctness grading."
        )
    elif reconstruction.get("status") == "ready" and len(
        reconstruction.get("candidates", [])
    ) > 1:
        result["status"] = "needs_clarification"
        result["message"] = (
            "Multiple problem interpretations remain possible. "
            "Select or clarify the intended problem before correctness grading."
        )
    elif reconstruction.get("status") == "invalid_request":
        result["status"] = "invalid_request"
        result["message"] = reconstruction.get("message")
    else:
        candidates = reconstruction.get("candidates", [])
        if reconstruction.get("status") == "ready" and len(candidates) == 1:
            selected_problem = dict(candidates[0])
            selected_problem["constraints"] = reconstruction.get("constraints", [])
            from analyzers.assignment_spec import AssignmentSpec

            try:
                draft = AssignmentSpec.create_draft(
                    candidates[0],
                    constraints=tuple(reconstruction.get("constraints", [])),
                    input_format=candidates[0]["input_format"],
                    output_format=candidates[0]["output_format"],
                    input_schema=candidates[0].get("input_schema"),
                )
                result["assignment_spec"] = draft.to_dict()
                result["assignment_spec_fingerprint"] = draft.fingerprint()
                result["assignment_spec_status"] = "draft_requires_instructor_confirmation"
            except (KeyError, TypeError, ValueError) as exc:
                result["assignment_spec"] = None
                result["assignment_spec_status"] = "incomplete_draft"
                result["assignment_spec_error"] = str(exc)
            result["edge_cases"] = analyze_edge_cases(selected_problem)
            if generate_edge_case_inputs:
                if edge_case_input_bounds is None:
                    result["generated_edge_case_inputs"] = {
                        "status": "needs_explicit_bounds",
                        "inputs": [],
                        "message": (
                            "Provide explicit integer-list bounds before "
                            "generating concrete inputs."
                        ),
                    }
                elif (
                    isinstance(edge_case_input_bounds, dict)
                    and set(edge_case_input_bounds).issubset({
                        "min_length", "max_length", "min_value", "max_value"
                    })
                ):
                    result["generated_edge_case_inputs"] = (
                        generate_integer_list_edge_cases(**edge_case_input_bounds)
                    )
                else:
                    result["generated_edge_case_inputs"] = {
                        "status": "invalid_request",
                        "inputs": [],
                        "message": "Edge-case bounds must be a dictionary of supported options.",
                    }
        result["status"] = "reconstruction_ready"
        result["message"] = (
            "Problem reconstruction completed. Correctness still requires "
            "validated references and test-based evaluation."
        )

    return _attach_grading(result)
