import time
from functools import wraps
from typing import Any
from langgraph.types import interrupt

from app.config import settings
from app.db.database import find_assets, insert_ticket, location_filters
from app.llm.agents import compose_recommendation, extract_issue
from app.policies.rules import category_for_asset_type, determine_priority, evaluate_safety
from app.rag.engine import retrieve_procedures
from app.workflow.state import MaintenanceState


def _add_trace(state: MaintenanceState, step: str, details: str | None = None, status: str = "completed") -> list[dict[str, Any]]:
    """Helper to append a structured trace step."""
    traces = list(state.get("trace", []))
    traces.append({
        "step": step,
        "status": status,
        "details": details,
        "duration_ms": None
    })
    return traces


def measured_node(function):
    """Measure node work only; interrupted time waiting for a user is excluded."""
    @wraps(function)
    def measured(state):
        started = time.perf_counter()
        result = function(state)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        if "trace" in result:
            previous_count = len(state.get("trace", []))
            result["trace"] = [
                {**item, "duration_ms": elapsed_ms} if index >= previous_count else item
                for index, item in enumerate(result["trace"])
            ]
        return result
    return measured


@measured_node
def extract_issue_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 1: Extract structured facts from user report."""
    issue = extract_issue(
        description=state.get("description", ""),
        location=state.get("location"),
        follow_up_answers=state.get("follow_up_answers", []),
    )
    
    loc = issue.location or state.get("location")
    missing = list(issue.missing_fields)
    for field, value in [("asset_type", issue.asset_type), ("location", loc), ("symptoms", issue.symptoms)]:
        if not value and field not in missing:
            missing.append(field)
    if loc and not any(location_filters(loc)) and "location" not in missing:
        missing.append("location")
    traces = _add_trace(
        state, 
        "استخراج بيانات البلاغ", 
        f"الجهاز: {issue.asset_type or 'غير محدد'} | الموقع: {loc or 'غير محدد'}"
    )

    return {
        "asset_type": issue.asset_type,
        "category": category_for_asset_type(issue.asset_type),
        "location": loc,
        "symptoms": issue.symptoms,
        "safety_signals": list(dict.fromkeys(state.get("safety_signals", []) + issue.safety_signals)),
        "missing_fields": missing,
        "trace": traces,
        "status": "processing",
        "error": None,
    }


@measured_node
def check_completeness_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 2: Verify all required information exists, pause if missing."""
    missing = state.get("missing_fields", [])
    if missing:
        question = "يرجى تحديد الموقع أو الغرفة لإكمال البلاغ."
        if "asset_type" in missing:
            question = "ما هو نوع الجهاز المتعطل؟ (مثال: مكيف، طابعة، سباكة، كهرباء)"
        elif "location" not in missing and "symptoms" in missing:
            question = "وش المشكلة اللي صارت بالجهاز؟ صف العطل اللي لاحظته."

        traces = _add_trace(state, "التحقق من اكتمال البيانات", f"بيانات ناقصة: {', '.join(missing)}")
        return {
            "status": "needs_information",
            "missing_fields": missing,
            "question": question,
            "trace": traces,
        }

    traces = _add_trace(state, "التحقق من اكتمال البيانات", "جميع البيانات الأساسية مكتملة")
    return {"status": "processing", "trace": traces}


@measured_node
def request_clarification_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 2b: Human-in-the-loop interrupt for missing info."""
    user_response = interrupt({
        "status": "needs_information",
        "missing_fields": state.get("missing_fields", []),
        "question": state.get("question", "يرجى توضيح تفاصيل البلاغ"),
        "safety_message": state.get("safety_message"),
        "trace": state.get("trace", []),
    })
    
    answers = list(state.get("follow_up_answers", []))
    if isinstance(user_response, dict):
        answers.append(user_response)
    elif isinstance(user_response, str):
        answers.append({"field": "general", "answer": user_response})
        
    updates = {"follow_up_answers": answers, "missing_fields": [],
               "trace": _add_trace(state, "استلام التوضيح", "تم استلام إجابة المتابعة")}
    if "location" in state.get("missing_fields", []):
        updates["location"] = answers[-1].get("answer")
    return updates


@measured_node
def lookup_asset_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 3: Check matching physical asset in SQLite."""
    asset_type = state.get("asset_type")
    location = state.get("location") or ""

    assets = find_assets(asset_type=asset_type or "other", location=location, db_path=settings.db_path)
    
    if len(assets) == 1:
        asset = assets[0]
        if asset.status != "active":
            message = (
                "الجهاز مسجل لكنه خارج الخدمة. يرجى التواصل مع قسم الصيانة."
                if asset.status == "inactive"
                else "حالة الجهاز غير متوفرة. يرجى التواصل مع قسم الصيانة."
            )
            return {
                "status": "asset_not_found", "message": message,
                "selected_asset": None, "selected_asset_id": None,
                "candidate_assets": [],
                "trace": _add_trace(state, "مطابقة الأصل", "الجهاز ليس بالخدمة"),
            }
        traces = _add_trace(state, "مطابقة الأصل", f"تم العثور على الأصل: {asset.asset_id}")
        return {
            "selected_asset": asset.model_dump(),
            "selected_asset_id": asset.asset_id,
            "candidate_assets": [],
            "trace": traces,
        }
    elif len(assets) > 1:
        rooms, _, building = location_filters(location)
        if len(rooms) == 1 and building is None and len({a.building for a in assets}) > 1:
            return {
                "status": "needs_information", "missing_fields": ["location"],
                "question": "رقم الغرفة موجود في أكثر من مبنى. اكتب رقم الغرفة واسم المبنى معاً.",
                "trace": _add_trace(state, "مطابقة الأصل", "يلزم تحديد المبنى"),
            }
        traces = _add_trace(state, "مطابقة الأصل", f"تم العثور على {len(assets)} أجهزة مطابقة")
        return {
            "status": "needs_asset_selection",
            "message": "تم العثور على أكثر من جهاز في هذا الموقع، يرجى اختيار الجهاز المتعطل.",
            "candidate_assets": [a.model_dump() for a in assets],
            "trace": traces,
        }
    
    return {
        "status": "asset_not_found",
        "message": "الجهاز غير مسجل في هالموقع. يرجى التواصل مع قسم الصيانة.",
        "selected_asset": None,
        "selected_asset_id": None,
        "candidate_assets": [],
        "trace": _add_trace(state, "مطابقة الأصل", "لا يوجد جهاز مسجل مطابق للموقع"),
    }


