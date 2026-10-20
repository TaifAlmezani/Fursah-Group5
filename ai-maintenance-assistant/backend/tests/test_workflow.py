import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.workflow import nodes
from app.workflow.graph import build_workflow_graph, get_workflow_graph
from app.db.database import get_db_connection


def test_trace_measures_work_and_preserves_previous_steps(monkeypatch):
    clock = iter([10.0, 10.247])
    monkeypatch.setattr(nodes.time, 'perf_counter', lambda: next(clock))
    previous = {'step':'previous', 'duration_ms':42.0}
    result = nodes.check_completeness_node({'missing_fields':[], 'trace':[previous]})
    assert result['trace'][0] == previous
    assert result['trace'][1]['duration_ms'] == 247.0


def test_resume_excludes_waiting_time_and_retains_saved_trace():
    with TestClient(app) as api:
        first = api.post('/api/maintenance/requests', json={'description':'المكيف لا يعمل'}).json()
        last = api.post(f"/api/maintenance/requests/{first['thread_id']}/continue",
                        json={"step_id": first["step_id"], 'input_type':'text', 'text':'B12'}).json()
    assert last['trace'][:len(first['trace'])] == first['trace']
    assert any(step['step']=='استلام التوضيح' for step in last['trace'])
    assert all(isinstance(step['duration_ms'], (int,float)) and step['duration_ms'] >= 0 for step in last['trace'])
    assert not all(step['duration_ms']==15.0 for step in last['trace'])


@pytest.mark.parametrize('change', ["UPDATE assets SET status='inactive' WHERE asset_id='PR-305-01'",
                                  "UPDATE assets SET room='999',floor='9' WHERE asset_id='PR-305-01'",
                                  "DELETE FROM assets WHERE asset_id='PR-305-01'"])
def test_selection_rechecks_asset_after_wait(change):
    with TestClient(app) as api:
        first = api.post('/api/maintenance/requests',json={'description':'الطابعة تعلق الورق','location':'الدور الثالث'}).json()
        with get_db_connection(settings.db_path) as connection:
            connection.execute(change)
        response = api.post(f"/api/maintenance/requests/{first['thread_id']}/continue",
                            json={"step_id": first["step_id"], 'input_type':'asset_selection','asset_id':'PR-305-01'})
        assert response.status_code == 200 and response.json()['status']=='asset_not_found'
        with get_db_connection(settings.db_path) as connection:
            assert connection.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0


def test_interrupted_workflow_survives_rebuilt_graph(monkeypatch):
    from app.workflow import graph
    with TestClient(app) as api:
        first = api.post('/api/maintenance/requests',json={'description':'الطابعة تعلق الورق','location':'الدور الثالث'}).json()
        get_workflow_graph().checkpointer.conn.close()
        monkeypatch.setattr(graph,'workflow_graph',build_workflow_graph())
        last = api.post(f"/api/maintenance/requests/{first['thread_id']}/continue",
                        json={"step_id": first["step_id"], 'input_type':'asset_selection','asset_id':'PR-310-01'}).json()
        assert last['asset']['asset_id']=='PR-310-01'
        with get_db_connection(settings.db_path) as connection:
            row = connection.execute('SELECT thread_id,asset_id,status FROM tickets').fetchone()
            assert tuple(row)==(first['thread_id'],'PR-310-01','created')


def test_missing_symptoms_gets_relevant_question():
    result = nodes.check_completeness_node({'missing_fields':['symptoms'],'trace':[]})
    assert 'العطل' in result['question'] and 'الغرفة' not in result['question']


def test_safe_error_code_distinguishes_missing_rag(monkeypatch):
    from app.rag.engine import RAGUnavailableError
    def fail(**kwargs):
        raise RAGUnavailableError('index_missing')
    monkeypatch.setattr(nodes, 'retrieve_procedures', fail)
    with TestClient(app) as api:
        response = api.post('/api/maintenance/requests', json={'description':'المكيف يهرب موية','location':'B12'})
    assert response.status_code == 503
    assert response.json()['error_code']=='rag_unavailable'
    assert 'index_missing' not in response.json()['message']
