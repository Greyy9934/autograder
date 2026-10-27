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