@measured_node
def request_asset_selection_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 3b: Human-in-the-loop interrupt for picking an asset among candidates."""
    selected_payload = interrupt({
        "status": "needs_asset_selection",
        "message": state.get("message", "يرجى اختيار الجهاز"),
        "candidate_assets": state.get("candidate_assets", []),
        "safety_message": state.get("safety_message"),
        "trace": state.get("trace", []),
    })
    
    asset_id = ""
    if isinstance(selected_payload, dict):
        asset_id = selected_payload.get("asset_id") or selected_payload.get("selected_asset_id", "")
    elif isinstance(selected_payload, str):
        asset_id = selected_payload

    # Find the chosen asset dict
    chosen = None
    for a in state.get("candidate_assets", []):
        if a.get("asset_id") == asset_id:
            chosen = a
            break
    if not chosen:
        raise ValueError("Selected asset is not among the candidates")
    current = find_assets(state.get("asset_type") or "other", state.get("location") or "", settings.db_path)
    chosen = next((asset.model_dump() for asset in current if asset.asset_id == asset_id), None)
    if not chosen or chosen.get("status") != "active":
        return {"status": "asset_not_found", "message": "الجهاز خارج الخدمة أو لم يعد مسجلًا في هالموقع. يرجى التواصل مع قسم الصيانة.", "selected_asset": None, "selected_asset_id": None,
                "trace": _add_trace(state, "تأكيد اختيار الجهاز", "الجهاز غير متاح بالخدمة")}

    return {
        "selected_asset": chosen,
        "selected_asset_id": chosen.get("asset_id") if chosen else asset_id,
        "status": "processing",
        "trace": _add_trace(state, "تأكيد اختيار الجهاز", f"تم اختيار الجهاز: {asset_id}"),
    }


@measured_node
def retrieve_sop_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 4: Retrieve verified SOP procedures using RAG."""
    chunks = retrieve_procedures(
        asset_type=state.get("asset_type", "other"),
        symptoms=state.get("symptoms", []),
        safety_signals=state.get("safety_signals", []),
    )
    details = f"تم استرجاع {len(chunks)} إجراءات مناسبة من مراجع المشروع" if chunks else "لا يوجد إجراء موثق مناسب؛ يلزم الفحص الميداني"
    traces = _add_trace(state, "استرجاع إجراءات الصيانة (RAG)", details)
    return {
        "retrieved_procedures": [chunk.model_dump() for chunk in chunks],
        "trace": traces,
    }


@measured_node
def evaluate_policy_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 5: Apply deterministic safety and priority policies (No AI Hallucination)."""
    priority = determine_priority(
        asset_type=state.get("asset_type"),
        symptoms=state.get("symptoms", []),
        safety_signals=state.get("safety_signals", []),
    )
    safety_message = evaluate_safety(
        safety_signals=state.get("safety_signals", [])
    )
    traces = _add_trace(state, "تقييم قواعد الأمان والأولوية", f"الأولوية: {priority}")
    return {
        "priority": priority.lower(),
        "safety_message": safety_message,
        "trace": traces,
    }


@measured_node
def compose_recommendation_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 6: Write technical recommendation grounded in SOP chunks."""
    output = compose_recommendation(
        procedures=state.get("retrieved_procedures", []),
        context={
            "asset_type": state.get("asset_type"),
            "priority": state.get("priority"),
            "symptoms": state.get("symptoms", []),
            "safety_signals": state.get("safety_signals", []),
        },
    )
    details = "التوصية من نص الإجراءات المسترجعة" if output.evidence else "لا توجد توصية إصلاح موثقة؛ يُحوّل للفحص الميداني"
    traces = _add_trace(state, "صياغة التوصية الفنية", details)
    return {
        "recommended_action": output.recommended_action,
        "recommendation_status": output.recommendation_status,
        "recommendation_evidence": output.evidence,
        "trace": traces,
    }


@measured_node
def create_ticket_node(state: MaintenanceState) -> dict[str, Any]:
    """Node 7: Persist ticket in SQLite database."""
    priority = state.get("priority", "low").lower()
    is_critical = priority == "critical"
    
    ticket_status = "escalated" if is_critical else "created"
    ticket_id = insert_ticket({**state, "ticket_status": ticket_status}, db_path=settings.db_path)
    final_status = "critical" if is_critical else "success"
    
    traces = _add_trace(state, "إنشاء تذكرة الصيانة", f"رقم التذكرة: {ticket_id} ({ticket_status})")
    
    return {
        "ticket_id": ticket_id,
        "ticket_status": ticket_status,
        "status": final_status,
        "trace": traces,
    }
