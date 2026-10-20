from contextlib import asynccontextmanager, closing
import uuid
import logging
from fastapi.responses import JSONResponse
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from app.config import settings
from app.db.database import init_db, get_ticket
from app.schemas import ContinuationRequest, MaintenanceRequest
from app.workflow.graph import get_workflow_graph
from app.workflow.locking import continuation_lock, ContinuationInProgressError
from app.llm.client import get_llm_client, ModelUnavailableError, StructuredOutputError
from app.rag.engine import initialize_rag, get_rag_status, RAGUnavailableError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    print(f"Starting {settings.app_name}...")
    # Initialize SQLite database and seed initial assets
    init_db(settings.db_path, settings.seed_path)
    # Pre-compile the LangGraph workflow with SQLite checkpointer
    get_workflow_graph()
    initialize_rag()
    get_llm_client().initialize()
    print("Application initialized. Check /ready for actual model readiness.")
    try:
        yield
    finally:
        shutdown = getattr(get_llm_client(), "shutdown", None)
        if shutdown:
            shutdown()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Agentic Maintenance Assistant with LangGraph, RAG, and ASL-4B-v1",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _format_frontend_response(state_dict: dict, request_id: str, thread_id: str) -> dict:
    status_value = state_dict.get("status")
    base = {"request_id": request_id, "thread_id": thread_id, "trace": state_dict.get("trace", [])}
    warning = {"safety_message": state_dict["safety_message"]} if state_dict.get("safety_message") else {}

    def asset_response(asset):
        parts = [asset.get("room") or asset.get("location"), f"مبنى {asset['building']}" if asset.get("building") else None, f"الدور {asset['floor']}" if asset.get("floor") else None]
        return {"asset_id": asset["asset_id"], "asset_type": asset["asset_type"], "location": " — ".join(str(p) for p in parts if p), "model": asset.get("model"), "status": asset.get("status")}

    if status_value == "needs_information":
        return {**base, **warning, "status": status_value, "missing_fields": state_dict.get("missing_fields", []), "question": state_dict.get("question") or "يرجى تحديد الموقع أو الغرفة لإكمال البلاغ."}
    if status_value == "needs_asset_selection":
        candidates = state_dict.get("candidate_assets", [])
        if candidates:
            return {**base, **warning, "status": status_value, "message": state_dict.get("message") or "يرجى اختيار الجهاز المتعطل.", "assets": [asset_response(a) for a in candidates]}
    if status_value == "asset_not_found":
        return {**base, **warning, "status": status_value, "message": state_dict.get("message") or "الجهاز غير مسجل في هالموقع. يرجى التواصل مع قسم الصيانة."}
    if status_value in {"success", "critical"}:
        ticket_id = state_dict.get("ticket_id")
        asset = state_dict.get("selected_asset")
        ticket = get_ticket(ticket_id, settings.db_path) if ticket_id else None
        expected = "escalated" if status_value == "critical" else "created"
        if ticket and asset and ticket["thread_id"] == thread_id and ticket["asset_id"] == asset.get("asset_id") and ticket["status"] == expected:
            import json
            evidence = json.loads(ticket.get("recommendation_evidence") or "[]")
            return {**base, **warning, "status": status_value, "ticket": {"ticket_id": ticket["ticket_id"], "status": ticket["status"]}, "asset": asset_response(asset), "analysis": {"category": ticket["category"], "priority": ticket["priority"], "symptoms": state_dict.get("symptoms", []), "safety_signals": state_dict.get("safety_signals", [])}, "recommended_action": ticket["recommended_action"], "recommendation_status":ticket.get("recommendation_status", "legacy"), "evidence":[{key:item.get(key) for key in ("procedure_id", "source", "section", "score", "source_sha256", "index_generation")} for item in evidence]}
    return {**base, **warning, "status": "error", "message": "تعذر تأكيد نتيجة البلاغ. يرجى التواصل مع قسم الصيانة.", "retryable": False}


def _failure_response(exc: Exception, request_id: str, thread_id: str):
    logger.error("Maintenance request failed: request_id=%s thread_id=%s", request_id, thread_id, exc_info=True)
    unavailable = isinstance(exc, (ModelUnavailableError, RAGUnavailableError))
    message = "مراجع الصيانة غير جاهزة. يرجى التواصل مع مسؤول النظام." if isinstance(exc,RAGUnavailableError) else "النموذج المحلي غير جاهز. يرجى التواصل مع مسؤول النظام." if unavailable else "تعذر معالجة البلاغ حاليًا. يرجى التواصل مع قسم الصيانة."
    error_code = "rag_unavailable" if isinstance(exc, RAGUnavailableError) else "model_unavailable" if isinstance(exc, ModelUnavailableError) else "invalid_model_output" if isinstance(exc, StructuredOutputError) else "processing_failed"
    return JSONResponse(status_code=503 if unavailable else 502 if isinstance(exc, StructuredOutputError) else 500,
        content={"status":"error", "request_id":request_id, "thread_id":thread_id,
                 "message":message, "error_code":error_code, "retryable":False})


def _snapshot_response(snapshot, request_id: str, thread_id: str) -> dict:
    """Expose the current interrupt identity; never resume from a read request."""
    if snapshot.tasks and snapshot.tasks[0].interrupts:
        waiting = snapshot.tasks[0].interrupts[0]
        return {**_format_frontend_response(waiting.value, request_id, thread_id), "step_id": waiting.id}
    return _format_frontend_response(snapshot.values, request_id, thread_id)


