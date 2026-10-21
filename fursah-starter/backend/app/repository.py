# Storage and retrieval layer.
#
# The prepared dataset (data/prepared/opportunities.json, produced reproducibly by
# data/build_opportunities.py) is loaded into SQLite via SQLAlchemy (app/infrastructure/db.py).
# Columns we filter on are real indexed columns; the complete prepared record is kept in a
# JSON column so no evidence, conflict or warning from preparation is ever lost.
#
# This module is the ONLY boundary between internal storage and the public API contract:
#   - search()       -> candidate records (internal dicts) for the discovery workflow
#   - get_details()  -> one OpportunityDetailsResponse (public contract)
# Mapping lives here so the rest of the application never depends on storage shapes.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .infrastructure.data_package import DatasetLoader
from .infrastructure.db import (
    OpportunityRow,
    SourceAlias,
    count_opportunities,
    make_engine,
    make_session_factory,
    rebuild_from_json,
)
from .infrastructure.errors import DataAccessError
from .schemas import EligibilityRequirements, OpportunityDetailsResponse

# If the prepared JSON is unavailable under its canonical name, reuse an earlier
# notebook export so the application still starts. Preparation remains reproducible
# through data/build_opportunities.py.
_PREPARED_FALLBACKS = (
    "prepared/source_preparation.json",
    "prepared/lesson_sample.json",
)

# registration_statement values map 1:1 to the frontend label keys in
# frontend/src/labels.ts. A source conflict about registration becomes
# "requires_verification"; an unknown status stays None (shown as "غير معروف").
_REGISTRATION_LABELS = {"open", "closed", "cancelled", "not_yet_open"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _str_list(value: Any) -> list[str] | None:
    """A nullable list of non-blank strings: None stays unknown, [] stays explicit-none."""
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    cleaned = [text for item in value if (text := _text(item))]
    return cleaned


@dataclass
class SearchCriteria:
    """Resolved, effective constraints passed identically to filtering and ranking.

    Built once per request by the workflow from the (resolved) profile + constraints +
    query so retrieval and scoring never disagree about what the user asked for.
    """

    text_terms: list[str] = field(default_factory=list)      # query keywords + interests
    opportunity_types: list[str] = field(default_factory=list)
    delivery_modes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)       # effective city filter
    available_from: date | None = None
    available_to: date | None = None
    max_duration_days: int | None = None
    max_budget_sar: float | None = None


