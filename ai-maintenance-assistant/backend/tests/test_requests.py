import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app, _format_frontend_response
from app.db.database import find_assets, get_ticket
from app.workflow.graph import get_workflow_graph
from app.workflow import nodes


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def create(api, description="المكيف لا يعمل", location="B12"):
    return api.post("/api/maintenance/requests", json={"description": description, "location": location}).json()


def ticket_count(thread):
    with sqlite3.connect(settings.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (thread,)).fetchone()[0]


@pytest.mark.parametrize("location", ["غرفة 999", "مكتب 204"])
def test_unknown_location_never_tickets(api, location):
    result = create(api, location=location)
    assert result["status"] == "asset_not_found"
    assert "ticket" not in result
    assert ticket_count(result["thread_id"]) == 0


def test_room_is_exact_and_arabic_digits_supported():
    assert find_assets("printer", "غرفة 30", settings.db_path) == []
    assert [a.asset_id for a in find_assets("printer", "غرفة ٣٠١", settings.db_path)] == ["PR-301-01"]


@pytest.mark.parametrize("location,expected", [("الدور الثالث", ["PR-301-01", "PR-305-01", "PR-310-01"]), ("301 و305", ["PR-301-01", "PR-305-01"])])
def test_selection_candidates_reach_api(api, location, expected):
    result = create(api, "الطابعة تعلق الورق", location)
    assert result["status"] == "needs_asset_selection"
    assert [a["asset_id"] for a in result["assets"]] == expected
    assert ticket_count(result["thread_id"]) == 0


def test_building_disambiguation_and_explicit_filters(api):
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("INSERT INTO assets SELECT 'PR-B-301',asset_type,asset_name_ar,'B',floor,room,model,status FROM assets WHERE asset_id='PR-301-01'")
    result = create(api, "الطابعة لا تعمل", "غرفة 301")
    assert result["status"] == "needs_information"
    assert "المبنى" in result["question"]
    clarified = api.post(f"/api/maintenance/requests/{result['thread_id']}/continue", json={"step_id": result["step_id"], "input_type":"text", "text":"غرفة 301 مبنى B"}).json()
    assert clarified["asset"]["asset_id"] == "PR-B-301"
    exact = create(api, "الطابعة لا تعمل", "غرفة 301 مبنى B الدور الثالث")
    assert exact["asset"]["asset_id"] == "PR-B-301"
    assert find_assets("printer", "غرفة 301 الدور الثاني", settings.db_path) == []


def test_ambiguous_location_requires_clarification(api):
    result = create(api, location="جنب الباب")
    assert result["status"] == "needs_information"
    assert "location" in result["missing_fields"]
    assert ticket_count(result["thread_id"]) == 0


def test_clarification_uses_new_location(api):
    result = create(api, location=None)
    continued = api.post(f"/api/maintenance/requests/{result['thread_id']}/continue", json={"step_id": result["step_id"], "input_type":"text", "text":"مكتب 204"}).json()
    assert continued["status"] == "asset_not_found"
    assert ticket_count(result["thread_id"]) == 0


@pytest.mark.parametrize("invalid", ["DOES-NOT-EXIST", "AC-B12-02", ""])
def test_invalid_choice_preserves_waiting_and_can_recover(api, invalid):
    result = create(api, "الطابعة لا تعمل", "301 و305")
    url = f"/api/maintenance/requests/{result['thread_id']}/continue"
    bad = api.post(url, json={"step_id": result["step_id"], "input_type":"asset_selection", "asset_id":invalid})
    assert bad.status_code == 422
    snapshot = get_workflow_graph().get_state({"configurable":{"thread_id":result["thread_id"]}})
    assert snapshot.tasks[0].interrupts
    assert ticket_count(result["thread_id"]) == 0
    good = api.post(url, json={"step_id": result["step_id"], "input_type":"asset_selection", "asset_id":"PR-305-01"}).json()
    assert good["asset"]["asset_id"] == "PR-305-01"
    assert get_ticket(good["ticket"]["ticket_id"],settings.db_path)["asset_id"] == "PR-305-01"
    assert api.post(url, json={"step_id": result["step_id"], "input_type":"asset_selection", "asset_id":"PR-305-01"}).status_code == 409


