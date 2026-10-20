import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import app
from app.workflow import graph, nodes
from app.workflow.locking import continuation_lock


def create(api, description="المكيف لا يعمل", location=None):
    return api.post("/api/maintenance/requests", json={"description": description, "location": location}).json()


def test_read_only_restore_keeps_step_after_restart_and_recovers_final_result(monkeypatch):
    with TestClient(app) as api:
        paused = create(api)
        url = f"/api/maintenance/requests/{paused['thread_id']}"
        graph.get_workflow_graph().checkpointer.conn.close()
        monkeypatch.setattr(graph, "workflow_graph", graph.build_workflow_graph())
        for _ in range(2):
            restored = api.get(url).json()
            assert restored["step_id"] == paused["step_id"]
            assert restored["description"] == "المكيف لا يعمل"
            assert restored["request_id"] != paused["request_id"]
            assert restored["status"] == "needs_information"
        snapshot = graph.get_workflow_graph().get_state({"configurable": {"thread_id": paused["thread_id"]}})
        assert snapshot.values["follow_up_answers"] == []
        finished = api.post(url + "/continue", json={"input_type": "text", "text": "B12", "step_id": paused["step_id"]}).json()
        recovered = api.get(url).json()
        assert recovered["ticket"] == finished["ticket"] and recovered["asset"] == finished["asset"]
        assert "step_id" not in recovered
        with sqlite3.connect(settings.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1


def test_step_identity_changes_only_on_a_valid_consumed_answer():
    with TestClient(app) as api:
        first = create(api, "جهاز لا يعمل")
        url = f"/api/maintenance/requests/{first['thread_id']}"
        assert api.post(url + "/continue", json={"input_type": "text", "text": "المكيف"}).status_code == 422
        assert api.get(url).json()["step_id"] == first["step_id"]
        second = api.post(url + "/continue", json={"input_type": "text", "text": "المكيف", "step_id": first["step_id"]}).json()
        assert second["step_id"] != first["step_id"]
        assert api.post(url + "/continue", json={"input_type": "text", "text": "المكيف", "step_id": first["step_id"]}).status_code == 409
        assert api.get(url).json()["step_id"] == second["step_id"]
        completed = api.post(url + "/continue", json={"input_type": "text", "text": "B12", "step_id": second["step_id"]}).json()
        assert completed["status"] == "success"


def test_state_read_is_safe_when_missing_busy_or_checkpoint_fails(monkeypatch):
    with TestClient(app) as api:
        assert api.get("/api/maintenance/requests/th_missing").status_code == 404
        paused = create(api)
        url = f"/api/maintenance/requests/{paused['thread_id']}"
        with continuation_lock(paused["thread_id"], settings.checkpoints_db_path):
            assert api.get(url).status_code == 409

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("PRIVATE-RESTORE-FAILURE")

        monkeypatch.setattr(graph.get_workflow_graph(), "get_state", fail)
        response = api.get(url)
        assert response.status_code == 500
        assert response.json()["error_code"] == "processing_failed"
        assert response.json()["thread_id"] == paused["thread_id"]
        assert "PRIVATE-RESTORE-FAILURE" not in response.text


@pytest.mark.parametrize("field,value", [("room", "999"), ("floor", "9"), ("building", "B")])
def test_asset_snapshot_cannot_change_during_inference(monkeypatch, field, value):
    save = nodes.insert_ticket

    def move(data, db_path):
        with sqlite3.connect(db_path) as conn:
            # Identifiers come from a fixed parametrized test list.
            conn.execute(f"UPDATE assets SET {field}=? WHERE asset_id='AC-B12-02'", (value,))
        return save(data, db_path)

    monkeypatch.setattr(nodes, "insert_ticket", move)
    with TestClient(app) as api:
        result = create(api, location="B12")
        assert result["status"] == "error"
        with sqlite3.connect(settings.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0
