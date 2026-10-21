# Learner guidance: prepare data/raw/raw_opportunities.csv using data/README.md.
# Choose your own storage and internal schema. The bridge is an optional CSV/JSON
# helper. Map your storage into the public API contract; rename/split this module freely.
from __future__ import annotations

import json
from typing import Any

from .infrastructure.data_package import DatasetLoader
from .infrastructure.errors import DataAccessError
from .schemas import OpportunityDetailsResponse

# Prefer a dedicated opportunity export if you create one later.
# Until then, reuse the notebook JSON you already prepared.
_PREPARED_FALLBACKS = (
    "prepared/source_preparation.json",
    "prepared/lesson_sample.json",
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class OpportunityRepository:
    """Maps prepared source rows into the public details contract."""

    def __init__(self, bridge: DatasetLoader) -> None:
        self.bridge = bridge
        self._records: list[dict[str, Any]] | None = None

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

    def is_ready(self) -> bool:
        """True only when prepared records can be loaded and at least one can be mapped."""
        try:
            records = self._load_records()
        except DataAccessError:
            return False
        return any(self._record_id(row) and self._title(row) for row in records)

    def search(self, criteria: Any):
        """TODO: criteria -> candidate records with source evidence from your store.

        Read exported data or your database, not notebook cell outputs.
        Internal candidate types and search technology are your choice.
        """
        raise NotImplementedError(
            "TODO(FURSAH-LEARNER): implement opportunity repository search"
        )

    def get_details(self, opportunity_id: str) -> OpportunityDetailsResponse | None:
        wanted = (opportunity_id or "").strip()
        if not wanted:
            return None

        for record in self._load_records():
            if self._record_id(record) == wanted:
                return self._to_details(record)
        return None

    def _record_id(self, record: dict[str, Any]) -> str | None:
        return _text(record.get("opportunity_id")) or _text(record.get("source_id"))

    def _title(self, record: dict[str, Any]) -> str | None:
        return _text(record.get("title")) or _text(record.get("title_suggestion"))

    def _to_details(self, record: dict[str, Any]) -> OpportunityDetailsResponse | None:
        opportunity_id = self._record_id(record)
        title = self._title(record)
        source_id = _text(record.get("source_id")) or opportunity_id
        if not opportunity_id or not title or not source_id:
            return None

        source_ids = record.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            source_ids = [source_id]
        source_ids = [text for item in source_ids if (text := _text(item))]
        if not source_ids:
            return None

        warnings: list[str] = []
        if record.get("title_needs_review"):
            warnings.append("العنوان مستخرج تلقائيًا ويحتاج مراجعة.")
        if record.get("deadline_state") == "uncertain" or (
            record.get("deadline_date") is None and record.get("deadline") is None
        ):
            warnings.append("موعد التقديم غير مؤكد من المصدر.")
        if record.get("cost") is None and record.get("cost_sar") is None:
            warnings.append("الرسوم غير مذكورة؛ القيمة مجهولة وليست مجانية.")

        cost = record.get("cost", record.get("cost_sar"))
        if cost is not None:
            try:
                cost = float(cost)
            except (TypeError, ValueError):
                cost = None
                warnings.append("تعذر قراءة قيمة الرسوم من السجل المعدّ.")

        extra_warnings = record.get("data_warnings")
        if isinstance(extra_warnings, list):
            warnings.extend(text for item in extra_warnings if (text := _text(item)))

        return OpportunityDetailsResponse(
            opportunity_id=opportunity_id,
            title=title,
            description=_text(record.get("description")) or _text(record.get("content")),
            application_url=_text(record.get("application_url")) or _text(record.get("activity_url")),
            cost=cost,
            deadline=_text(record.get("deadline")) or _text(record.get("deadline_date")),
            source_ids=source_ids,
            data_warnings=warnings,
        )
