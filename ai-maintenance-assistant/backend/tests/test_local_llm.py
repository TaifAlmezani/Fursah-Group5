import json
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
from app.llm import client as llm
from app.schemas import IssueExtraction, RecommendationOutput


@pytest.mark.parametrize("description,expected", [
    ("المكيف ما يبرد، ما فيه دخان ولا ريحة حريق ولا تسريب", []),
    ("المكيف ما يبرد، لا يوجد دخان", []),
    ("المكيف ما يبرد، بدون دخان", []),
    ("المكيف لا يعمل، ما فيه دخان لكن فيه شرار", ["fire_or_smoke"]),
    ("المكيف لا يعمل وفيه دخان، ولا تسريب", ["fire_or_smoke"]),
    ("المكيف يهرب موية على اللوحة الكهربائية وفيه دخان", ["electrical_risk", "fire_or_smoke"]),
])
def test_demo_extraction_handles_local_negation_and_independent_hazards(description, expected):
    result = llm.run_structured_model(IssueExtraction, "test", {"description": description, "location": "B12"})
    assert result.safety_signals == expected


def test_demo_extraction_does_not_invent_an_unspecified_symptom():
    result = llm.run_structured_model(IssueExtraction, "test", {"description": "عندي مكيف في B12", "location": "B12"})
    assert result.symptoms == [] and "symptoms" in result.missing_fields


@pytest.mark.parametrize("raw", ["NOT VALID JSON", "{}", '{"asset_type":42}', 'null'])
def test_invalid_output_is_not_empty_facts(raw):
    with pytest.raises(llm.StructuredOutputError):
        llm.parse_structured_output(raw, IssueExtraction)


def test_fenced_json_supported_but_explanations_rejected():
    output = llm.parse_structured_output('```json\n{"recommended_action":"فحص الفلتر"}\n```',RecommendationOutput)
    assert output.recommended_action == "فحص الفلتر"
    with pytest.raises(llm.StructuredOutputError):
        llm.parse_structured_output('Explanation {"recommended_action":"فحص"}',RecommendationOutput)


def test_neural_load_failure_never_calls_heuristic(monkeypatch):
    monkeypatch.setattr(settings,"llm_mode","neural")
    client = llm.LocalASLClient()
    monkeypatch.setattr(client,"load_model",lambda:False)
    def forbidden(*args):
        pytest.fail("Neural failure must never use heuristic")
    monkeypatch.setattr(client,"_heuristic_fallback",forbidden)
    with pytest.raises(llm.ModelUnavailableError):
        client.generate("prompt",{"description":"المكيف لا يعمل"})
    assert client.get_status()["mode"] == "neural_not_loaded"


def test_readiness_reports_explicit_heuristic_mode():
    with TestClient(app) as api:
        result=api.get("/ready")
    assert result.status_code == 200
    assert result.json()["model_status"]["mode"] == "fast_heuristic_mode"
    assert result.json()["model_status"]["is_neural_loaded"] is False


def test_neural_not_loaded_returns_503_and_safe_request_error(monkeypatch):
    monkeypatch.setattr(settings,"llm_mode","neural")
    monkeypatch.setattr(llm.get_llm_client(),"load_model",lambda:False)
    with TestClient(app) as api:
        ready=api.get("/ready")
        result=api.post("/api/maintenance/requests",json={"description":"المكيف لا يعمل","location":"B12"})
    assert ready.status_code == 503 and ready.json()["status"] == "not_ready"
    assert result.status_code == 503 and result.json()["status"] == "error"
    assert "ticket" not in result.json()


def test_loaded_without_generation_is_not_ready(monkeypatch):
    client=llm.get_llm_client()
    monkeypatch.setattr(settings,"llm_mode","neural")
    monkeypatch.setattr(client,"_loaded",True)
    monkeypatch.setattr(client,"initialize",lambda:False)
    with TestClient(app) as api:
        assert api.get("/ready").status_code == 503
        monkeypatch.setattr(client,"_generation_verified",True)
        assert api.get("/ready").status_code == 200


def test_malformed_extraction_is_safe_http_error_without_ticket(monkeypatch):
    monkeypatch.setattr(llm.get_llm_client(),"generate",lambda *args,**kwargs:"NOT VALID JSON")
    with TestClient(app) as api:
        response=api.post("/api/maintenance/requests",json={"description":"المكيف لا يعمل","location":"B12"})
    assert response.status_code == 502
    assert response.json()["status"] == "error"
    assert "NOT NULL" not in response.json()["message"]
    assert "ticket" not in response.json()
    import sqlite3
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0
