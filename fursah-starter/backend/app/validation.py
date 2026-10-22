# Evidence-based validation and safe handling of unknown information.
#
# Everything a recommendation shows must be traceable to the source record. This module is
# the gate that:
#   - verifies the source IDs attached to a recommendation really belong to that record,
#   - NEVER confirms eligibility from data the sources do not establish (age and study-year
#     are not collected, and "no stated condition" is not "eligible"), so eligibility stays
#     uncertain and the reason why is surfaced as a caveat,
#   - preserves source conflicts and unknowns (null cost, unknown deadline) instead of
#     guessing, turning each into a visible caveat.
from __future__ import annotations

from datetime import datetime
from typing import Any

from .schemas import EligibilityStatus, MatchFactor, Recommendation
from .tools import (
    DEADLINE_EXPIRED,
    DEADLINE_SAME_DAY,
    DEADLINE_UNKNOWN,
    evaluate_deadline,
)


def verify_sources(record: dict[str, Any]) -> list[str]:
    """Return the record's own non-blank source IDs. Empty means it cannot be grounded."""
    source_ids = record.get("source_ids")
    if not isinstance(source_ids, list):
        return []
    return [str(sid).strip() for sid in source_ids if isinstance(sid, str) and sid.strip()]


def assess_eligibility(record: dict[str, Any]) -> tuple[EligibilityStatus, list[str]]:
    """Eligibility is always uncertain for this corpus; explain the specific reason.

    The sources state requirements, never a confirmation that a given user qualifies, and the
    profile form does not collect age or study-year. Confirming eligibility here would be an
    invention, so we keep it uncertain and name what remains unverified.
    """
    caveats: list[str] = []
    mandatory = record.get("eligibility_mandatory")
    if isinstance(mandatory, list) and mandatory:
        joined = "؛ ".join(str(m) for m in mandatory if str(m).strip())
        if joined:
            caveats.append(f"شروط المصدر: {joined}. الأهلية غير مؤكدة من البيانات المتاحة.")
    else:
        caveats.append("لم يذكر المصدر شروطاً إلزامية؛ هذا لا يؤكد الأهلية.")

    if record.get("min_age") is not None:
        caveats.append("تشترط الفرصة حدًّا أدنى للعمر لا يجمعه النموذج؛ الأهلية غير مؤكدة.")
    if record.get("final_year_student_field"):
        caveats.append("تشترط الفرصة سنة دراسية/تخصصاً لا يجمعه النموذج؛ الأهلية غير مؤكدة.")

    return EligibilityStatus.UNCERTAIN, caveats


def collect_caveats(
    record: dict[str, Any], evaluation_time: datetime, application_status: str | None
) -> list[str]:
    """Build the visible caveats: deadline/registration state, unknown cost, conflicts, warnings."""
    caveats: list[str] = []

    deadline_state = evaluate_deadline(record, evaluation_time)
    if deadline_state == DEADLINE_EXPIRED:
        caveats.append("انقضى آخر يوم للتقديم حسب تاريخ التقويم المستخدم.")
    elif deadline_state == DEADLINE_SAME_DAY:
        caveats.append("آخر يوم للتقديم هو اليوم والساعة غير محددة؛ تحقق بسرعة.")
    elif deadline_state == DEADLINE_UNKNOWN:
        caveats.append("موعد التقديم غير مذكور أو غير مؤكد من المصدر.")

    if application_status == "not_yet_open":
        caveats.append("لم يبدأ التسجيل بعد حسب المصدر.")
    elif application_status == "closed":
        caveats.append("التسجيل مغلق حسب المصدر.")
    elif application_status == "requires_verification":
        caveats.append("حالة التسجيل متعارضة بين المصادر وتحتاج تحققاً.")

    if record.get("cost_sar") is None:
        caveats.append("الرسوم غير مذكورة؛ القيمة مجهولة وليست بالضرورة مجانية.")

    if record.get("delivery_mode") == "hybrid":
        caveats.append("الحضور مدمج: اللقاء الأول حضوري وإلزامي والمتابعة عن بعد.")

    # Preserve explicit source conflicts verbatim as caveats.
    for conflict in record.get("conflicts") or []:
        if isinstance(conflict, dict):
            field = conflict.get("field", "حقل")
            caveats.append(f"تعارض بين المصادر حول «{field}»؛ لم يُحسم.")

    # De-duplicate while preserving order; cap to keep the card readable.
    seen: set[str] = set()
    unique = [c for c in caveats if not (c in seen or seen.add(c))]
    return unique[:6]


def to_recommendation(
    record: dict[str, Any],
    *,
    reason: str,
    relevance_score: float | None,
    application_status: str | None,
    evaluation_time: datetime,
    extra_caveats: list[str] | None = None,
    match_factors: list[MatchFactor] | None = None,
) -> Recommendation | None:
    """Assemble a public Recommendation only if it is fully grounded in the record.

    Returns None when the record cannot be presented (no title or no verifiable source IDs),
    so an ungrounded candidate is dropped rather than shown. extra_caveats lets the caller
    flag an approximate ("closest, not exact") match.
    """
    source_ids = verify_sources(record)
    title = record.get("title")
    opportunity_id = record.get("opportunity_id") or record.get("source_id")
    if not source_ids or not title or not opportunity_id:
        return None

    eligibility, eligibility_caveats = assess_eligibility(record)
    caveats = (extra_caveats or []) + eligibility_caveats + collect_caveats(
        record, evaluation_time, application_status
    )
    seen: set[str] = set()
    caveats = [c for c in caveats if not (c in seen or seen.add(c))][:8]

    deadline = record.get("deadline_date") or record.get("deadline")

    return Recommendation(
        evidence_version=record.get("evidence_version") or None,
        opportunity_id=str(opportunity_id),
        title=str(title),
        opportunity_type=record.get("opportunity_type"),
        location=record.get("location"),
        delivery_mode=record.get("delivery_mode"),
        deadline=str(deadline) if deadline else None,
        application_status=application_status,
        eligibility_status=eligibility,
        reason=reason,
        caveats=caveats,
        source_ids=source_ids,
        relevance_score=relevance_score,
        match_factors=match_factors or [],
    )
