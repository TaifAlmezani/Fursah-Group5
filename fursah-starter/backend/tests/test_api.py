"""Public HTTP contract through the FastAPI app (TestClient, no live model)."""
from __future__ import annotations


def test_health(client):
    assert client.get("/health").status_code == 200


def test_ready(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"storage": True, "application": True}


def test_details_ok(client):
    response = client.get("/api/v1/opportunities/SRC-0001")
    assert response.status_code == 200
    body = response.json()
    assert body["opportunity_id"] == "SRC-0001"
    assert body["title"]
    assert body["source_ids"]


def test_details_not_found(client):
    response = client.get("/api/v1/opportunities/NOPE-9999")
    assert response.status_code == 404
    assert response.json()["error_code"] == "FURSAH_OPPORTUNITY_NOT_FOUND"


def test_discover_ok(client):
    body = {
        "request_id": "api-ok",
        "query": "أبحث عن ورشة برمجة",
        "profile": {"interests": ["البرمجة"], "skills": None},
        "constraints": {"opportunity_types": ["workshop"]},
    }
    response = client.post("/api/v1/discover", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert 1 <= len(payload["recommendations"]) <= 3
    assert payload["recommendations"][0]["source_ids"]


def test_discover_invalid_returns_422(client):
    response = client.post("/api/v1/discover", json={"query": "", "profile": {}, "constraints": {}})
    assert response.status_code == 422
    assert response.json()["error_code"] == "FURSAH_REQUEST_VALIDATION_ERROR"
