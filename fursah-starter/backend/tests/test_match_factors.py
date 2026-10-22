"""Auditable match factors: derived from real signals, never invented, uncertainty surfaced."""
from __future__ import annotations

import asyncio

from app.schemas import DiscoveryRequest, MatchKind, SearchConstraints, UserProfile
from app.workflow import discover


def test_recommendations_carry_auditable_match_factors(deps):
    r = asyncio.run(discover(DiscoveryRequest(
        request_id="mf",
        query="ورشة في تحليل البيانات في الرياض",
        profile=UserProfile(interests=["البيانات"]),
        constraints=SearchConstraints(),
    ), deps))
    assert r.recommendations
    rec = r.recommendations[0]

    assert rec.match_factors, "every recommendation explains its score"
    assert all(f.kind in {MatchKind.MATCH, MatchKind.MISMATCH, MatchKind.UNKNOWN} for f in rec.match_factors)
    assert all(f.text.strip() for f in rec.match_factors)  # no blank/invented factors
    # Eligibility uncertainty is always surfaced as an "unknown" factor.
    assert any(f.kind is MatchKind.UNKNOWN and "الأهلية" in f.text for f in rec.match_factors)
    # A matched search term / interest shows up as a confirmed match.
    assert any(f.kind is MatchKind.MATCH for f in rec.match_factors)
