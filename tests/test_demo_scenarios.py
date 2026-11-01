from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from analyzers.agent3_ai import (
    analyze_agent3b_edges,
    execute_agent3a_program,
    generate_agent3a_program,
    validate_agent3b_edges,
)
from analyzers.assignment_spec import AssignmentSpec
from analyzers.code_quality import review_code_quality
from analyzers.complexity_analysis import analyze_complexity
from analyzers.mathematical_verification import verify_algorithm
from analyzers.problem_reconstruction import reconstruct_problem
from analyzers.reference_solutions import generate_reference_solutions
from analyzers.structured_input_schema import StructuredIntegerInputSchema
from app.ai.demo_scenarios import (
    DEMO_SCENARIOS,
    SCENARIO_IDS,
    DemoScenarioProvider,
    get_demo_scenario,
    select_demo_scenario,
    validate_demo_input,
)
from app.runner import compile_c_source


def _agent_contracts(scenario_id):
    scenario = get_demo_scenario(scenario_id)
    provider = DemoScenarioProvider(scenario_id)
    reconstructed = reconstruct_problem(
        scenario["student"], scenario["statement"], provider=provider
    )
    assert reconstructed["status"] == "ready"
    candidate = reconstructed["candidates"][0]
    references = generate_reference_solutions(
        {"problem_statement": scenario["statement"], "constraints": scenario["constraints"]},
        provider,
    )
    assert references["status"] == "generated_unverified"
    spec = AssignmentSpec.create_draft(
        candidate,
        constraints=tuple(scenario["constraints"]),
        input_format=candidate["input_format"],
        output_format=candidate["output_format"],
        input_schema=scenario["input_schema"],
    ).confirm(instructor_approved=True)
    schema = StructuredIntegerInputSchema.from_dict(scenario["input_schema"])
    agent3a = generate_agent3a_program(
        provider, problem=spec.to_dict(), schema=scenario["input_schema"],
        references=references, student_source=scenario["student"], max_cases=4,
    )
    generated = execute_agent3a_program(
        agent3a, seed=42, schema=schema, max_cases=4,
    )
    agent3b = analyze_agent3b_edges(
        provider, problem=spec.to_dict(), schema=scenario["input_schema"],
        references=references, student_source=scenario["student"],
    )
    validated = validate_agent3b_edges(agent3b, schema=schema)
    assert generated["status"] == "generated"
    assert validated["status"] == "validated"
    assert all(validate_demo_input(scenario_id, case["input"]) for case in generated["inputs"])
    if scenario_id == "fibonacci":
        assert [case["input_size"] for case in generated["inputs"]] == [10, 20, 30, 40]
    if scenario_id == "traveling_salesman":
        assert [case["input_size"] for case in generated["inputs"]] == [4, 7, 9, 12]
    assert all(validate_demo_input(scenario_id, case["input"]) for case in validated["cases"])
    assert analyze_complexity(scenario["student"], provider)["status"] == "analyzed"
    proof = verify_algorithm(
        {"problem_statement": scenario["statement"], "constraints": scenario["constraints"]},
        {"code": scenario["student"], "algorithm": "Inspect the submitted implementation."},
        provider,
    )
    assert proof["status"] == "proof_sketch"
    assert review_code_quality(scenario["student"], provider)["status"] == "completed"
    assert provider.calls == ["agent1", "agent2", "agent3a", "agent3b", "agent4", "agent5", "agent6"]


def test_demo_scenarios_are_complete_and_provider_is_task_routed():
    assert set(DEMO_SCENARIOS) == {"binary_search", "subset_sum", "fibonacci", "traveling_salesman"}
    assert select_demo_scenario()["scenario_id"] in SCENARIO_IDS
    assert select_demo_scenario("binary_search")["scenario_id"] == "binary_search"
    for scenario_id in SCENARIO_IDS:
        scenario = get_demo_scenario(scenario_id)
        assert set(scenario["agent_responses"]) == {
            "agent1", "agent2", "agent3a", "agent3b", "agent4", "agent5", "agent6"
        }
        assert len(scenario["edge_cases"]) >= 8
        assert compile_c_source(scenario["student"])["status"] == "compiled"
        for name in ("brute_force", "efficient"):
            assert compile_c_source(scenario[name]["code"])["status"] == "compiled"
        _agent_contracts(scenario_id)


