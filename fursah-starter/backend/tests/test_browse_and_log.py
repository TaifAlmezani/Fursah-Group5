"""Similar-on-no-match fallback, the browse (show more / show all) endpoint, and the agent log."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from app.infrastructure.tracing import Tracer
from app.schemas import DiscoveryRequest, DiscoveryStatus, SearchConstraints, UserProfile
from app.workflow import discover, discover_all


def _req(query, **kw):
    return DiscoveryRequest(
        request_id=kw.pop("request_id", "b-1"),
        query=query,
        profile=UserProfile(**kw.pop("profile", {})),
        constraints=SearchConstraints(**kw.pop("constraints", {})),
        **kw,
    )


def test_no_topical_match_is_no_match(deps):
    """Day 4: a query with no topically-relevant match returns an honest no_match, not
    off-topic 'closest' recommendations."""
    r = asyncio.run(discover(_req("فرصة في الغوص والرياضات المائية"), deps))
    assert r.status is DiscoveryStatus.NO_MATCH
    assert r.recommendations == []


def test_impossible_constraints_still_no_match(deps):
    r = asyncio.run(discover(_req(
        "ورشة",
        constraints={"opportunity_types": ["internship"], "delivery_modes": ["online"],
                     "location_preference": ["نجران"], "max_budget_sar": 0},
    ), deps))
    assert r.status is DiscoveryStatus.NO_MATCH
    assert r.recommendations == []


def test_exact_match_not_padded_with_approximate(deps):
    """When exact matches exist, the shown cards are exact only (no off-topic padding)."""
    r = asyncio.run(discover(_req("ورشة في تحليل البيانات في الرياض"), deps))
    assert r.status is DiscoveryStatus.OK
    assert r.approximate is False
    assert all(not any("أقرب خيار" in c for c in rec.caveats) for rec in r.recommendations)


class _RecordingTracer(Tracer):
    """Captures what the backend tracer receives, without printing."""
    def __init__(self):
        super().__init__()
        self.steps: list[str] = []

    def emit(self, *, request_id, step, component, outcome, elapsed_ms=0, evidence_ids=None):
        self.steps.append(step)
        return None


def test_agent_log_goes_to_backend_not_the_response(deps):
    """Task 3: technical steps are logged in the BACKEND tracer, never on the public response."""
    tracer = _RecordingTracer()
    r = asyncio.run(discover(_req("ورشة في تحليل البيانات في الرياض"), replace(deps, tracer=tracer)))
    # The public response carries no technical log.
    assert "execution_log" not in r.model_dump()
    # The backend tracer recorded the agent stages.
    assert {"interpret", "tool.search", "assess", "rank"} <= set(tracer.steps)


def test_browse_pagination_is_consistent(deps):
    page1 = asyncio.run(discover_all(_req("فرصة تطوع في خدمة المجتمع"), deps, offset=0, limit=3))
    page2 = asyncio.run(discover_all(_req("فرصة تطوع في خدمة المجتمع"), deps, offset=3, limit=3))
    assert page1.total >= 1
    assert page1.offset == 0 and page2.offset == 3
    ids1 = {r.opportunity_id for r in page1.recommendations}
    ids2 = {r.opportunity_id for r in page2.recommendations}
    assert ids1.isdisjoint(ids2)  # pages do not overlap
    assert len(page1.recommendations) <= 3


def test_browse_endpoint_http(client):
    body = {"request_id": "http-browse", "query": "فرصة تطوع في خدمة المجتمع",
            "profile": {"interests": [], "skills": None}, "constraints": {}}
    response = client.post("/api/v1/discover/all?offset=0&limit=5", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert "total" in payload and payload["offset"] == 0 and payload["limit"] == 5
    assert isinstance(payload["recommendations"], list)
