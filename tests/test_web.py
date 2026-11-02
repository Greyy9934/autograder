from fastapi.testclient import TestClient
import pytest

import app.web as web
from app.web import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_login_rate_limit_state():
    with web._LOGIN_ATTEMPTS_LOCK:
        web._LOGIN_ATTEMPTS.clear()


def test_health_reports_execution_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "health.sqlite3"))
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["code_execution_enabled"] is False
    assert data["ui_enabled"] is True
    assert data["storage"] == "sqlite_local"


def test_health_fails_when_production_database_is_missing(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AUTOGRADER_STATE_DB", raising=False)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Persistent database unavailable."


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
    assert "Live analysis sends the problem statement and submitted C source" in response.text
    assert "Demo mode uses simulated responses" in response.text


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
    assert data["preflight"]["decision"] == "continue"
    assert "program_structure" in data["complexity"]
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
        input_schema={
            "version": 1,
            "fields": [
                {"name": "a", "type": "int", "min": -100, "max": 100},
                {"name": "b", "type": "int", "min": -100, "max": 100},
            ],
        },
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
        input_schema={
            "version": 1,
            "fields": [
                {"name": "a", "type": "int", "min": -100, "max": 100},
                {"name": "b", "type": "int", "min": -100, "max": 100},
            ],
        },
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
        input_schema={
            "version": 1,
            "fields": [
                {"name": "a", "type": "int", "min": -100, "max": 100},
                {"name": "b", "type": "int", "min": -100, "max": 100},
            ],
        },
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
        input_schema={
            "version": 1,
            "fields": [
                {"name": "a", "type": "int", "min": -100, "max": 100},
                {"name": "b", "type": "int", "min": -100, "max": 100},
            ],
        },
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


def _set_test_ui_credentials(monkeypatch):
    import hashlib

    username = "test-instructor"
    password = "test-password-for-tests-only"
    salt = b"autograder-test-salt"
    iterations = 600000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, iterations
    )
    encoded = (
        f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"
    )
    monkeypatch.setenv("AUTOGRADER_USERNAME", username)
    monkeypatch.setenv("AUTOGRADER_PASSWORD_HASH", encoded)
    return username, password


def test_instructor_ui_login_sets_secure_session_cookie(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "prep-test-secret")
    username, password = _set_test_ui_credentials(monkeypatch)
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-12345678901234567890")

    response = client.post(
        "/api/ui/login",
        json={"username": username, "password": password},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "prep-test-secret" not in response.text
    assert "instructor-test-secret" not in response.text


def test_instructor_ui_login_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "prep-test-secret")
    username, _ = _set_test_ui_credentials(monkeypatch)

    response = client.post(
        "/api/ui/login",
        json={"username": username, "password": "wrong-test-password"},
    )

    assert response.status_code == 401


def test_instructor_ui_prepare_requires_session(monkeypatch):
    monkeypatch.setenv("PREPARATION_API_KEY", "prep-test-secret")

    response = client.post(
        "/api/ui/prepare",
        json={"source": "int main(void) { return 0; }"},
    )

    assert response.status_code == 401


def test_ui_preflight_compiles_before_agent1_and_reports_result(monkeypatch):
    import app.web

    client = _ui_test_client(monkeypatch)
    monkeypatch.setattr(app.web, "preflight", lambda source: {
        "decision": "continue", "status": "source_validated", "source_bytes": len(source), "reasons": []
    })
    monkeypatch.setattr(app.web, "compile_c_source", lambda source: {
        "status": "compiled", "compiler_stderr": ""
    })

    response = client.post(
        "/api/ui/preflight",
        json={"source": "int main(void) { return 0; }"},
    )

    assert response.status_code == 200
    assert response.json()["preflight"]["decision"] == "continue"
    assert response.json()["compilation"]["status"] == "compiled"
    assert response.json()["agent1_started"] is False

