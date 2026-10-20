"""Regression cases promoted from the adversarial QA audit.

All persistence is isolated by tests/conftest.py. Controlled extraction is labelled.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.db.database import find_assets, get_ticket
from app.main import app
from app.schemas import IssueExtraction
from app.workflow import graph, nodes


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def observe(record_property, value):
    record_property("observation", json.dumps(value, ensure_ascii=False))


def start(api, description="المكيف لا يعمل", location="B12"):
    return api.post("/api/maintenance/requests", json={"description": description, "location": location})


@pytest.mark.parametrize("description", ["", " \t\n ", "المكيف " + "ع" * 4001], ids=["empty", "whitespace", "over-ui-limit"])
def test_api_rejects_empty_and_over_limit_descriptions(api, record_property, description):
    response = start(api, description=description)
    observe(record_property, {"length": len(description), "http": response.status_code, "body": response.json()})
    assert response.status_code == 422


@pytest.mark.parametrize("answer", [" \t\n ", "B12 " + "ع" * 2001], ids=["whitespace", "over-ui-limit"])
def test_api_rejects_empty_and_over_limit_clarifications(api, record_property, answer):
    first = start(api, location=None).json()
    response = api.post(f"/api/maintenance/requests/{first['thread_id']}/continue", json={"step_id": first["step_id"], "input_type": "text", "text": answer})
    observe(record_property, {"length": len(answer), "http": response.status_code, "body": response.json()})
    assert response.status_code == 422


def test_replaying_old_answer_does_not_consume_a_new_question(api, record_property):
    first = start(api, "جهاز لا يعمل", None).json()
    url = f"/api/maintenance/requests/{first['thread_id']}/continue"
    body = {"step_id": first["step_id"], "input_type": "text", "text": "المكيف"}
    second = api.post(url, json=body).json()
    assert second["status"] == "needs_information" and second["missing_fields"] == ["location"]
    assert first["question"] != second["question"]
    replay = api.post(url, json=body)
    snapshot = graph.get_workflow_graph().get_state({"configurable": {"thread_id": first["thread_id"]}})
    observe(record_property, {"first_question": first["question"], "next_question": second["question"],
                              "replay_http": replay.status_code, "saved_answers": snapshot.values["follow_up_answers"]})
    assert replay.status_code == 409
    assert len(snapshot.values["follow_up_answers"]) == 1


@pytest.mark.parametrize("change", ["UPDATE assets SET room='999' WHERE asset_id='AC-B12-02'",
                                  "UPDATE assets SET status='inactive' WHERE asset_id='AC-B12-02'",
                                  "UPDATE assets SET asset_type='printer' WHERE asset_id='AC-B12-02'",
                                  "DELETE FROM assets WHERE asset_id='AC-B12-02'"],
                         ids=["moved", "inactive", "changed-type", "deleted"])
def test_asset_is_still_valid_at_ticket_commit(api, monkeypatch, record_property, change):
    save = nodes.insert_ticket

    def changed_before_save(data, db_path):
        with sqlite3.connect(db_path) as conn:
            conn.execute(change)
        return save(data, db_path)

    monkeypatch.setattr(nodes, "insert_ticket", changed_before_save)
    response = start(api)
    result = response.json()
    with sqlite3.connect(settings.db_path) as conn:
        assets = conn.execute("SELECT asset_id,room,status FROM assets WHERE asset_id='AC-B12-02'").fetchall()
        count = conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (result["thread_id"],)).fetchone()[0]
    observe(record_property, {"change": change, "http": response.status_code, "body": result, "current_assets": assets, "tickets": count})
    assert result["status"] not in {"success", "critical"}
    assert count == 0


@pytest.mark.parametrize("location", ["غرفة 301", "غرفة ٣٠١", "غرفة ۳۰۱", "غرفة\u00a0301", "غرفة ３０１"])
def test_room_matching_is_invariant_under_supported_numerals(location):
    assert [a.asset_id for a in find_assets("printer", location, settings.db_path)] == ["PR-301-01"]


def test_twenty_competing_asset_choices_have_one_consistent_winner(api, record_property):
    first = start(api, "الطابعة تعلق الورق", "الدور الثالث").json()
    url = f"/api/maintenance/requests/{first['thread_id']}/continue"
    barrier = Barrier(20)

    def submit(i):
        selected = ["PR-301-01", "PR-305-01", "PR-310-01"][i % 3]
        barrier.wait(timeout=15)
        response = api.post(url, json={"step_id": first["step_id"], "input_type": "asset_selection", "asset_id": selected})
        return selected, response.status_code, response.json()

    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(submit, range(20)))
    observe(record_property, {"http_codes": [r[1] for r in results], "winners": [r for r in results if r[1] == 200]})
    winners = [r for r in results if r[1] == 200]
    assert len(winners) == 1 and sum(r[1] == 409 for r in results) == 19
    selected, _, response = winners[0]
    saved = get_ticket(response["ticket"]["ticket_id"], settings.db_path)
    assert saved["asset_id"] == selected == response["asset"]["asset_id"]
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tickets WHERE thread_id=?", (first["thread_id"],)).fetchone()[0] == 1


def test_twelve_independent_reports_do_not_share_state_or_tickets(api, record_property):
    barrier = Barrier(12)

    def submit(i):
        barrier.wait(timeout=15)
        response = start(api, f"المكيف لا يعمل؛ بلاغ مستقل {i}")
        return response.status_code, response.json()

    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(submit, range(12)))
    observe(record_property, {"http_codes": [r[0] for r in results], "threads": [r[1].get("thread_id") for r in results]})
    assert all(code == 200 and body["status"] == "success" for code, body in results)
    assert len({body["thread_id"] for _, body in results}) == 12
    assert len({body["ticket"]["ticket_id"] for _, body in results}) == 12


def test_explicit_heuristic_mode_detects_both_smoke_and_electrical_risk(api, record_property):
    response = start(api, "المكيف يهرب موية على اللوحة الكهربائية وفيه دخان")
    result = response.json()
    observe(record_property, result)
    assert set(result["analysis"]["safety_signals"]) == {"electrical_risk", "fire_or_smoke"}


def test_explicit_heuristic_mode_does_not_turn_negated_smoke_into_danger(api, record_property):
    result = start(api, "المكيف ما يبرد، ما فيه دخان ولا ريحة حريق ولا تسريب").json()
    observe(record_property, result)
    assert result["status"] == "success"
    assert result["analysis"]["safety_signals"] == []


def test_noncritical_flood_warning_is_present_in_real_api_output(api, monkeypatch, record_property):
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("INSERT INTO assets(asset_id,asset_type,room,status) VALUES ('PL-7','plumbing','7','active')")

    def controlled(*args, **kwargs):
        return IssueExtraction(asset_type="plumbing", location="7", symptoms=["water_leak"], safety_signals=["flooding"], missing_fields=[])

    monkeypatch.setattr(nodes, "extract_issue", controlled)
    result = start(api, "اختبار مخرجات استخراج فيضان معلنة", "7").json()
    observe(record_property, result)
    assert result["status"] == "success" and result["analysis"]["priority"] == "high"
    assert result["safety_message"]
    assert get_ticket(result["ticket"]["ticket_id"], settings.db_path)["safety_message"] == result["safety_message"]


def test_sql_metacharacters_cannot_modify_assets(api, record_property):
    result = start(api, "الطابعة تعلق الورق", "'; DROP TABLE assets; --").json()
    with sqlite3.connect(settings.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    observe(record_property, {"body": result, "asset_count": count})
    assert count == 4 and "ticket" not in result


def test_unknown_or_invalid_json_payload_is_rejected_before_workflow(api):
    for payload in [None, [], {"description": 12}, {"description": {}}, {"description": None}]:
        assert api.post("/api/maintenance/requests", json=payload).status_code == 422
