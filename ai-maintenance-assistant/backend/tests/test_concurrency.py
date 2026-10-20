from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import subprocess
import sys
from threading import Barrier, Event

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.db.database import init_db, insert_ticket
from app.main import app
from app.workflow import graph
from app.workflow.locking import continuation_lock, ContinuationInProgressError


CHOICE = {"input_type": "asset_selection", "asset_id": "PR-305-01"}


def start_selection(api):
    response = api.post("/api/maintenance/requests", json={
        "description": "الطابعة تعلق الورق", "location": "الدور الثالث"})
    assert response.json()["status"] == "needs_asset_selection"
    return response.json()


def count_tickets(thread_id):
    with sqlite3.connect(settings.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (thread_id,)).fetchone()[0]


@pytest.mark.parametrize("rebuild", [False, True])
def test_simultaneous_continuations_create_one_ticket_and_reject_replay(monkeypatch, rebuild):
    with TestClient(app) as api:
        initial = start_selection(api)
        thread_id = initial["thread_id"]
        choice = {**CHOICE, "step_id": initial["step_id"]}
        if rebuild:
            graph.get_workflow_graph().checkpointer.conn.close()
            monkeypatch.setattr(graph, "workflow_graph", graph.build_workflow_graph())
        workflow = graph.get_workflow_graph()
        invoke = workflow.invoke
        entered, release = Event(), Event()

        def held_invoke(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return invoke(*args, **kwargs)

        monkeypatch.setattr(workflow, "invoke", held_invoke)
        url = f"/api/maintenance/requests/{thread_id}/continue"
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(api.post, url, json=choice)
            try:
                assert entered.wait(10)
                second = pool.submit(api.post, url, json=choice).result(timeout=10)
                assert second.status_code == 409
                assert "حاليًا" in second.json()["detail"]
            finally:
                release.set()
            completed = first.result(timeout=10)
        assert completed.status_code == 200
        assert completed.json()["status"] == "success"
        assert count_tickets(thread_id) == 1
        # Reopen the actual on-disk checkpointer, rather than relying on memory.
        workflow.checkpointer.conn.close()
        monkeypatch.setattr(graph, "workflow_graph", graph.build_workflow_graph())
        assert api.post(url, json=choice).status_code == 409
        assert count_tickets(thread_id) == 1
        new_thread = start_selection(api)
        assert api.post(f"/api/maintenance/requests/{new_thread['thread_id']}/continue", json={**CHOICE, "step_id": new_thread["step_id"]}).status_code == 200
        assert count_tickets(new_thread["thread_id"]) == 1


def test_independent_conversations_can_resume_concurrently(monkeypatch):
    with TestClient(app) as api:
        threads = [start_selection(api), start_selection(api)]
        workflow = graph.get_workflow_graph()
        invoke = workflow.invoke
        rendezvous = Barrier(2)

        def concurrent_invoke(*args, **kwargs):
            rendezvous.wait(timeout=10)
            return invoke(*args, **kwargs)

        monkeypatch.setattr(workflow, "invoke", concurrent_invoke)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(api.post, f"/api/maintenance/requests/{t['thread_id']}/continue", json={**CHOICE, "step_id": t["step_id"]}) for t in threads]
            assert [future.result(timeout=15).status_code for future in futures] == [200, 200]
        assert [count_tickets(t["thread_id"]) for t in threads] == [1, 1]


def test_another_process_cannot_resume_locked_conversation_and_crash_releases_lock():
    with TestClient(app) as api:
        initial = start_selection(api)
        thread_id = initial["thread_id"]
        choice = {**CHOICE, "step_id": initial["step_id"]}
        script = """
import sys
from app.workflow.locking import continuation_lock
with continuation_lock(sys.argv[1], sys.argv[2]):
    print('locked', flush=True)
    sys.stdin.readline()
"""
        worker = subprocess.Popen([sys.executable, "-c", script, thread_id, settings.checkpoints_db_path],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert worker.stdout.readline().strip() == "locked"
            with pytest.raises(ContinuationInProgressError):
                with continuation_lock(thread_id, settings.checkpoints_db_path):
                    pytest.fail("Acquired a lock held by another process")
            url = f"/api/maintenance/requests/{thread_id}/continue"
            assert api.post(url, json=choice).status_code == 409
            assert count_tickets(thread_id) == 0
            worker.kill()
            worker.wait(timeout=10)
            assert api.post(url, json=choice).status_code == 200
            assert count_tickets(thread_id) == 1
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)


def test_ticket_idempotency_across_processes_restart_and_new_report():
    data = {"thread_id": "th_shared", "ticket_status": "created",
            "selected_asset_id": "PR-305-01", "asset_type": "printer"}
    script = """
import json, sys
from app.db.database import insert_ticket
sys.stdin.readline()
print(insert_ticket(json.loads(sys.argv[1]), sys.argv[2]), flush=True)
"""
    workers = [subprocess.Popen([sys.executable, "-c", script, json.dumps(data), settings.db_path],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
               for _ in range(4)]
    try:
        for worker in workers:
            worker.stdin.write("go\n")
            worker.stdin.flush()
        results = [worker.communicate(timeout=15) for worker in workers]
        assert all(worker.returncode == 0 for worker in workers), results
        assert len({out.strip() for out, _ in results}) == 1
        assert count_tickets("th_shared") == 1
        init_db(settings.db_path)
        assert insert_ticket(data, settings.db_path) == results[0][0].strip()
        assert insert_ticket({**data, "thread_id": "th_independent"}, settings.db_path) != results[0][0].strip()
        with sqlite3.connect(settings.db_path) as conn:
            # A caller bypassing insert_ticket must still satisfy the UNIQUE index.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO tickets SELECT 'TICK-DUP',thread_id,asset_id,asset_type,category,location,symptoms,safety_signals,priority,safety_message,recommended_action,status,created_at,recommendation_status,recommendation_evidence,operation_key FROM tickets WHERE operation_key='th_shared'")
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=10)


def test_migration_preserves_historical_duplicates_and_reserves_the_operation(tmp_path):
    legacy = str(tmp_path / "legacy.db")
    init_db(legacy, settings.seed_path)
    data = {"thread_id": "th_old", "ticket_status": "created",
            "selected_asset_id": "PR-305-01", "asset_type": "printer"}
    original = insert_ticket(data, legacy)
    with sqlite3.connect(legacy) as conn:
        conn.execute("DROP INDEX tickets_operation_key")
        conn.execute("ALTER TABLE tickets DROP COLUMN operation_key")
        conn.execute("INSERT INTO tickets SELECT 'TICK-OLD-DUP',thread_id,asset_id,asset_type,category,location,symptoms,safety_signals,priority,safety_message,recommended_action,status,created_at,recommendation_status,recommendation_evidence FROM tickets")
    init_db(legacy)
    init_db(legacy)
    assert insert_ticket(data, legacy) in {original, "TICK-OLD-DUP"}
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM tickets WHERE operation_key='th_old'").fetchone()[0] == 1