def test_instructor_ui_prepare_uses_server_side_key(monkeypatch):
    import app.web

    monkeypatch.setenv("PREPARATION_API_KEY", "prep-test-secret")
    username, password = _set_test_ui_credentials(monkeypatch)
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-test-secret")
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-12345678901234567890")

    captured = {}

    def fake_prepare(source, problem_statement=None):
        captured["source"] = source
        return {"status": "ready"}

    monkeypatch.setattr(app.web, "evaluate_submission", fake_prepare)

    session = client.post(
        "/api/ui/login",
        json={"username": username, "password": password},
    )
    assert session.status_code == 200

    response = client.post(
        "/api/ui/prepare",
        json={"source": "int main(void) { return 0; }"},
    )

    assert response.status_code == 200
    assert captured["source"] == "int main(void) { return 0; }"


def test_instructor_ui_logout_clears_session_cookie():
    response = client.post("/api/ui/logout")

    assert response.status_code == 200
    assert response.json()["status"] == "logged_out"
    assert "max-age=0" in response.headers["set-cookie"].lower()


def _ui_test_client(monkeypatch):
    from fastapi.testclient import TestClient
    import app.web

    # Each test gets an isolated rate-limit state; production behavior is unchanged.
    with app.web._LOGIN_ATTEMPTS_LOCK:
        app.web._LOGIN_ATTEMPTS.clear()

    monkeypatch.setenv("PREPARATION_API_KEY", "prep-test-secret")
    monkeypatch.setenv("INSTRUCTOR_CONFIRMATION_KEY", "instructor-test-secret")
    username, password = _set_test_ui_credentials(monkeypatch)
    monkeypatch.setenv(
        "INSTRUCTOR_TOKEN_SIGNING_KEY",
        "test-signing-key-12345678901234567890",
    )
    test_client = TestClient(app.web.app)
    response = test_client.post(
        "/api/ui/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return test_client


def _install_ui_workflow_mocks(monkeypatch):
    import hashlib
    import app.web

    source = "int main(void) { return 0; }"
    spec = {
        "title": "Test assignment",
        "problem_statement": "Return zero.",
        "input_format": "One integer.",
        "output_format": "Print zero.",
        "input_schema": {"version": 1, "fields": [
            {"name": "x", "type": "int", "min": -10, "max": 10}
        ]},
    }
    fingerprint = "a" * 64

    def fake_prepare(request, x_preparation_key=""):
        return {
            "status": "ready",
            "assignment_spec_status": "draft_requires_instructor_confirmation",
            "assignment_spec": spec,
            "assignment_spec_fingerprint": fingerprint,
            "assignment_spec_draft_token": "test-draft-token",
            "source_sha256": hashlib.sha256(request.source.encode()).hexdigest(),
        }

    def fake_confirm(request, x_instructor_key=""):
        return {
            "status": "confirmed",
            "assignment_spec": spec,
            "assignment_spec_fingerprint": fingerprint,
            "approval_token": "test-approval-token",
            "confirmation": {"instructor_approved": True},
        }

    def fake_references(request, x_instructor_key=""):
        return {"status": "generated_unverified", "references_trusted": False}

    monkeypatch.setattr(app.web, "prepare_submission", fake_prepare)
    monkeypatch.setattr(app.web, "confirm_assignment", fake_confirm)
    monkeypatch.setattr(app.web, "generate_references", fake_references)
    return source


def test_ui_submission_handoff_requires_approval_and_rejects_duplicate(monkeypatch):
    source = _install_ui_workflow_mocks(monkeypatch)
    test_client = _ui_test_client(monkeypatch)

    prepared = test_client.post("/api/ui/prepare", json={"source": source})
    assert prepared.status_code == 200
    submission_id = prepared.json()["submission_id"]

    before_approval = test_client.post(
        "/api/ui/generate-references",
        json={"submission_id": submission_id},
    )
    assert before_approval.status_code == 403

    approved = test_client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "confirmed"

    duplicate = test_client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert duplicate.status_code == 409

    references = test_client.post(
        "/api/ui/generate-references",
        json={"submission_id": submission_id},
    )
    assert references.status_code == 200
    assert references.json()["references_trusted"] is False


def test_ui_submission_cannot_be_used_by_another_session(monkeypatch):
    source = _install_ui_workflow_mocks(monkeypatch)
    owner = _ui_test_client(monkeypatch)
    other = _ui_test_client(monkeypatch)

    prepared = owner.post("/api/ui/prepare", json={"source": source})
    assert prepared.status_code == 200
    submission_id = prepared.json()["submission_id"]

    stolen = other.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert stolen.status_code == 404


def test_ui_submission_expiry_is_enforced(monkeypatch):
    import app.web

    source = _install_ui_workflow_mocks(monkeypatch)
    test_client = _ui_test_client(monkeypatch)

    prepared = test_client.post("/api/ui/prepare", json={"source": source})
    assert prepared.status_code == 200
    submission_id = prepared.json()["submission_id"]

    app.web._UI_SUBMISSIONS[submission_id]["expires_at"] = 0

    expired = test_client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert expired.status_code == 404


def test_ui_agent3_generates_tests_only_after_approval(monkeypatch):
    import app.web

    source = _install_ui_workflow_mocks(monkeypatch)
    test_client = _ui_test_client(monkeypatch)

    prepared = test_client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    payload = {
        "submission_id": submission_id,
        "random_count": 1,
    }

    denied = test_client.post("/api/ui/generate-tests", json=payload)
    assert denied.status_code == 403

    approved = test_client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert approved.status_code == 200

    confirmed_spec = {
        "problem_id": "test-problem",
        "title": "Test assignment",
        "problem_statement": "Return zero.",
        "constraints": (),
        "input_format": "One integer.",
        "output_format": "Print one integer.",
        "input_schema": {"version": 1, "fields": [
            {"name": "x", "type": "int", "min": 0, "max": 100}
        ]},
        "time_limit_seconds": 2.0,
        "memory_limit_mb": 256,
        "version": 1,
        "confirmed": True,
    }
    app.web._UI_SUBMISSIONS[submission_id]["confirmed_spec"] = confirmed_spec
    app.web._UI_SUBMISSIONS[submission_id]["references"] = {
        "brute_force": {"code": "int main(void) { return 0; }"},
        "efficient": {"code": "int main(void) { return 0; }"},
    }

    calls = {"plans": 0}

    def fake_generate(**kwargs):
        calls["plans"] += 1
        assert kwargs["source"] == source
        assert kwargs["spec"].confirmed is True
        assert kwargs["schema"].validate("50\n")
        assert not kwargs["schema"].validate("101\n")
        return {
            "status": "generated",
            "execution_performed": False,
            "random_tests": {"status": "generated"},
            "adversarial_tests": {"status": "planned"},
        }

    monkeypatch.setattr(app.web, "generate_test_plans", fake_generate)

    response = test_client.post("/api/ui/generate-tests", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "generated"
    assert response.json()["execution_performed"] is False
    assert app.web._UI_SUBMISSIONS[submission_id]["test_plans"]["status"] == "generated"

    # An identical retry must return the cached plan and avoid repeating Agent 3.
    repeated = test_client.post("/api/ui/generate-tests", json=payload)
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    assert calls["plans"] == 1



def test_ui_agent3_uses_approved_structured_schema_end_to_end(monkeypatch):
    import app.web
    from analyzers.structured_input_schema import StructuredIntegerInputSchema

    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    assert prepared.status_code == 200
    submission_id = prepared.json()["submission_id"]

    approved = client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    assert approved.status_code == 200

    approved_schema = {
        "version": 1,
        "fields": [
            {"name": "n", "type": "int", "min": 1, "max": 100},
            {
                "name": "values",
                "type": "int_array",
                "length_from": "n",
                "min": -1000,
                "max": 1000,
            },
            {"name": "target", "type": "int", "min": -1000, "max": 1000},
        ],
        "size_field": "values",
    }

    record = app.web._UI_SUBMISSIONS[submission_id]
    record["confirmed_spec"] = {
        "problem_id": "structured-test",
        "title": "Structured assignment",
        "problem_statement": "Read an array and a target.",
        "constraints": (),
        "input_format": "n, followed by n integers, followed by target.",
        "output_format": "Print the result.",
        "time_limit_seconds": 2.0,
        "memory_limit_mb": 256,
        "version": 1,
        "confirmed": True,
        "input_schema": approved_schema,
    }
    record["references"] = {
        "brute_force": {"code": "int main(void) { return 0; }"},
        "efficient": {"code": "int main(void) { return 0; }"},
    }

    captured = {"agent_calls": 0}
    provider = object()
    sample_input = "3\n10 20 30\n20\n"
    generated_cases = [{"input": sample_input, "input_size": 3}]

    def fake_generate_test_plans(**kwargs):
        assert isinstance(kwargs["schema"], StructuredIntegerInputSchema)
        assert kwargs["schema"].validate(sample_input)
        assert kwargs["schema"].input_size(sample_input) == 3
        captured["generation_schema"] = kwargs["schema"]
        return {
            "status": "generated",
            "execution_performed": False,
            "random_tests": {"status": "generated"},
            "adversarial_tests": {"status": "planned"},
        }

    def fake_create_provider():
        return provider

    def fake_generate_agent3a_program(
        actual_provider, *, problem, schema, references, student_source, max_cases
    ):
        assert actual_provider is provider
        captured["agent_calls"] += 1
        captured["agent3a_schema_data"] = schema
        return {"status": "program_generated_unexecuted"}

    def fake_execute_agent3a_program(
        agent3a, *, seed, schema, max_cases
    ):
        assert isinstance(schema, StructuredIntegerInputSchema)
        assert schema.validate(sample_input)
        assert schema.input_size(sample_input) == 3
        captured["agent3a_execution_schema"] = schema
        return {"status": "generated", "inputs": generated_cases}

    def fake_analyze_agent3b_edges(
        actual_provider, *, problem, schema, references, student_source
    ):
        assert actual_provider is provider
        captured["agent_calls"] += 1
        captured["agent3b_schema_data"] = schema
        return {"status": "proposed_unvalidated", "cases": []}

    def fake_validate_agent3b_edges(agent3b, *, schema):
        assert isinstance(schema, StructuredIntegerInputSchema)
        assert schema.validate(sample_input)
        captured["agent3b_validation_schema"] = schema
        return {
            "status": "validated",
            "cases": [
                {
                    "input": sample_input,
                    "target": ["student"],
                    "targeted_implementation": ["student"],
                }
            ],
            "validation": {"valid": True},
        }

    def fake_benchmark(student, brute, efficient, cases, *, time_budget_seconds):
        assert cases == generated_cases
        assert time_budget_seconds == 2.0
        assert cases[0]["input_size"] == 3
        captured["benchmark_called"] = True
        return {"status": "completed"}

    monkeypatch.setattr(app.web, "generate_test_plans", fake_generate_test_plans)
    monkeypatch.setattr(app.web, "create_ai_provider", fake_create_provider)
    monkeypatch.setattr(
        app.web, "generate_agent3a_program", fake_generate_agent3a_program
    )
    monkeypatch.setattr(
        app.web, "execute_agent3a_program", fake_execute_agent3a_program
    )
    monkeypatch.setattr(
        app.web, "analyze_agent3b_edges", fake_analyze_agent3b_edges
    )
    monkeypatch.setattr(
        app.web, "validate_agent3b_edges", fake_validate_agent3b_edges
    )
    monkeypatch.setattr(
        app.web, "benchmark_three_programs_parallel", fake_benchmark
    )

    response = client.post(
        "/api/ui/generate-tests",
        json={
            "submission_id": submission_id,
            "random_count": 1,
            "adversarial_count": 1,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "generated"

    # Both AI agents receive the same approved schema data.
    assert captured["agent3a_schema_data"] == approved_schema
    assert captured["agent3b_schema_data"] == approved_schema
    assert (
        captured["agent3a_schema_data"]
        is captured["agent3b_schema_data"]
    )

    # Generation, Agent 3A execution and Agent 3B validation use
    # structured schema instances rather than legacy token-count schemas.
    assert isinstance(
        captured["generation_schema"], StructuredIntegerInputSchema
    )
    assert captured["agent3a_execution_schema"] is captured["generation_schema"]
    assert captured["agent3b_validation_schema"] is captured["generation_schema"]

    # The validated Agent 3A cases are the cases sent to the benchmark.
    assert captured["benchmark_called"] is True
    assert record["input_schema"] == approved_schema
    assert record["agent3a_benchmark"]["status"] == "completed"
    assert captured["agent_calls"] == 2

    repeated = client.post(
        "/api/ui/generate-tests",
        json={
            "submission_id": submission_id,
            "random_count": 1,
            "adversarial_count": 1,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    assert captured["agent_calls"] == 2


def test_ui_agent3_rejects_invalid_input_bounds(monkeypatch):
    source = _install_ui_workflow_mocks(monkeypatch)
    test_client = _ui_test_client(monkeypatch)

    prepared = test_client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    test_client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )

    response = test_client.post(
        "/api/ui/generate-tests",
        json={
            "submission_id": submission_id,
            "token_count": 1,
            "minimum": 100,
            "maximum": 0,
        },
    )
    assert response.status_code == 422


def test_ui_agent3_rejects_unauthenticated_request(monkeypatch):
    source = _install_ui_workflow_mocks(monkeypatch)
    test_client = _ui_test_client(monkeypatch)
    test_client.post("/api/ui/logout")

    response = test_client.post(
        "/api/ui/generate-tests",
        json={
            "submission_id": "a" * 32,
            "token_count": 1,
            "minimum": 0,
            "maximum": 100,
        },
    )
    assert response.status_code == 401


def test_ui_execution_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LOCAL_CODE_EXECUTION_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    response = client.post(
        "/api/ui/execute-tests",
        json={"submission_id": submission_id},
    )
    assert response.status_code == 503


def _mock_postgres_storage_for_production_test(monkeypatch, tmp_path):
    import sqlite3
    import app.ui_storage as storage

    database_path = tmp_path / "mock-neon.sqlite3"

    def connect():
        raw = sqlite3.connect(database_path, timeout=10, isolation_level=None)
        raw.execute("PRAGMA busy_timeout = 10000")
        raw.execute("PRAGMA foreign_keys = ON")
        return storage._Connection(raw, postgres=False)

    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://mock-neon/test")
    monkeypatch.setattr(storage, "_connect", connect)


def test_ui_execution_is_blocked_in_production(monkeypatch, tmp_path):
    _mock_postgres_storage_for_production_test(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "production")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    response = client.post(
        "/api/ui/execute-tests",
        json={"submission_id": submission_id},
    )
    assert response.status_code == 403


def test_ui_execution_uses_stored_plans_and_caches_result(monkeypatch):
    import app.web

    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )

    record = app.web._UI_SUBMISSIONS[submission_id]
    schema = {"version": 1, "fields": [
        {"name": "a", "type": "int", "min": 0, "max": 100},
        {"name": "b", "type": "int", "min": 0, "max": 100},
    ]}
    record["confirmed_spec"]["problem_id"] = "test-problem"
    record["confirmed_spec"]["input_schema"] = schema
    from analyzers.assignment_spec import AssignmentSpec
    spec_data = dict(record["confirmed_spec"])
    spec_data["constraints"] = tuple(spec_data.get("constraints", ()))
    record["confirmed_fingerprint"] = AssignmentSpec(**spec_data).fingerprint()
    record["input_schema"] = schema
    plans = {
        "status": "generated",
        "spec_fingerprint": record["confirmed_fingerprint"],
        "random_tests": {},
        "adversarial_tests": {},
    }
    app.web._UI_SUBMISSIONS[submission_id]["test_plans"] = plans
    app.web._UI_SUBMISSIONS[submission_id]["prepared_result"] = {
        "status": "reconstruction_ready"
    }

    calls = []

    def fake_evaluate(**kwargs):
        calls.append(kwargs)
        return {
            "execution_status": "completed",
            "grading": {"status": "provisional"},
        }

    monkeypatch.setattr(app.web, "evaluate_execution_evidence", fake_evaluate)

    payload = {
        "submission_id": submission_id,
        "test_cases": [{"input": "2 3", "expected_output": "5"}],
    }
    first = client.post("/api/ui/execute-tests", json=payload)
    second = client.post("/api/ui/execute-tests", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1
    assert calls[0]["source"] == source
    assert calls[0]["generated_test_plans"] is plans
    assert calls[0]["run_memory_diagnostics"] is True
    assert calls[0]["memory_diagnostic_stdin"] == "2 3"


def test_ui_pdf_report_download_requires_completed_evaluation(monkeypatch):
    import app.web

    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    denied = client.post(
        "/api/ui/generate-report",
        json={"submission_id": submission_id},
    )
    assert denied.status_code == 409

    app.web._UI_SUBMISSIONS[submission_id]["execution_result"] = {
        "status": "completed",
        "execution_status": "completed",
        "grading": {"status": "provisional"},
        "tests": {"passed": 2, "failed": 0, "inconclusive": 0},
    }

    response = client.post(
        "/api/ui/generate-report",
        json={"submission_id": submission_id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


def test_ui_pdf_report_requires_instructor_session(monkeypatch):
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)
    client.post("/api/ui/logout")

    response = client.post(
        "/api/ui/generate-report",
        json={"submission_id": "a" * 32},
    )
    assert response.status_code == 401


def test_ui_complexity_benchmark_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LOCAL_CODE_EXECUTION_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    response = client.post(
        "/api/ui/benchmark-complexity",
        json={
            "submission_id": prepared.json()["submission_id"],
            "benchmark_cases": [{"input_size": 10, "input": "10\n"}],
        },
    )

    assert response.status_code == 503


def test_ui_complexity_benchmark_is_blocked_in_production(monkeypatch, tmp_path):
    _mock_postgres_storage_for_production_test(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "production")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    response = client.post(
        "/api/ui/benchmark-complexity",
        json={
            "submission_id": prepared.json()["submission_id"],
            "benchmark_cases": [{"input_size": 10, "input": "10\n"}],
        },
    )

    assert response.status_code == 403


def test_ui_complexity_benchmark_requires_session_and_approval(monkeypatch):
    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]
    payload = {
        "submission_id": submission_id,
        "benchmark_cases": [{"input_size": 10, "input": "10\n"}],
    }

    denied = client.post("/api/ui/benchmark-complexity", json=payload)
    assert denied.status_code == 403

    client.post(
        "/api/ui/confirm-assignment",
        json={"submission_id": submission_id, "instructor_approved": True},
    )
    client.post("/api/ui/logout")

    unauthenticated = client.post("/api/ui/benchmark-complexity", json=payload)
    assert unauthenticated.status_code == 401


def test_ui_complexity_benchmark_uses_stored_source_and_saves_result(monkeypatch):
    import app.web

    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]
    record = app.web._UI_SUBMISSIONS[submission_id]
    record["confirmed_spec"] = {"title": "Approved test"}
    record["approval_token"] = "approved-test-token"

    calls = []
    benchmark_result = {
        "status": "completed",
        "source_sha256": "test-hash",
        "results": [],
        "chart_data": [],
        "growth_observations": [],
        "interpretation": "Observations only; not a complexity proof.",
    }

    def fake_benchmark(**kwargs):
        calls.append(kwargs)
        return benchmark_result

    monkeypatch.setattr(app.web, "benchmark_complexity", fake_benchmark)

    response = client.post(
        "/api/ui/benchmark-complexity",
        json={
            "submission_id": submission_id,
            "benchmark_cases": [
                {"input_size": 10, "input": "10\n"},
                {"input_size": 100, "input": "100\n"},
            ],
            "repetitions": 2,
        },
    )

    assert response.status_code == 200
    assert response.json() == benchmark_result
    assert len(calls) == 1
    assert calls[0]["source"] == source
    assert calls[0]["benchmark_cases"] == [
        {"input_size": 10, "input": "10\n"},
        {"input_size": 100, "input": "100\n"},
    ]
    assert calls[0]["repetitions"] == 2
    assert record["complexity_benchmark"] == benchmark_result
    assert "grading" not in record


def test_ui_complexity_benchmark_rejects_duplicate_input_sizes(monkeypatch):
    import app.web

    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]
    record = app.web._UI_SUBMISSIONS[submission_id]
    record["confirmed_spec"] = {"title": "Approved test"}
    record["approval_token"] = "approved-test-token"

    response = client.post(
        "/api/ui/benchmark-complexity",
        json={
            "submission_id": submission_id,
            "benchmark_cases": [
                {"input_size": 10, "input": "10\n"},
                {"input_size": 10, "input": "20\n"},
            ],
        },
    )

    assert response.status_code == 422
    assert "complexity_benchmark" not in record


def test_ui_complexity_benchmark_rejects_invalid_request_bounds(monkeypatch):
    monkeypatch.setenv("LOCAL_CODE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "development")
    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]

    response = client.post(
        "/api/ui/benchmark-complexity",
        json={
            "submission_id": submission_id,
            "benchmark_cases": [{"input_size": 0, "input": "0\n"}],
            "repetitions": 11,
        },
    )

    assert response.status_code == 422


def test_ui_pdf_report_includes_saved_complexity_benchmark(monkeypatch):
    import app.web
    from pypdf import PdfReader
    from io import BytesIO

    source = _install_ui_workflow_mocks(monkeypatch)
    client = _ui_test_client(monkeypatch)

    prepared = client.post("/api/ui/prepare", json={"source": source})
    submission_id = prepared.json()["submission_id"]
    record = app.web._UI_SUBMISSIONS[submission_id]

    record["execution_result"] = {
        "status": "completed",
        "execution_status": "completed",
        "grading": {"status": "provisional"},
        "tests": {"passed": 2, "failed": 0, "inconclusive": 0},
    }
    record["complexity_benchmark"] = {
        "status": "completed",
        "measurement_method": "isolated_process_wall_clock",
        "measurement_scope": "Includes sandbox/process startup overhead.",
        "repetitions_per_size": 3,
        "compile_seconds": 0.01,
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
                "successful_runs": 3,
                "failed_runs": 0,
                "median_runtime_seconds": 0.004,
                "minimum_runtime_seconds": 0.003,
                "maximum_runtime_seconds": 0.005,
            },
        ],
        "chart_data": [
            {"input_size": 10, "median_runtime_seconds": 0.001},
            {"input_size": 100, "median_runtime_seconds": 0.004},
        ],
        "growth_observations": [
            {
                "from_input_size": 10,
                "to_input_size": 100,
                "input_size_ratio": 10.0,
                "runtime_ratio": 4.0,
                "interpretation": "Observed ratio only; not an asymptotic complexity proof.",
            }
        ],
        "interpretation": "Empirical observations only; not a Big-O proof.",
        "limitations": ["Process startup overhead is included."],
    }

    response = client.post(
        "/api/ui/generate-report",
        json={"submission_id": submission_id},
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")

    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(response.content)).pages
    )
    assert "Empirical runtime benchmark" in pdf_text
    # Internal runner identifiers are intentionally omitted from the PDF.
    assert "Median (s)" in pdf_text
    assert "0.004000" in pdf_text
    assert "isolated_process_wall_clock" not in pdf_text
    assert "not a Big-O proof" in pdf_text


