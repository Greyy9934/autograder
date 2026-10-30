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