@app.get("/api/maintenance/requests/{thread_id}")
def read_maintenance_request(thread_id: str):
    request_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    try:
        with continuation_lock(thread_id, settings.checkpoints_db_path):
            snapshot = get_workflow_graph().get_state({"configurable": {"thread_id": thread_id}})
            if not snapshot or not snapshot.values:
                raise HTTPException(status_code=404, detail="تعذر العثور على الطلب المطلوب استكماله.")
            return {**_snapshot_response(snapshot, request_id, thread_id),
                    "description": snapshot.values.get("description", ""),
                    "location": snapshot.values.get("location")}
    except ContinuationInProgressError:
        raise HTTPException(status_code=409, detail="يجري تحديث هذا الطلب حاليًا.")
    except HTTPException:
        raise
    except Exception as exc:
        return _failure_response(exc, request_id, thread_id)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/ready")
@app.get("/ready")
def readiness_check():
    """Readiness probe for database and workflow availability."""
    client = get_llm_client()
    model_status = client.get_status()
    try:
        import sqlite3
        from pathlib import Path
        with closing(sqlite3.connect(Path(settings.db_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("SELECT asset_id FROM assets LIMIT 1")
            connection.execute("SELECT ticket_id FROM tickets LIMIT 1")
        database_ready = True
    except Exception:
        database_ready = False
    try:
        workflow_ready = get_workflow_graph() is not None
    except Exception:
        workflow_ready = False
    model_ready = settings.llm_mode == "heuristic" or (model_status["is_neural_loaded"] and model_status["generation_verified"])
    rag_status = get_rag_status()
    ready = database_ready and workflow_ready and model_ready and rag_status["ready"]
    return JSONResponse(status_code=200 if ready else 503, content={
        "status": "ready" if ready else "not_ready", "model": settings.llm_model,
        "database_ready": database_ready, "workflow_ready": workflow_ready,
        "model_status": model_status,
        "rag_ready":rag_status["ready"], "rag_status":rag_status,
    })


@app.post("/api/maintenance/requests")
@app.post("/api/v1/maintenance/report")
def handle_maintenance_request(request: MaintenanceRequest):
    """Create a new maintenance request (called by React frontend)."""
    request_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    thread_id = f"th_{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "request_id": request_id,
        "thread_id": thread_id,
        "description": request.description,
        "location": request.location,
        "follow_up_answers": [],
        "trace": [],
    }

    try:
        graph = get_workflow_graph()
        graph.invoke(initial_state, config=config)
        
        # Check current graph state
        snapshot = graph.get_state(config)
        return _snapshot_response(snapshot, request_id, thread_id)
    except Exception as e:
        return _failure_response(e, request_id, thread_id)


@app.post("/api/maintenance/requests/{thread_id}/continue")
@app.post("/api/v1/maintenance/resume")
def handle_continuation_request(thread_id: str, request: ContinuationRequest):
    """Resume an interrupted maintenance workflow with user clarification or asset selection."""
    request_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    try:
        with continuation_lock(thread_id, settings.checkpoints_db_path):
            return _resume_maintenance_request(thread_id, request, request_id)
    except ContinuationInProgressError:
        raise HTTPException(status_code=409, detail="يجري استكمال هذا الطلب حاليًا. لا يمكن استخدام الإجابة مرتين.")
    except HTTPException:
        raise
    except Exception as exc:
        return _failure_response(exc, request_id, thread_id)


def _resume_maintenance_request(thread_id: str, request: ContinuationRequest, request_id: str):
    # Read and validate only after acquiring the lock; no worker may resume
    # a snapshot read before another worker consumed its interruption.
    config = {"configurable": {"thread_id": thread_id}}
    graph = get_workflow_graph()

    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="تعذر العثور على الطلب المطلوب استكماله."
        )

    if not snapshot.tasks or not snapshot.tasks[0].interrupts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="هذا الطلب مكتمل أو لا ينتظر هذا النوع من الإجابات."
        )

    if request.step_id != snapshot.tasks[0].interrupts[0].id:
        raise HTTPException(status_code=409, detail="هذه الإجابة تخص خطوة سابقة. حدّث البلاغ للإجابة عن السؤال الحالي.")

    waiting_status = snapshot.values.get("status")
    expected_input = "asset_selection" if waiting_status == "needs_asset_selection" else "text"
    if request.input_type != expected_input:
        raise HTTPException(status_code=409, detail="نوع الإجابة لا يطابق الخطوة الحالية.")
    if expected_input == "asset_selection":
        candidates = snapshot.values.get("candidate_assets", [])
        if request.asset_id not in {a["asset_id"] for a in candidates}:
            raise HTTPException(status_code=422, detail="اختيار الجهاز غير صالح. اختر جهازاً من القائمة.")

    # Determine continuation payload
    continuation = {}
    if request.input_type == "text" and request.text:
        continuation = {"field": "clarification", "answer": request.text}
    elif request.input_type == "asset_selection" and request.asset_id:
        continuation = {"asset_id": request.asset_id}
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="بيانات الإدخال غير صالحة."
        )

    graph.invoke(Command(resume=continuation), config=config)

    new_snapshot = graph.get_state(config)
    return _snapshot_response(new_snapshot, request_id, thread_id)
