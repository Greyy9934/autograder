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
