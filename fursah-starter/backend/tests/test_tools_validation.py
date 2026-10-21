"""Deadline tool and evidence-based validation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas import EligibilityStatus
from app.tools import (
    DEADLINE_EXPIRED,
    DEADLINE_OPEN,
    DEADLINE_SAME_DAY,
    DEADLINE_UNKNOWN,
    evaluate_deadline,
)
from app.validation import assess_eligibility, to_recommendation, verify_sources

EVAL = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))


def test_deadline_states():
    assert evaluate_deadline({"deadline_date": None}, EVAL) == DEADLINE_UNKNOWN
    assert evaluate_deadline({"deadline_date": "2026-10-17"}, EVAL) == DEADLINE_EXPIRED
    # Same day is uncertain, not expired, because no hour was published.
    assert evaluate_deadline({"deadline_date": "2026-10-18"}, EVAL) == DEADLINE_SAME_DAY
    assert evaluate_deadline({"deadline_date": "2026-12-01"}, EVAL) == DEADLINE_OPEN


def test_verify_sources():
    assert verify_sources({"source_ids": ["SRC-1", " SRC-2 "]}) == ["SRC-1", "SRC-2"]
    assert verify_sources({"source_ids": []}) == []
    assert verify_sources({}) == []


def test_eligibility_is_never_confirmed():
    """Requirements are preserved as caveats; eligibility stays uncertain either way."""
    status, caveats = assess_eligibility({"eligibility_mandatory": ["معرفة Python مطلوبة"]})
    assert status is EligibilityStatus.UNCERTAIN
    assert any("Python" in c for c in caveats)

    status2, caveats2 = assess_eligibility({"eligibility_mandatory": None})
    assert status2 is EligibilityStatus.UNCERTAIN
    assert caveats2  # explains that "no stated condition" is not a confirmation


def test_to_recommendation_grounded():
    record = {
        "opportunity_id": "SRC-9",
        "title": "عنوان",
        "source_ids": ["SRC-9"],
        "opportunity_type": "workshop",
        "cost_sar": None,
        "deadline_date": "2026-12-01",
        "evidence_version": "abc123",
    }
    rec = to_recommendation(
        record, reason="سبب", relevance_score=70.0,
        application_status="open", evaluation_time=EVAL,
    )
    assert rec is not None
    assert rec.source_ids == ["SRC-9"]
    assert rec.eligibility_status is EligibilityStatus.UNCERTAIN
    assert any("الرسوم" in c for c in rec.caveats)  # unknown cost surfaced


def test_to_recommendation_rejects_ungrounded():
    assert to_recommendation(
        {"opportunity_id": "X", "title": "t", "source_ids": []},
        reason="r", relevance_score=1.0, application_status=None, evaluation_time=EVAL,
    ) is None
