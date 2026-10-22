from __future__ import annotations

import time
from uuid import uuid4
from dataclasses import replace
from .infrastructure.tracing import Tracer

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .infrastructure.dependencies import AppDependencies, get_app_dependencies
from .infrastructure.errors import ErrorCode, FursahError, RecordNotFound
from .schemas import (
    ApiErrorResponse, BrowseResponse, DiscoveryRequest, DiscoveryResponse, DiscoveryStatus,
    HealthResponse, InterestRequest, InterestStatusResponse, InterestedListResponse,
    OpportunityDetailsResponse, ReadinessResponse,
)
from .workflow import discover, discover_all

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="fursah-api")


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    deps: AppDependencies = Depends(get_app_dependencies),
):
    checks, details = deps.readiness()
    is_ready = all(checks.values())
    payload = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        checks=checks,
        details=details,
    )
    if is_ready:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))


def _error_response(request_id: str, code: str, message: str, status_code: int = 503):
    payload = DiscoveryResponse(
        request_id=request_id,
        status=DiscoveryStatus.ERROR,
        message=message,
        recommendations=[],
        missing_fields=[],
        error_code=code,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


@router.post("/api/v1/discover", response_model=DiscoveryResponse)
async def discover_route(
    body: DiscoveryRequest,
    request: Request,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    deps = replace(deps, tracer=Tracer(deps.settings.trace_jsonl_path),
                   evaluation_time=deps.settings.resolve_evaluation_time())
    request_id = body.request_id or (request.headers.get("x-request-id") or "").strip()[:120] or str(uuid4())
    request.state.request_id = request_id
    body = body.model_copy(update={"request_id": request_id})
    started = time.perf_counter()

    deps.tracer.emit(
        request_id=request_id,
        step="request_received",
        component="api",
        outcome="success",
    )

    try:
        result = await discover(body, deps)
    except NotImplementedError:
        elapsed = (time.perf_counter() - started) * 1000
        deps.tracer.emit(
            request_id=request_id,
            step="request_failed",
            component="service",
            outcome="not_implemented",
            elapsed_ms=elapsed,
        )
        return _error_response(
            request_id,
            ErrorCode.NOT_IMPLEMENTED,
            "The FURSAH discovery workflow is intentionally unfinished in the starter.",
        )
    except FursahError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        deps.tracer.emit(
            request_id=request_id,
            step="request_failed",
            component="service",
            outcome=exc.public_code,
            elapsed_ms=elapsed,
        )
        return _error_response(
            request_id,
            exc.public_code,
            exc.public_message,
            status_code=exc.http_status,
        )
    except Exception:
        deps.tracer.emit(
            request_id=request_id,
            step="request_failed",
            component="service",
            outcome=ErrorCode.INTERNAL,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        raise

    elapsed = (time.perf_counter() - started) * 1000
    deps.tracer.emit(
        request_id=request_id,
        step="response_ready",
        component="api",
        outcome=result.status.value,
        elapsed_ms=elapsed,
        evidence_ids=[
            source_id
            for rec in result.recommendations
            for source_id in rec.source_ids
        ],
    )
    return result


@router.post("/api/v1/discover/all", response_model=BrowseResponse)
async def discover_all_route(
    body: DiscoveryRequest,
    request: Request,
    offset: int = 0,
    limit: int = 3,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    """Additive 'show more / show all' endpoint — does not change the /discover contract."""
    deps = replace(deps, tracer=Tracer(deps.settings.trace_jsonl_path),
                   evaluation_time=deps.settings.resolve_evaluation_time())
    request_id = body.request_id or (request.headers.get("x-request-id") or "").strip()[:120] or str(uuid4())
    body = body.model_copy(update={"request_id": request_id})
    return await discover_all(body, deps, offset=offset, limit=limit)


@router.post("/api/v1/interested", response_model=InterestStatusResponse)
def save_interest(
    body: InterestRequest,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    """Save ('مهتم') an opportunity for a browser-scoped client. Idempotent; 404 if unknown."""
    canonical = deps.repository.add_interest(body.client_id, body.opportunity_id)
    if canonical is None:
        payload = ApiErrorResponse(
            request_id=str(uuid4()), error_code=ErrorCode.OPPORTUNITY_NOT_FOUND,
            message="The requested opportunity was not found.", details=[],
        )
        return JSONResponse(status_code=404, content=payload.model_dump(mode="json"))
    return InterestStatusResponse(opportunity_id=canonical, interested=True)


@router.delete("/api/v1/interested/{opportunity_id}", response_model=InterestStatusResponse)
def remove_interest(
    opportunity_id: str,
    client_id: str,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    canonical = deps.repository.remove_interest(client_id, opportunity_id)
    return InterestStatusResponse(opportunity_id=canonical or opportunity_id, interested=False)


@router.get("/api/v1/interested", response_model=InterestedListResponse)
def list_interests(
    client_id: str,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    """A client's saved opportunities, most recent first (full details for display)."""
    opportunities = deps.repository.list_interested(client_id)
    return InterestedListResponse(
        client_id=client_id,
        opportunity_ids=[item.opportunity_id for item in opportunities],
        opportunities=opportunities,
    )


@router.get(
    "/api/v1/opportunities/{opportunity_id}",
    response_model=OpportunityDetailsResponse,
)
def opportunity_details(
    opportunity_id: str,
    deps: AppDependencies = Depends(get_app_dependencies),
):
    request_id = str(uuid4())
    try:
        result = deps.repository.get_details(opportunity_id)
        if result is None:
            raise RecordNotFound()
        return result
    except RecordNotFound as exc:
        payload = ApiErrorResponse(
            request_id=request_id,
            error_code=exc.public_code,
            message=exc.public_message,
            details=[],
        )
        return JSONResponse(status_code=404, content=payload.model_dump(mode="json"))
    except NotImplementedError:
        payload = ApiErrorResponse(
            request_id=request_id,
            error_code=ErrorCode.NOT_IMPLEMENTED,
            message=(
                "The prepared dataset has not yet been mapped into the "
                "application repository. Implement repository.get_details first."
            ),
            details=[],
        )
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))

    except FursahError as exc:
        payload = ApiErrorResponse(request_id=request_id, error_code=exc.public_code,
                                   message=exc.public_message, details=[])
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump(mode="json"))
