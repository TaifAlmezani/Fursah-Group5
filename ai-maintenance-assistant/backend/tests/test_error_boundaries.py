import logging
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app import main
from app.workflow.graph import get_workflow_graph


@pytest.mark.parametrize("operation,failure", [
    ("create", "graph"), ("create", "read_after"), ("create", "invoke"),
    ("continue", "graph"), ("continue", "read_before"),
    ("continue", "read_after"), ("continue", "invoke"),
])
def test_workflow_failures_always_return_safe_correlated_errors(monkeypatch, caplog, operation, failure):
    with TestClient(main.app) as api:
        thread_id = None
        if operation == "continue":
            initial = api.post("/api/maintenance/requests", json={"description": "الطابعة تعلق الورق", "location": "الدور الثالث"}).json()
            thread_id = initial["thread_id"]
        workflow = get_workflow_graph()

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("PRIVATE-CHECKPOINT-FAILURE")

        if failure == "graph":
            monkeypatch.setattr(main, "get_workflow_graph", fail)
        elif failure == "invoke":
            monkeypatch.setattr(workflow, "invoke", fail)
        else:
            get_state = workflow.get_state
            reads = 0

            def faulty_read(*args, **kwargs):
                nonlocal reads
                reads += 1
                if reads == (2 if operation == "continue" and failure == "read_after" else 1):
                    fail()
                return get_state(*args, **kwargs)

            monkeypatch.setattr(workflow, "get_state", faulty_read)
        with caplog.at_level(logging.ERROR):
            if operation == "continue":
                response = api.post(f"/api/maintenance/requests/{thread_id}/continue", json={"step_id": initial["step_id"], "input_type": "asset_selection", "asset_id": "PR-305-01"})
            else:
                response = api.post("/api/maintenance/requests", json={"description": "المكيف لا يعمل", "location": "B12"})
        assert response.status_code == 500
        body = response.json()
        assert body["status"] == "error" and body["error_code"] == "processing_failed"
        assert body["request_id"].startswith("REQ-")
        assert body["thread_id"].startswith("th_")
        assert body["retryable"] is False
        assert "PRIVATE-CHECKPOINT-FAILURE" not in response.text
        assert body["request_id"] in caplog.text and body["thread_id"] in caplog.text
        assert "PRIVATE-CHECKPOINT-FAILURE" in caplog.text
        if thread_id:
            assert body["thread_id"] == thread_id


def test_unknown_thread_keeps_404():
    with TestClient(main.app) as api:
        response = api.post("/api/maintenance/requests/th_missing/continue", json={"step_id": "unknown-step", "input_type": "text", "text": "B12"})
    assert response.status_code == 404


def test_checkpoint_write_retry_reuses_already_saved_ticket(monkeypatch):
    from app.workflow import nodes
    from app.db.database import insert_ticket
    with TestClient(main.app) as api:
        paused = api.post("/api/maintenance/requests", json={"description": "الطابعة تعلق الورق", "location": "الدور الثالث"}).json()
        thread_id = paused["thread_id"]

        def save_then_fail(*args, **kwargs):
            insert_ticket(*args, **kwargs)
            raise sqlite3.OperationalError("Checkpoint failed after ticket commit")

        monkeypatch.setattr(nodes, "insert_ticket", save_then_fail)
        url = f"/api/maintenance/requests/{thread_id}/continue"
        choice = {"step_id": paused["step_id"], "input_type": "asset_selection", "asset_id": "PR-305-01"}
        assert api.post(url, json=choice).status_code == 500
        monkeypatch.setattr(nodes, "insert_ticket", insert_ticket)
        # Recover the saved graph directly, as a workflow recovery task would.
        get_workflow_graph().invoke(None, {"configurable": {"thread_id": thread_id}})
        assert api.post(url, json=choice).status_code == 409
        with sqlite3.connect(settings.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (thread_id,)).fetchone()[0] == 1
