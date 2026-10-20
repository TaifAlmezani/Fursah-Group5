"""Controlled extraction tests: verify policy/workflow, not neural hazard recall."""
from itertools import permutations
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.db.database import get_ticket
from app.main import app
from app.policies.rules import SAFETY_MESSAGES
from app.schemas import IssueExtraction
from app.workflow import graph, nodes


ORDER = ("fire_or_smoke", "electrical_risk", "exposed_wires", "flooding")


@pytest.mark.parametrize("initial,additional", list(permutations(ORDER, 2)))
def test_new_hazard_on_continuation_is_accumulated_ordered_and_persisted(monkeypatch, initial, additional):
    def extracted(description, location=None, follow_up_answers=()):
        resumed = bool(follow_up_answers)
        return IssueExtraction(asset_type="air_conditioner", location="B12" if resumed else None,
                               symptoms=["not_working"], safety_signals=[additional, additional] if resumed else [initial],
                               missing_fields=[] if resumed else ["location"])

    monkeypatch.setattr(nodes, "extract_issue", extracted)
    with TestClient(app) as api:
        first = api.post("/api/maintenance/requests", json={"description": "بلاغ مخاطر متعدد لاختبار السياسة"}).json()
        assert first["status"] == "needs_information"
        assert first["safety_message"] == SAFETY_MESSAGES[initial]
        thread_id = first["thread_id"]
        # Prove accumulation survives opening the checkpoint again, too.
        graph.get_workflow_graph().checkpointer.conn.close()
        monkeypatch.setattr(graph, "workflow_graph", graph.build_workflow_graph())
        last = api.post(f"/api/maintenance/requests/{thread_id}/continue",
                        json={"step_id": first["step_id"], "input_type": "text", "text": "B12؛ ظهر خطر إضافي"}).json()
        expected = " ".join(SAFETY_MESSAGES[s] for s in ORDER if s in {initial, additional})
        assert last["status"] == "critical"
        assert last["analysis"]["priority"] == "critical"
        assert set(last["analysis"]["safety_signals"]) == {initial, additional}
        assert last["safety_message"] == expected
        assert last["thread_id"] == thread_id and last["request_id"] != first["request_id"]
        saved = get_ticket(last["ticket"]["ticket_id"], settings.db_path)
        assert saved["safety_message"] == expected
        assert set(json.loads(saved["safety_signals"])) == {initial, additional}
        assert saved["status"] == last["ticket"]["status"] == "escalated"
        with sqlite3.connect(settings.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (thread_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("location,expected_status", [(None, "needs_information"), ("الدور الثالث", "needs_asset_selection"), ("999", "asset_not_found")])
def test_all_warnings_are_present_before_asset_resolution(monkeypatch, location, expected_status):
    def extracted(*args, **kwargs):
        return IssueExtraction(asset_type="printer", location=location, symptoms=["paper_jam"],
                               safety_signals=list(reversed(ORDER)), missing_fields=[] if location else ["location"])

    monkeypatch.setattr(nodes, "extract_issue", extracted)
    with TestClient(app) as api:
        result = api.post("/api/maintenance/requests", json={"description": "اختبار تحذيرات قبل مطابقة الجهاز", "location": location}).json()
        expected = " ".join(SAFETY_MESSAGES[s] for s in ORDER)
        assert result["status"] == expected_status
        assert result["safety_message"] == expected
        if expected_status == "needs_asset_selection":
            completed = api.post(f"/api/maintenance/requests/{result['thread_id']}/continue",
                                 json={"step_id": result["step_id"], "input_type": "asset_selection", "asset_id": "PR-305-01"}).json()
            assert completed["status"] == "critical" and completed["safety_message"] == expected
            assert get_ticket(completed["ticket"]["ticket_id"], settings.db_path)["safety_message"] == expected
        else:
            with sqlite3.connect(settings.db_path) as conn:
                assert conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (result["thread_id"],)).fetchone()[0] == 0