class OpportunityRepository:
    """Maps prepared source rows into the public contract and serves candidate retrieval."""

    def __init__(self, bridge: DatasetLoader) -> None:
        self.bridge = bridge
        self._data_dir = bridge.data_dir
        self._records: list[dict[str, Any]] | None = None  # JSON cache (build source / fallback)
        self._session_factory = None

    # ------------------------------------------------------------------
    # SQLite access (auto-built from the prepared JSON on first use)
    # ------------------------------------------------------------------
    def _ensure_store(self):
        """Open the SQLite store, building it from the prepared JSON when empty.

        Auto-building keeps the demo to a single run command: no separate DB step is
        required, yet `python -m app.infrastructure.db` can still rebuild it explicitly.
        """
        if self._session_factory is not None:
            return self._session_factory
        engine = make_engine(self._data_dir)
        if count_opportunities(engine) == 0:
            rebuild_from_json(engine, self._load_records())
        self._session_factory = make_session_factory(engine)
        return self._session_factory

    # ------------------------------------------------------------------
    # JSON loading (build source for the DB and a resilient fallback)
    # ------------------------------------------------------------------
    def _load_records(self) -> list[dict[str, Any]]:
        if self._records is not None:
            return self._records

        try:
            records = self.bridge.load_prepared_opportunities()
        except DataAccessError:
            records = self._load_fallback_json()

        if not isinstance(records, list) or not records:
            raise DataAccessError("Prepared storage is empty or unreadable.")

        self._records = [row for row in records if isinstance(row, dict) and row]
        if not self._records:
            raise DataAccessError("Prepared storage has no object records.")
        return self._records

    def _load_fallback_json(self) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for relative in _PREPARED_FALLBACKS:
            path = self.bridge.data_dir / relative
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, ValueError) as exc:
                last_error = exc
                continue
            if isinstance(payload, list) and payload:
                return payload
        raise DataAccessError(
            "Could not read prepared JSON. Expected data/prepared/opportunities.json "
            "or source_preparation.json / lesson_sample.json."
        ) from last_error

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def is_ready(self) -> bool:
        """True only when the SQLite store is accessible and holds at least one opportunity."""
        try:
            factory = self._ensure_store()
            with factory() as session:
                return count_opportunities(session.get_bind()) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Retrieval for discovery
    # ------------------------------------------------------------------
    def search(self, criteria: SearchCriteria, limit: int = 60) -> list[dict[str, Any]]:
        """Apply hard constraints in SQL and return the full prepared records as candidates.

        Only constraints the source can actually support are enforced here. Unknown facts
        (null cost, null dates, null duration) are kept rather than excluded, so an unknown
        stays uncertain instead of being silently filtered out. Ranking happens in the
        workflow over these records; this method never decides eligibility or final order.
        """
        factory = self._ensure_store()
        stmt = select(OpportunityRow)

        # Cancelled opportunities are never actionable, so they are excluded outright.
        stmt = stmt.where(
            or_(
                OpportunityRow.registration_statement.is_(None),
                OpportunityRow.registration_statement != "cancelled",
            )
        )
        if criteria.opportunity_types:
            stmt = stmt.where(OpportunityRow.opportunity_type.in_(criteria.opportunity_types))
        if criteria.delivery_modes:
            stmt = stmt.where(OpportunityRow.delivery_mode.in_(criteria.delivery_modes))
        if criteria.locations:
            # Online opportunities are location-independent, so they survive a city filter.
            stmt = stmt.where(
                or_(
                    OpportunityRow.location.in_(criteria.locations),
                    OpportunityRow.delivery_mode == "online",
                )
            )
        if criteria.available_from is not None:
            stmt = stmt.where(
                or_(
                    OpportunityRow.start_date.is_(None),
                    OpportunityRow.start_date >= criteria.available_from,
                )
            )
        if criteria.available_to is not None:
            stmt = stmt.where(
                or_(
                    OpportunityRow.start_date.is_(None),
                    OpportunityRow.start_date <= criteria.available_to,
                )
            )
        if criteria.max_duration_days is not None:
            stmt = stmt.where(
                or_(
                    OpportunityRow.duration_days.is_(None),
                    OpportunityRow.duration_days <= criteria.max_duration_days,
                )
            )
        if criteria.max_budget_sar is not None:
            stmt = stmt.where(
                or_(
                    OpportunityRow.cost_sar.is_(None),
                    OpportunityRow.cost_sar <= criteria.max_budget_sar,
                )
            )

        with factory() as session:  # type: Session
            rows = session.execute(stmt.limit(limit)).scalars().all()
            # Detach the plain prepared dicts; the workflow never touches ORM objects.
            return [row.record for row in rows]

    def get_record(self, opportunity_id: str) -> dict[str, Any] | None:
        """Return the raw prepared record by opportunity id or secondary source alias."""
        wanted = (opportunity_id or "").strip()
        if not wanted:
            return None
        factory = self._ensure_store()
        with factory() as session:  # type: Session
            row = session.get(OpportunityRow, wanted)
            if row is None:
                alias = session.get(SourceAlias, wanted)
                if alias is not None:
                    row = session.get(OpportunityRow, alias.opportunity_id)
            return row.record if row is not None else None

    # ------------------------------------------------------------------
    # Details (public contract)
    # ------------------------------------------------------------------
    def get_details(self, opportunity_id: str) -> OpportunityDetailsResponse | None:
        wanted = (opportunity_id or "").strip()
        if not wanted:
            return None

        factory = self._ensure_store()
        with factory() as session:  # type: Session
            row = session.get(OpportunityRow, wanted)
            if row is None:
                # A secondary announcement ID (e.g. SRC-0435) resolves to its parent.
                alias = session.get(SourceAlias, wanted)
                if alias is not None:
                    row = session.get(OpportunityRow, alias.opportunity_id)
            if row is None:
                return None
            return self._to_details(row.record, requested_id=wanted)

    # ------------------------------------------------------------------
    # Record -> public details mapping (the single adaptation point)
    # ------------------------------------------------------------------
    def _record_id(self, record: dict[str, Any]) -> str | None:
        return _text(record.get("opportunity_id")) or _text(record.get("source_id"))

    def _title(self, record: dict[str, Any]) -> str | None:
        return _text(record.get("title")) or _text(record.get("title_suggestion"))

    def application_status(self, record: dict[str, Any]) -> str | None:
        """Map the source registration statement into a frontend label key.

        A registration conflict between sources is surfaced as needing verification
        rather than guessing a winner; an unmentioned status stays unknown (None).
        """
        if any(
            isinstance(c, dict) and c.get("field") == "registration_statement"
            for c in record.get("conflicts") or []
        ):
            return "requires_verification"
        statement = _text(record.get("registration_statement"))
        return statement if statement in _REGISTRATION_LABELS else None

    def _to_details(
        self, record: dict[str, Any], requested_id: str | None = None
    ) -> OpportunityDetailsResponse | None:
        opportunity_id = self._record_id(record)
        title = self._title(record)
        if not opportunity_id or not title:
            return None  # cannot present an opportunity without an id and a title

        source_ids = _str_list(record.get("source_ids")) or []
        if not source_ids:
            fallback = _text(record.get("source_id")) or opportunity_id
            source_ids = [fallback]
        if not source_ids:
            return None

        eligibility = EligibilityRequirements(
            mandatory=_str_list(record.get("eligibility_mandatory")),
            preferred=_str_list(record.get("eligibility_preferred")),
        )

        warnings = _str_list(record.get("data_warnings")) or []

        # canonical_id distinguishes the stable opportunity from a secondary source alias
        # the caller may have requested.
        canonical_id = opportunity_id if requested_id and requested_id != opportunity_id else None

        return OpportunityDetailsResponse(
            evidence_version=_text(record.get("evidence_version")),
            opportunity_id=opportunity_id,
            canonical_id=canonical_id,
            title=title,
            opportunity_type=_text(record.get("opportunity_type")),
            description=_text(record.get("description")) or _text(record.get("content")),
            location=_text(record.get("location")),
            delivery_mode=_text(record.get("delivery_mode")),
            start_date=_text(record.get("start_date")),
            end_date=_text(record.get("end_date")),
            remote_participation_allowed=record.get("remote_participation_allowed"),
            physical_attendance_required=record.get("physical_attendance_required"),
            duration=_positive_int(record.get("duration_days")),
            session_count=_positive_int(record.get("session_count")),
            hours_per_session=_positive_float(record.get("hours_per_session")),
            total_hours=_positive_float(record.get("total_hours")),
            application_url=_text(record.get("application_url")),
            deadline=_text(record.get("deadline_date")) or _text(record.get("deadline")),
            application_status=self.application_status(record),
            topics=_str_list(record.get("topics")) or [],
            eligibility_requirements=eligibility,
            required_skills=_str_list(record.get("required_skills")),
            cost=record.get("cost_sar") if isinstance(record.get("cost_sar"), (int, float)) else None,
            source_ids=source_ids,
            last_verified_at=_text(record.get("latest_published_at")),
            data_warnings=warnings,
        )