def test_wrong_continuation_type_does_not_resume(api):
    result = create(api, "الطابعة لا تعمل", "301 و305")
    assert api.post(f"/api/maintenance/requests/{result['thread_id']}/continue",json={"step_id": result["step_id"], "input_type":"text","text":"301"}).status_code == 409
    assert ticket_count(result["thread_id"]) == 0


@pytest.mark.parametrize("description", ["السخان ما يشتغل", "المغسلة فيها تسريب موية"])
def test_unregistered_type_stops_without_generic_asset(api, description):
    result = create(api, description, "المستودع 7")
    assert result["status"] == "asset_not_found"
    assert "asset" not in result and "ticket" not in result
    assert ticket_count(result["thread_id"]) == 0


@pytest.mark.parametrize("description,expected", [("المكيف لا يعمل", "created"),("المكيف يهرب موية على اللوحة الكهربائية", "escalated")])
def test_saved_ticket_matches_response(api, description, expected):
    result = create(api,description)
    saved = get_ticket(result["ticket"]["ticket_id"], settings.db_path)
    assert saved["status"] == result["ticket"]["status"] == expected
    assert saved["thread_id"] == result["thread_id"]


@pytest.mark.parametrize("description,signal", [("المكيف يهرب موية على اللوحة الكهربائية", "electrical_risk"),("المكيف فيه دخان", "fire_or_smoke")])
def test_hazard_warning_precedes_clarification(api, description, signal):
    result = create(api,description,None)
    assert result["status"] == "needs_information" and result["safety_message"]
    snapshot = get_workflow_graph().get_state({"configurable":{"thread_id":result["thread_id"]}})
    assert signal in snapshot.values["safety_signals"]
    assert ticket_count(result["thread_id"]) == 0


def test_warning_survives_selection_and_no_match(api):
    result = create(api,"الطابعة لا تعمل وفيها دخان","الدور الثالث")
    assert result["status"] == "needs_asset_selection" and result["safety_message"]
    missing = create(api,"المكيف يهرب موية على اللوحة الكهربائية","999")
    assert missing["status"] == "asset_not_found" and missing["safety_message"]


def test_metadata_and_out_of_service(api):
    result = create(api)
    assert result["asset"]["model"] == "Demo-AC-01"
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE assets SET status='inactive' WHERE asset_id='AC-B12-02'")
    stopped = create(api)
    assert stopped["status"] == "asset_not_found" and "خارج الخدمة" in stopped["message"]
    assert ticket_count(stopped["thread_id"]) == 0


@pytest.mark.parametrize("state", [{},{"status":"processing"},{"status":"success"},{"status":"success","ticket_id":"TICK-MISSING","selected_asset":{"asset_id":"AC-B12-02"}}])
def test_formatter_never_invents_success(state):
    result = _format_frontend_response(state,"REQ-test","th_test")
    assert result["status"] == "error" and "ticket" not in result and "asset" not in result


def test_save_failure_never_reports_success(api, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("TEST-SAVE-FAILURE")
    monkeypatch.setattr(nodes,"insert_ticket",fail)
    result = create(api)
    assert result["status"] == "error" and "ticket" not in result
    assert ticket_count(result["thread_id"]) == 0


def test_out_of_service_candidate_stops_without_ticket(api):
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE assets SET status='inactive' WHERE asset_id='PR-305-01'")
    result = create(api, "الطابعة لا تعمل", "الدور الثالث")
    response = api.post(f"/api/maintenance/requests/{result['thread_id']}/continue", json={"step_id": result["step_id"], "input_type":"asset_selection", "asset_id":"PR-305-01"}).json()
    assert response["status"] == "asset_not_found" and "خارج الخدمة" in response["message"]
    assert ticket_count(result["thread_id"]) == 0


def test_no_warning_for_nonhazard_and_null_metadata(api):
    paused = create(api, location=None)
    assert not paused.get("safety_message")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE assets SET model=NULL WHERE asset_id='AC-B12-02'")
    result = create(api)
    assert result["asset"]["model"] is None


def test_warning_survives_location_clarification(api):
    result = create(api, "المكيف يهرب موية على اللوحة الكهربائية", None)
    finished = api.post(f"/api/maintenance/requests/{result['thread_id']}/continue", json={"step_id": result["step_id"], "input_type":"text", "text":"B12"}).json()
    assert finished["status"] == "critical" and finished["safety_message"]
    assert get_ticket(finished["ticket"]["ticket_id"], settings.db_path)["status"] == "escalated"
