from fastapi.testclient import TestClient

from app.web import app

client = TestClient(app)


def test_health_reports_execution_disabled():
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["code_execution_enabled"] is False
    assert data["ui_enabled"] is True


def test_api_status_does_not_claim_grading_is_enabled():
    response = client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["evaluation_enabled"] is False
    assert "secure execution environment" in data["message"]


def test_homepage_loads():
    response = client.get("/")

    assert response.status_code == 200
    assert "AutoGrader" in response.text


def test_api_does_not_advertise_an_evaluation_endpoint():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/status" in paths
    assert "/health" in paths
    assert "/api/evaluate" not in paths
    assert "/api/prepare" in paths


def test_static_analysis_endpoint_never_claims_execution_or_grading():
    response = client.post(
        "/api/analyze",
        json={"source": "int main(void) { int x = 1 / 0; return x; }"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["analysis_only"] is True
    assert data["code_executed"] is False
    assert "source_risks" in data
    assert "complexity" in data
    assert "grade" not in data


def test_static_analysis_rejects_blank_source():
    response = client.post("/api/analyze", json={"source": "   "})

    assert response.status_code == 422


def test_static_analysis_rejects_missing_source():
    response = client.post("/api/analyze", json={})

    assert response.status_code == 422


def test_static_analysis_rejects_oversized_source():
    response = client.post(
        "/api/analyze",
        json={"source": "x" * 262145},
    )

    assert response.status_code == 422


def test_prepare_endpoint_calls_orchestrator_without_execution(monkeypatch):
    import app.web

    captured = {}

    def fake_evaluate_submission(source, problem_statement=None):
        captured["source"] = source
        captured["problem_statement"] = problem_statement
        return {
            "status": "reconstruction_ready",
            "execution_status": "not_run",
            "correctness_assessed": False,
        }

    monkeypatch.setattr(app.web, "evaluate_submission", fake_evaluate_submission)
    monkeypatch.setenv("PREPARATION_API_KEY", "test-secret")

    response = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "test-secret"},
        json={
            "source": "int main(void) { return 0; }",
            "problem_statement": "Read and print an integer.",
        },
    )

    assert response.status_code == 200
    assert captured["source"] == "int main(void) { return 0; }"
    assert captured["problem_statement"] == "Read and print an integer."
    assert response.json()["execution_status"] == "not_run"
    assert response.json()["correctness_assessed"] is False


def test_prepare_endpoint_rejects_requests_when_key_is_unconfigured(monkeypatch):
    monkeypatch.delenv("PREPARATION_API_KEY", raising=False)
    response = client.post(
        "/api/prepare",
        json={"source": "int main(void) { return 0; }"},
    )
    assert response.status_code == 503


def test_prepare_endpoint_rejects_missing_or_invalid_key(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "correct-secret")

    missing = client.post(
        "/api/prepare",
        json={"source": "int main(void) { return 0; }"},
    )
    invalid = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "wrong-secret"},
        json={"source": "int main(void) { return 0; }"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_prepare_endpoint_rejects_blank_source(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "test-secret")
    response = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "test-secret"},
        json={"source": "   "},
    )
    assert response.status_code == 422


def test_prepare_endpoint_rejects_blank_problem_statement(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "test-secret")
    response = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "test-secret"},
        json={"source": "int main(void) { return 0; }", "problem_statement": "  "},
    )
    assert response.status_code == 422


