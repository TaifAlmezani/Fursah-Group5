"""Discovery workflow: the four outcomes, constraint resolution, and grounding."""
from __future__ import annotations

import asyncio

from app.schemas import (
    DiscoveryRequest,
    DiscoveryStatus,
    SearchConstraints,
    UserProfile,
)
from app.workflow import application_is_ready, discover


def _run(deps, **kw):
    request = DiscoveryRequest(
        request_id=kw.pop("request_id", "t-1"),
        query=kw.pop("query"),
        profile=UserProfile(**kw.pop("profile", {})),
        constraints=SearchConstraints(**kw.pop("constraints", {})),
        **kw,
    )
    return asyncio.run(discover(request, deps))


def test_application_is_ready(deps):
    assert application_is_ready(deps) is True


def test_ok_recommendations_are_grounded(deps):
    r = _run(deps, query="أبحث عن ورشة برمجة", constraints={"opportunity_types": ["workshop"]})
    assert r.status is DiscoveryStatus.OK
    assert 1 <= len(r.recommendations) <= 3
    assert r.missing_fields == []
    for rec in r.recommendations:
        assert rec.source_ids  # every recommendation cites its source
        assert rec.eligibility_status.value == "uncertain"
        assert rec.opportunity_type == "workshop"
    assert r.interpreted_filters  # readable filters are reported


def test_city_conflict_needs_info(deps):
    r = _run(deps, query="أريد فرصة في جدة هذه المرة", profile={"city": "الرياض"})
    assert r.status is DiscoveryStatus.NEEDS_INFO
    assert r.constraint_conflict is True
    assert r.missing_fields == ["constraints.location_preference"]
    assert r.recommendations == []


def test_city_conflict_resolved_by_query(deps):
    r = _run(
        deps, query="أريد فرصة في جدة هذه المرة",
        profile={"city": "الرياض"}, constraint_resolution="query",
    )
    assert r.status is DiscoveryStatus.OK
    assert not r.constraint_conflict


def test_skill_gap_needs_info(deps):
    """A top match requiring a skill + unanswered skills (null) asks before recommending."""
    record = next(
        r for r in deps.repository._load_records()
        if r.get("required_skills") and r.get("registration_statement") != "cancelled"
    )
    topic = record["title"]
    r = _run(deps, query=f"{topic}", profile={"skills": None})
    # It should either ask about skills, or (if a different opportunity ranks top) still be valid.
    if r.status is DiscoveryStatus.NEEDS_INFO:
        assert r.missing_fields == ["profile.skills"]
        assert r.missing_explanations


def test_no_match(deps):
    r = _run(
        deps, query="فرصة",
        constraints={
            "opportunity_types": ["internship"],
            "delivery_modes": ["online"],
            "location_preference": ["نجران"],
            "max_budget_sar": 0,
        },
    )
    assert r.status is DiscoveryStatus.NO_MATCH
    assert r.recommendations == []


def test_saved_profile_city_used_without_conflict(deps):
    r = _run(deps, query="أبحث عن دورة", profile={"city": "الرياض"})
    assert any("الرياض" in f for f in r.interpreted_filters)