def _configure_instructor(monkeypatch, tmp_path):
    import app.web as web
    import app.orchestrator as orchestrator
    from app.ai import demo_scenarios

    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "ui-state.sqlite3"))
    monkeypatch.setenv("AUTOGRADER_USERNAME", "demo-instructor")
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "confirmation-key-for-tests")
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-with-more-than-32-bytes")
    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    monkeypatch.setenv("AUTOGRADER_MOCK_MODE", "0")
    monkeypatch.delenv("PREPARATION_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "intentionally-invalid-if-used")

    password = "demo-password-for-tests"
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    monkeypatch.setenv(
        "AUTOGRADER_PASSWORD_HASH",
        f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}",
    )

    def forbidden_provider(*args, **kwargs):
        raise AssertionError("Demo attempted to construct a real AI provider")

    monkeypatch.setattr(web, "create_ai_provider", forbidden_provider)
    monkeypatch.setattr(orchestrator, "create_ai_provider", forbidden_provider)
    with web._LOGIN_ATTEMPTS_LOCK:
        web._LOGIN_ATTEMPTS.clear()
    return web, demo_scenarios, password


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_demo_submission_pins_scenario_and_runs_full_workflow(
    monkeypatch, tmp_path, scenario_id
):
    web, demo_scenarios, password = _configure_instructor(monkeypatch, tmp_path)
    scenario = get_demo_scenario(scenario_id)
    selections = []

    def choose_once(requested=None):
        selections.append(requested or scenario_id)
        return get_demo_scenario(requested or scenario_id)

    monkeypatch.setattr(demo_scenarios, "select_demo_scenario", choose_once)
    client = TestClient(web.app)

    # The instructor session remains mandatory even though Demo needs no prep key.
    unauthenticated = client.post(
        "/api/ui/prepare",
        json={"source": "", "problem_statement": "ignored", "demo_mode": True},
    )
    assert unauthenticated.status_code == 401

    login = client.post(
        "/api/ui/login",
        json={"username": "demo-instructor", "password": password},
    )
    assert login.status_code == 200

    prepared = client.post(
        "/api/ui/prepare",
        json={"source": "editor contents must be ignored", "problem_statement": "wrong problem", "demo_mode": True, "demo_scenario_id": scenario_id},
    )
    assert prepared.status_code == 200, prepared.text
    prepared_data = prepared.json()
    assert prepared_data["demo_scenario_id"] == scenario_id
    assert prepared_data["source_sha256"] == hashlib.sha256(scenario["student"].encode()).hexdigest()
    assert prepared_data["demo_mode"] is True
    assert prepared_data["analysis_mode"] == "simulated"
    assert selections == [scenario_id]
    submission_id = prepared_data["submission_id"]

    confirmed = client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    references = client.post(
        "/api/ui/generate-references", json={"submission_id": submission_id}
    )
    assert references.status_code == 200, references.text
    assert references.json()["provider_mode"] == "demo_scenario"
    assert references.json()["brute_force"]["code"] == scenario["brute_force"]["code"]

    plans = client.post(
        "/api/ui/generate-tests",
        json={"submission_id": submission_id, "random_count": 2, "adversarial_count": 2},
    )
    assert plans.status_code == 200, plans.text
    plan_data = plans.json()
    assert plan_data["status"] == "generated"
    assert plan_data["demo_scenario_id"] == scenario_id
    assert plan_data["agent3a"]["status"] == "generated"
    assert plan_data["agent3a"]["generation"]["validation"]["all_cases_validated"] is True
    assert plan_data["agent3b"]["status"] == "validated"
    assert all(validate_demo_input(scenario_id, item["input"]) for item in plan_data["agent3a"]["generation"]["inputs"])

    execution = client.post(
        "/api/ui/execute-tests", json={"submission_id": submission_id}
    )
    assert execution.status_code == 200, execution.text
    result = execution.json()
    assert result["demo_scenario_id"] == scenario_id
    assert result["provider_mode"] == "demo_scenario"
    assert result["test_evaluation"]["passed"] == len(scenario["edge_cases"])
    assert result["test_evaluation"]["failed"] == 0
    assert result["reference_validation"]["brute_force"]["passed"] is True
    assert result["reference_validation"]["efficient"]["passed"] is True
    assert result["agent3a_benchmark"]["batches"]["student"]["results"]
    assert result["random_test_execution"]["executed"] > 0
    assert result["adversarial_execution"]["executed"] > 0
    assert result["complexity_analysis"]["analysis_mode"] == "simulated"
    assert result["mathematical_verification"]["analysis_mode"] == "simulated"
    assert result["code_quality"]["analysis_mode"] == "simulated"
    assert result["grading"]["status"] in {"graded", "provisional"}
    assert result["grading"]["reproducibility"]["fingerprint"]
    assert set(result["metric_scores"]) == {
        "correctness", "edge_cases", "mathematical_correctness", "complexity",
        "readability", "modularity", "design_originality",
    }
    assert all(value is not None for value in result["metric_scores"].values())
    assert result["grading"]["grade_band"] in {"A", "B", "C", "D", "F"}
    assert result["grading"]["reproducibility"]["grade_snapshot_key"]
    assert result["grading"]["reproducibility"]["grade_snapshot_reused"] is False
    assert result["grading"]["reproducibility"]["grade_snapshot_persisted"] is True
    assert result["grading"]["reproducibility"]["grade_snapshot_status"] == "saved"
    assert result["grading"]["reproducibility"]["grade_snapshot_backend"] in {"sqlite_local", "neon_postgresql"}
    assert result["complexity_analysis"]["complexity_graphs"]
    assert all("status" in curve for curve in result["complexity_analysis"]["complexity_graphs"].values())

    report = client.post(
        "/api/ui/generate-report", json={"submission_id": submission_id}
    )
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert report.content.startswith(b"%PDF-")
    assert selections == [scenario_id]


def test_normal_preparation_still_requires_its_api_key(monkeypatch):
    import app.web as web

    client = TestClient(web.app)
    monkeypatch.delenv("PREPARATION_API_KEY", raising=False)
    missing = client.post(
        "/api/prepare", json={"source": "int main(void) { return 0; }"}
    )
    assert missing.status_code == 503

    monkeypatch.setenv("PREPARATION_API_KEY", "normal-preparation-test-key")
    invalid = client.post(
        "/api/prepare",
        json={"source": "int main(void) { return 0; }"},
        headers={"X-Preparation-Key": "wrong-key"},
    )
    assert invalid.status_code == 401


def test_instructor_login_rate_limit_counts_failed_attempts(monkeypatch, tmp_path):
    web, _, _ = _configure_instructor(monkeypatch, tmp_path)
    client = TestClient(web.app)
    for _ in range(5):
        response = client.post(
            "/api/ui/login",
            json={"username": "demo-instructor", "password": "wrong"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/ui/login",
        json={"username": "demo-instructor", "password": "wrong"},
    )
    assert limited.status_code == 429