def test_prepare_rate_limit_blocks_excess_requests(monkeypatch):
    import app.web

    monkeypatch.setenv("PREPARATION_API_KEY", "rate-test-secret")
    monkeypatch.setenv("PREPARATION_RATE_LIMIT", "2")
    monkeypatch.setenv("PREPARATION_RATE_WINDOW_SECONDS", "60")
    app.web._PREPARATION_REQUESTS.clear()
    monkeypatch.setattr(
        app.web,
        "evaluate_submission",
        lambda **kwargs: {"status": "ready"},
    )

    headers = {"X-Preparation-Key": "rate-test-secret"}
    payload = {"source": "int main(void) { return 0; }"}

    assert client.post("/api/prepare", headers=headers, json=payload).status_code == 200
    assert client.post("/api/prepare", headers=headers, json=payload).status_code == 200

    blocked = client.post("/api/prepare", headers=headers, json=payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_prepare_rate_limit_resets_after_window(monkeypatch):
    import app.web

    monkeypatch.setenv("PREPARATION_API_KEY", "reset-test-secret")
    monkeypatch.setenv("PREPARATION_RATE_LIMIT", "1")
    monkeypatch.setenv("PREPARATION_RATE_WINDOW_SECONDS", "60")
    app.web._PREPARATION_REQUESTS.clear()
    monkeypatch.setattr(
        app.web,
        "evaluate_submission",
        lambda **kwargs: {"status": "ready"},
    )

    clock = {"now": 100.0}
    monkeypatch.setattr(app.web.time, "monotonic", lambda: clock["now"])

    headers = {"X-Preparation-Key": "reset-test-secret"}
    payload = {"source": "int main(void) { return 0; }"}

    assert client.post("/api/prepare", headers=headers, json=payload).status_code == 200
    assert client.post("/api/prepare", headers=headers, json=payload).status_code == 429

    clock["now"] = 161.0
    assert client.post("/api/prepare", headers=headers, json=payload).status_code == 200


def test_invalid_key_does_not_consume_rate_limit(monkeypatch):
    import app.web

    monkeypatch.setenv("PREPARATION_API_KEY", "valid-rate-secret")
    monkeypatch.setenv("PREPARATION_RATE_LIMIT", "1")
    app.web._PREPARATION_REQUESTS.clear()
    monkeypatch.setattr(
        app.web,
        "evaluate_submission",
        lambda **kwargs: {"status": "ready"},
    )

    payload = {"source": "int main(void) { return 0; }"}

    invalid = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "wrong-secret"},
        json=payload,
    )
    valid = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "valid-rate-secret"},
        json=payload,
    )
    blocked = client.post(
        "/api/prepare",
        headers={"X-Preparation-Key": "valid-rate-secret"},
        json=payload,
    )

    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert blocked.status_code == 429


def test_instructor_confirmation_endpoint_confirms_valid_draft(monkeypatch):
    from analyzers.assignment_spec import AssignmentSpec

    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-12345678901234567890")
    draft = AssignmentSpec.create_draft(
        {
            "id": "sum",
            "title": "Sum two integers",
            "problem_statement": "Read two integers and print their sum.",
        },
        constraints=("Both integers are within signed 32-bit range.",),
        input_format="Two integers separated by whitespace.",
        output_format="Print their sum followed by a newline.",
    )

    response = client.post(
        "/api/confirm-assignment",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": draft.to_dict(),
            "expected_fingerprint": draft.fingerprint(),
            "draft_token": __import__(
                "app.web", fromlist=["_create_draft_token"]
            )._create_draft_token(draft.fingerprint()),
            "instructor_approved": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["assignment_spec"]["confirmed"] is True


def test_instructor_confirmation_requires_separate_key(monkeypatch):
    monkeypatch.delenv("INSTRUCTOR_CONFIRMATION_KEY", raising=False)
    response = client.post(
        "/api/confirm-assignment",
        json={
            "assignment_spec": {},
            "expected_fingerprint": "0" * 64,
            "draft_token": "invalid-test-token",
            "instructor_approved": True,
        },
    )
    assert response.status_code == 503


def test_instructor_confirmation_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "correct-instructor-key")
    response = client.post(
        "/api/confirm-assignment",
        headers={"X-Instructor-Key": "wrong-key"},
        json={
            "assignment_spec": {},
            "expected_fingerprint": "0" * 64,
            "draft_token": "invalid-test-token",
            "instructor_approved": True,
        },
    )
    assert response.status_code == 401


def test_instructor_confirmation_rejects_missing_approval(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    response = client.post(
        "/api/confirm-assignment",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": {},
            "expected_fingerprint": "0" * 64,
            "draft_token": "invalid-test-token",
            "instructor_approved": False,
        },
    )
    assert response.status_code == 403


