# Deterministic application tools used by the discovery workflow.
#
# These are the small, source-grounded primitives the workflow composes. They return
# evidence (records carry their own source_ids) and never decide final rankings or
# eligibility on their own. An LLM cannot reach the dataset, so retrieval and deadline
# checks are ordinary code over the repository.
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .repository import OpportunityRepository, SearchCriteria

# Deadline outcomes. Deadlines in the corpus are DATE-ONLY (no hour), so an exact cutoff
# cannot be asserted: a same-day deadline stays uncertain rather than being called expired.
DEADLINE_UNKNOWN = "unknown"     # the source never stated a deadline
DEADLINE_OPEN = "open"           # deadline is in the future
DEADLINE_SAME_DAY = "uncertain"  # deadline is today; no hour is known, so keep it uncertain
DEADLINE_EXPIRED = "expired"     # the deadline day has fully passed


def search_opportunities(
    criteria: SearchCriteria, repo: OpportunityRepository, limit: int = 60
) -> list[dict[str, Any]]:
    """Return candidate records matching the resolved hard constraints (evidence, not rankings)."""
    return repo.search(criteria, limit=limit)


def get_opportunity_details(opportunity_id: str, repo: OpportunityRepository):
    """Return the source-grounded public details for one opportunity, or None if absent."""
    return repo.get_details(opportunity_id)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def evaluate_deadline(record: dict[str, Any], evaluation_time: datetime) -> str:
    """Classify a record's deadline against the request's single evaluation instant.

    evaluation_time is timezone-aware; the deadline is a bare date. We compare calendar
    days in the evaluation instant's own offset. Only a day that has fully passed counts
    as expired; the deadline day itself is uncertain because no hour was published.
    """
    deadline = _as_date(record.get("deadline_date")) or _as_date(record.get("deadline"))
    if deadline is None:
        return DEADLINE_UNKNOWN
    today = evaluation_time.date()
    if deadline < today:
        return DEADLINE_EXPIRED
    if deadline == today:
        return DEADLINE_SAME_DAY
    return DEADLINE_OPEN


def check_deadline(
    opportunity_id: str, repo: OpportunityRepository, evaluation_time: datetime
) -> str:
    """Tool wrapper: look up a record by id and classify its deadline."""
    record = repo.get_record(opportunity_id)
    if record is None:
        return DEADLINE_UNKNOWN
    return evaluate_deadline(record, evaluation_time)
