"""SQLite storage for prepared opportunities (SQLAlchemy 2.x).

Design:
  - opportunities:  one row per opportunity. Columns we FILTER on are real,
                    indexed columns. The complete prepared record (sources,
                    conflicts, warnings, eligibility...) is kept in `record`
                    so nothing from preparation is lost.
  - source_aliases: every source ID -> its opportunity, so a secondary
                    announcement such as SRC-0435 opens its parent SRC-0434.

The database is rebuilt from data/prepared/opportunities.json whenever the
data changes (that is why we don't need Alembic). From fursah-starter/backend:

    python -m app.infrastructure.db
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON, Boolean, Date, Float, ForeignKey, Integer, String, create_engine, select, func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_RELATIVE_PATH = Path("prepared") / "fursah.db"
JSON_RELATIVE_PATH = Path("prepared") / "opportunities.json"


class Base(DeclarativeBase):
    pass


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    organizer: Mapped[str | None] = mapped_column(String(200))
    topic: Mapped[str | None] = mapped_column(String(200), index=True)

    # Filter columns (None = unknown, never a default guess).
    opportunity_type: Mapped[str | None] = mapped_column(String(30), index=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(20), index=True)
    location: Mapped[str | None] = mapped_column(String(100), index=True)
    physical_attendance_required: Mapped[bool | None] = mapped_column(Boolean)
    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    deadline_date: Mapped[date | None] = mapped_column(Date, index=True)
    registration_statement: Mapped[str | None] = mapped_column(String(30), index=True)
    registration_opens_date: Mapped[date | None] = mapped_column(Date)
    cost_sar: Mapped[float | None] = mapped_column(Float, index=True)

    has_conflicts: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_version: Mapped[str] = mapped_column(String(64))

    # Full prepared record, exactly as produced by build_opportunities.py.
    record: Mapped[dict[str, Any]] = mapped_column(JSON)


class SourceAlias(Base):
    __tablename__ = "source_aliases"

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.opportunity_id"), index=True
    )


# --------------------------------------------------------------------------
# Engine and sessions
# --------------------------------------------------------------------------
def make_engine(data_dir: Path) -> Engine:
    """Open (or create) data/prepared/fursah.db.

    check_same_thread=False lets FastAPI's worker threads share the engine;
    each request still uses its own short-lived Session.
    """
    db_path = Path(data_dir) / DB_RELATIVE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def count_opportunities(engine: Engine) -> int:
    """Used by readiness: 0 when the table is missing or empty."""
    try:
        with Session(engine) as session:
            return session.scalar(select(func.count()).select_from(OpportunityRow)) or 0
    except Exception:
        return 0


# --------------------------------------------------------------------------
# Rebuild from the prepared JSON
# --------------------------------------------------------------------------
def _as_date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _to_row(record: dict[str, Any]) -> OpportunityRow:
    return OpportunityRow(
        opportunity_id=record["opportunity_id"],
        title=record["title"],
        organizer=record.get("organizer"),
        topic=record.get("topic"),
        opportunity_type=record.get("opportunity_type"),
        delivery_mode=record.get("delivery_mode"),
        location=record.get("location"),
        physical_attendance_required=record.get("physical_attendance_required"),
        start_date=_as_date(record.get("start_date")),
        end_date=_as_date(record.get("end_date")),
        duration_days=record.get("duration_days"),
        deadline_date=_as_date(record.get("deadline_date")),
        registration_statement=record.get("registration_statement"),
        registration_opens_date=_as_date(record.get("registration_opens_date")),
        cost_sar=record.get("cost_sar"),
        has_conflicts=bool(record.get("conflicts")),
        evidence_version=record["evidence_version"],
        record=record,
    )


def rebuild_from_json(engine: Engine, records: list[dict[str, Any]]) -> int:
    """Replace all stored opportunities with `records`, in one transaction."""
    if not records:
        raise ValueError("No prepared records: run data/build_opportunities.py first.")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        for record in records:
            session.add(_to_row(record))
        session.flush()  # opportunities first, so aliases can reference them
        for record in records:
            for source_id in record["source_ids"]:
                session.add(SourceAlias(source_id=source_id,
                                        opportunity_id=record["opportunity_id"]))
    return len(records)


def main() -> None:
    from .config import get_settings

    data_dir = get_settings().data_dir
    json_path = data_dir / JSON_RELATIVE_PATH
    records = json.loads(json_path.read_text(encoding="utf-8"))
    engine = make_engine(data_dir)
    count = rebuild_from_json(engine, records)
    print(f"Loaded {count} opportunities from {json_path} into {data_dir / DB_RELATIVE_PATH}")


if __name__ == "__main__":
    main()