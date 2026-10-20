import json
from pathlib import Path
import sqlite3
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
from app.rag import engine as rag
from app.llm import agents
from app.llm.client import StructuredOutputError
from app.db.database import get_ticket, init_db, insert_ticket, get_db_connection


def test_chunks_have_substantive_content_and_known_sources():
    docs = rag.load_and_split_documents(settings.knowledge_path)
    assert len(docs) == 6
    assert all("\n- " in d["content"] and d["metadata"]["source_sha256"] for d in docs)


def test_irrelevant_symptoms_and_devices_are_excluded():
    leak = rag.retrieve_procedures("air_conditioner", ["water_leak"])
    assert {c.section for c in leak} == {"تسرب المياه"}
    assert all(c.source == "air_conditioning.md" for c in leak)
    assert rag.retrieve_procedures("air_conditioner", ["not_working"]) == []
    assert rag.retrieve_procedures("heater", ["water_leak"]) == []


def test_safety_retrieval_never_returns_normal_repair_instructions():
    chunks = rag.retrieve_procedures("air_conditioner", ["water_leak"], ["electrical_risk"])
    assert [c.source for c in chunks] == ["electrical.md"]
    assert rag.retrieve_procedures("printer", ["paper_jam"], ["fire_or_smoke"]) == []


def test_threshold_and_limits_are_effective():
    assert rag.retrieve_procedures("printer", ["paper_jam", "not_working"], top_k=1)
    assert len(rag.retrieve_procedures("printer", ["paper_jam", "not_working"], top_k=1)) == 1
    assert rag.retrieve_procedures("printer", ["paper_jam"], top_k=0) == []
    assert rag.retrieve_procedures("air_conditioner", ["water_leak"], ["electrical_risk"], min_score=.99999) == []


def test_source_changes_mark_index_stale_and_readiness_503(tmp_path, monkeypatch):
    knowledge = tmp_path / "knowledge"
    shutil.copytree(settings.knowledge_path, knowledge)
    monkeypatch.setattr(settings,"knowledge_path",str(knowledge))
    rag.build_rag_index()
    with TestClient(app) as api:
        assert api.get("/ready").status_code == 200
        with (knowledge / "air_conditioning.md").open("a",encoding="utf-8") as file:
            file.write("\nتغيير المرجع\n")
        assert api.get("/ready").status_code == 503
        result = api.post("/api/maintenance/requests",json={"description":"المكيف يهرب موية","location":"B12"})
        assert result.status_code == 503 and "ticket" not in result.json()
    assert rag.get_rag_status()["status"] == "index_stale"


def test_corrupt_index_is_not_used():
    pointer = json.loads((Path(settings.vectorstore_path) / "current.json").read_text())
    path = Path(settings.vectorstore_path) / "generations" / pointer["generation"] / "index.faiss"
    path.write_bytes(b"corrupt")
    with pytest.raises(rag.RAGUnavailableError):
        rag.retrieve_procedures("printer",["paper_jam"])


def test_failed_rebuild_keeps_previous_index(monkeypatch):
    path = Path(settings.vectorstore_path) / "current.json"
    previous = path.read_bytes()
    monkeypatch.setattr(rag,"_encode",lambda texts: (_ for _ in ()).throw(RuntimeError("embedding failure")))
    with pytest.raises(RuntimeError):
        rag.build_rag_index()
    assert path.read_bytes() == previous


def test_unavailable_index_never_claims_ready(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"vectorstore_path",str(tmp_path / "missing"))
    with TestClient(app) as api:
        assert api.get("/ready").status_code == 503


def test_no_evidence_skips_llm_and_reports_manual_review(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail("No evidence must not trigger model repair generation")
    monkeypatch.setattr(agents,"run_structured_model",forbidden)
    result = agents.compose_recommendation([],{"asset_type":"air_conditioner","symptoms":["not_working"]})
    assert result.recommendation_status == "manual_review" and result.evidence == []


@pytest.mark.parametrize("ids", [["UNKNOWN"],["P1","P1"],["P1"]])
def test_bad_or_incomplete_selection_is_rejected(monkeypatch,ids):
    chunks = rag.retrieve_procedures("printer",["paper_jam","not_working"])
    monkeypatch.setattr(agents,"run_structured_model",lambda *args,**kwargs:SimpleNamespace(procedure_ids=ids))
    with pytest.raises(StructuredOutputError):
        agents.compose_recommendation(chunks,{"symptoms":["paper_jam","not_working"]})


def test_recommendation_is_exact_evidence_and_persisted():
    with TestClient(app) as api:
        response=api.post("/api/maintenance/requests",json={"description":"المكيف يهرب موية","location":"B12"}).json()
    assert response["status"] == "success" and response["recommendation_status"] == "grounded"
    saved=get_ticket(response["ticket"]["ticket_id"],settings.db_path)
    evidence=json.loads(saved["recommendation_evidence"])
    assert len(evidence)==1 and evidence[0]["source"]=="air_conditioning.md"
    assert saved["recommended_action"] == evidence[0]["content"].removeprefix("## ").strip()
    assert response["evidence"][0]["source_sha256"] == evidence[0]["source_sha256"]


def test_no_sop_still_creates_real_manual_review_ticket():
    with TestClient(app) as api:
        response=api.post("/api/maintenance/requests",json={"description":"المكيف لا يعمل","location":"B12"}).json()
    assert response["status"] == "success" and response["recommendation_status"] == "manual_review"
    assert response["evidence"] == []
    assert get_ticket(response["ticket"]["ticket_id"],settings.db_path)["recommendation_status"] == "manual_review"


def test_existing_ticket_migration_preserves_old_data(tmp_path):
    db=tmp_path / "legacy.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, thread_id TEXT, asset_id TEXT, asset_type TEXT, category TEXT, location TEXT, symptoms TEXT, safety_signals TEXT, priority TEXT, safety_message TEXT, recommended_action TEXT, status TEXT, created_at TEXT)")
        c.execute("INSERT INTO tickets(ticket_id,status,recommended_action) VALUES ('OLD','processing','old text')")
    init_db(str(db))
    saved=get_ticket("OLD",str(db))
    assert saved["status"] == "processing" and saved["recommended_action"] == "old text"
    assert saved["recommendation_status"] == "legacy" and saved["recommendation_evidence"] == "[]"


def test_ticket_cannot_claim_grounding_without_evidence():
    with pytest.raises(ValueError, match="requires source evidence"):
        insert_ticket({"ticket_status":"created", "selected_asset_id":"AC-B12-02",
            "asset_type":"air_conditioner", "recommendation_status":"grounded", "recommendation_evidence":[]},settings.db_path)


def test_database_connection_closes_and_releases_windows_file(tmp_path):
    db = tmp_path / "connection.db"
    with get_db_connection(str(db)) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    db.unlink()