def test_demo_endpoint_requires_authenticated_instructor(monkeypatch):
    monkeypatch.setenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "test-signing-key-" * 3)
    response = client.post("/api/ui/demo")
    assert response.status_code == 401


def test_grade_snapshot_requires_complete_ai_evidence():
    from types import SimpleNamespace
    from app.web import (
        _grade_metric_snapshot_eligible,
        _grade_snapshot_analysis_identity,
    )

    complete = {
        "agent3a": {"status": "generated"},
        "agent3b": {"status": "validated"},
        "complexity_analysis": {
            "status": "analyzed",
            "ai_analysis": {
                "grading_assessment": {"rating": 3, "evidence": ["bounded loop"]}
            },
        },
        "mathematical_verification": {"status": "proof_sketch"},
        "code_quality": {
            "status": "completed",
            "rubric_ratings": {
                "readability": {"rating": 3, "evidence": ["named variables"]},
                "modularity": {"rating": 2, "evidence": ["separated helper"]},
                "design_originality": {"rating": 1, "evidence": ["custom approach"]},
            },
        },
    }
    assert _grade_metric_snapshot_eligible(complete, object()) is True

    failed = {**complete, "code_quality": {"status": "provider_error"}}
    assert _grade_metric_snapshot_eligible(failed, object()) is False
    assert _grade_metric_snapshot_eligible(complete, None) is False

    first = _grade_snapshot_analysis_identity(
        SimpleNamespace(model="deepseek-flash"), {}
    )
    second = _grade_snapshot_analysis_identity(
        SimpleNamespace(model="deepseek-other"), {}
    )
    assert first["analysis_code_sha256"] == second["analysis_code_sha256"]
    assert first["model"] != second["model"]