def test_instructor_confirmation_rejects_modified_draft(monkeypatch):
    from analyzers.assignment_spec import AssignmentSpec

    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    draft = AssignmentSpec.create_draft(
        {
            "id": "sum",
            "title": "Sum two integers",
            "problem_statement": "Read two integers and print their sum.",
        },
        input_format="Two integers.",
        output_format="Print their sum.",
    )
    modified = draft.to_dict()
    modified["output_format"] = "Print their product."

    response = client.post(
        "/api/confirm-assignment",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": modified,
            "expected_fingerprint": draft.fingerprint(),
            "instructor_approved": True,
        },
    )
    assert response.status_code == 422


def _reference_generation_spec(confirmed=True):
    from analyzers.assignment_spec import AssignmentSpec

    draft = AssignmentSpec.create_draft(
        {
            "id": "sum",
            "title": "Sum two integers",
            "problem_statement": "Read two integers and print their sum.",
        },
        input_format="Two integers separated by whitespace.",
        output_format="Print their sum followed by a newline.",
    )
    return draft.confirm(instructor_approved=True) if confirmed else draft


def test_reference_generation_endpoint_accepts_confirmed_spec(monkeypatch):
    from unittest.mock import patch

    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-12345678901234567890")
    spec = _reference_generation_spec()
    from app.web import _create_approval_token
    token = _create_approval_token(spec.fingerprint())

    with patch(
        "app.orchestrator.generate_reference_solutions_for_confirmed_spec",
        return_value={"status": "generated_unverified", "references_trusted": False},
    ) as generate:
        response = client.post(
            "/api/generate-references",
            headers={"X-Instructor-Key": "instructor-secret"},
            json={
                "assignment_spec": spec.to_dict(),
                "expected_fingerprint": spec.fingerprint(),
                "approval_token": token,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "generated_unverified"
    assert response.json()["references_trusted"] is False
    generate.assert_called_once()


def test_reference_generation_endpoint_rejects_unconfirmed_spec(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    spec = _reference_generation_spec(confirmed=False)

    response = client.post(
        "/api/generate-references",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": spec.to_dict(),
            "expected_fingerprint": spec.fingerprint(),
            "approval_token": "test-invalid-token",
        },
    )

    assert response.status_code == 422


def test_reference_generation_endpoint_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    spec = _reference_generation_spec()

    response = client.post(
        "/api/generate-references",
        headers={"X-Instructor-Key": "wrong-key"},
        json={
            "assignment_spec": spec.to_dict(),
            "expected_fingerprint": spec.fingerprint(),
            "approval_token": "test-invalid-token",
        },
    )

    assert response.status_code == 401


def test_reference_generation_endpoint_rejects_modified_spec(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    spec = _reference_generation_spec()
    modified = spec.to_dict()
    modified["output_format"] = "Print their product."

    response = client.post(
        "/api/generate-references",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": modified,
            "expected_fingerprint": spec.fingerprint(),
            "approval_token": "test-invalid-token",
        },
    )

    assert response.status_code == 422


def test_instructor_confirmation_rejects_recomputed_modified_draft(monkeypatch):
    from analyzers.assignment_spec import AssignmentSpec
    from app.web import _create_draft_token

    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-secret")
    monkeypatch.setenv(
        "INSTRUCTOR_TOKEN_SIGNING_KEY",
        "test-signing-key-12345678901234567890",
    )

    draft = AssignmentSpec.create_draft(
        {
            "id": "sum",
            "title": "Sum two integers",
            "problem_statement": "Read two integers and print their sum.",
        },
        input_format="Two integers.",
        output_format="Print their sum.",
    )
    original_token = _create_draft_token(draft.fingerprint())

    modified_values = draft.to_dict()
    modified_values["output_format"] = "Print their product."
    modified_values["constraints"] = tuple(
        modified_values.get("constraints", ())
    )
    modified = AssignmentSpec(**modified_values)

    response = client.post(
        "/api/confirm-assignment",
        headers={"X-Instructor-Key": "instructor-secret"},
        json={
            "assignment_spec": modified.to_dict(),
            "expected_fingerprint": modified.fingerprint(),
            "draft_token": original_token,
            "instructor_approved": True,
        },
    )

    assert response.status_code == 422
    assert "draft token" in response.json()["detail"].lower()
