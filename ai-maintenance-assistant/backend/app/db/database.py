import json
import re
import unicodedata
import sqlite3
from pathlib import Path
from typing import Any
import uuid
from contextlib import contextmanager
from collections.abc import Iterator

from app.schemas import AssetItem


@contextmanager
def get_db_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    """Create a thread-safe connection to the SQLite database."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: str, seed_path: str | None = None) -> None:
    """Initialize database tables and optionally load seed assets."""
    with get_db_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        
        # 1. Assets Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                asset_type TEXT NOT NULL,
                asset_name_ar TEXT,
                building TEXT,
                floor TEXT,
                room TEXT,
                model TEXT,
                status TEXT
            )
        """)
        
        # 2. Tickets Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                asset_id TEXT,
                asset_type TEXT NOT NULL,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                symptoms TEXT NOT NULL,
                safety_signals TEXT NOT NULL,
                priority TEXT NOT NULL,
                safety_message TEXT,
                recommended_action TEXT,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(tickets)")}
        if "recommendation_status" not in columns:
            cursor.execute("ALTER TABLE tickets ADD COLUMN recommendation_status TEXT NOT NULL DEFAULT 'legacy'")
        if "recommendation_evidence" not in columns:
            cursor.execute("ALTER TABLE tickets ADD COLUMN recommendation_evidence TEXT NOT NULL DEFAULT '[]'")
        if "operation_key" not in columns:
            cursor.execute("ALTER TABLE tickets ADD COLUMN operation_key TEXT")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS tickets_operation_key ON tickets(operation_key)")
        # Reserve one key per historical conversation without deleting old
        # duplicates. A new conversation for the same asset has a different key.
        cursor.execute("""
            UPDATE tickets SET operation_key = thread_id
            WHERE ticket_id IN (SELECT MIN(ticket_id) FROM tickets GROUP BY thread_id)
              AND operation_key IS NULL AND thread_id != ''
              AND NOT EXISTS (SELECT 1 FROM tickets AS keyed WHERE keyed.operation_key = tickets.thread_id)
        """)
        conn.commit()

        # Seed initial assets if provided and table is empty
        if seed_path and Path(seed_path).exists():
            cursor.execute("SELECT COUNT(*) FROM assets")
            if cursor.fetchone()[0] == 0:
                with open(seed_path, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                    for item in seed_data:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO assets 
                            (asset_id, asset_type, asset_name_ar, building, floor, room, model, status) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item["asset_id"],
                                item["asset_type"],
                                item.get("asset_name_ar", ""),
                                item.get("building", "A"),
                                item.get("floor", "1"),
                                item.get("room", ""),
                                item.get("model", ""),
                                item.get("status", "active")
                            )
                        )
                conn.commit()


def normalize_location(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    return re.sub(r"\s+", " ", value).strip()


def location_filters(location: str) -> tuple[set[str], str | None, str | None]:
    """Parse explicit room/floor/building selectors, never room substrings."""
    text = normalize_location(location)
    building_match = re.search(r"(?:مبنى|المبنى|building)\s+([a-z0-9]+)(?![a-z0-9])", text)
    floor_match = re.search(r"(?:الدور|دور|الطابق|طابق|floor)\s+(\d+|الأول|الاول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|الأرضي|الارضي)(?![\w])", text)
    ordinals = {"الأول":"1", "الاول":"1", "الثاني":"2", "الثالث":"3", "الرابع":"4", "الخامس":"5", "السادس":"6", "السابع":"7", "الثامن":"8", "التاسع":"9", "العاشر":"10", "الأرضي":"0", "الارضي":"0"}
    floor = ordinals.get(floor_match[1], floor_match[1]) if floor_match else None
    # Remove floor/building so their numbers cannot be mistaken for room IDs.
    room_text = text
    for match in sorted([m for m in [building_match, floor_match] if m], key=lambda m:m.start(), reverse=True):
        room_text = room_text[:match.start()] + " " + room_text[match.end():]
    rooms = set(re.findall(r"(?<![a-z0-9])(?:[a-z]+-?)?\d+(?![a-z0-9])", room_text))
    return rooms, floor, building_match[1] if building_match else None


def find_assets(asset_type: str, location: str, db_path: str) -> list[AssetItem]:
    rooms, floor, building = location_filters(location)
    if not rooms and floor is None and building is None:
        return []
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT asset_id, asset_type, asset_name_ar, building, floor, room, model, status FROM assets WHERE asset_type = ? ORDER BY asset_id",
            (asset_type,),
        ).fetchall()
    matches = []
    for row in rows:
        if rooms and normalize_location(row["room"] or "") not in rooms:
            continue
        if floor is not None and normalize_location(row["floor"] or "") != floor:
            continue
        if building is not None and normalize_location(row["building"] or "") != building:
            continue
        matches.append(AssetItem(**dict(row)))
    return matches


def insert_ticket(data: dict[str, Any], db_path: str) -> str:
    """Persist at most one ticket per workflow, including checkpoint retries."""
    ticket_status = data.get("ticket_status")
    asset_id = data.get("selected_asset_id") or data.get("asset_id")
    recommendation_status = data.get("recommendation_status", "legacy")
    evidence = data.get("recommendation_evidence", [])
    if recommendation_status not in {"grounded", "partial", "manual_review", "legacy"}:
        raise ValueError("Unknown recommendation status")
    if recommendation_status in {"grounded", "partial"} and not evidence:
        raise ValueError("A grounded recommendation requires source evidence")
    if recommendation_status == "manual_review" and evidence:
        raise ValueError("Manual review cannot claim supporting repair evidence")
    if ticket_status not in {"created", "escalated"} or not asset_id:
        raise ValueError("A registered asset and explicit ticket status are required")
    thread_id = data.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("A workflow thread_id is required for ticket idempotency")
    ticket_id = f"TICK-{uuid.uuid4().hex[:6].upper()}"
    with get_db_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT ticket_id, asset_id, status FROM tickets WHERE operation_key = ?", (thread_id,)).fetchone()
        if existing:
            if existing["asset_id"] != asset_id or existing["status"] != ticket_status:
                raise ValueError("The workflow already has a ticket for another result")
            return existing["ticket_id"]
        asset = conn.execute("SELECT asset_type, status, room, floor, building FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if asset is None or asset["asset_type"] != data.get("asset_type") or asset["status"] != "active":
            raise ValueError("Ticket asset must exist, match its type, and be in service")
        # The inventory may change during RAG/model work. Validate the matched
        # snapshot inside the same write transaction as the insert.
        selected = data.get("selected_asset")
        if selected is not None and any(
            normalize_location(asset[field] or "") != normalize_location(selected.get(field) or "")
            for field in ("room", "floor", "building")
        ):
            raise ValueError("Ticket asset location changed after matching")
        rooms, floor, building = location_filters(data.get("location") or "")
        if ((rooms and normalize_location(asset["room"] or "") not in rooms)
                or (floor is not None and normalize_location(asset["floor"] or "") != floor)
                or (building is not None and normalize_location(asset["building"] or "") != building)):
            raise ValueError("Ticket asset no longer matches the requested location")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tickets (
                ticket_id, thread_id, asset_id, asset_type, category,
                location, symptoms, safety_signals, priority,
                safety_message, recommended_action, status, recommendation_status, recommendation_evidence, operation_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                thread_id,
                data.get("selected_asset_id") or data.get("asset_id"),
                data.get("asset_type", "other"),
                data.get("category", "General"),
                data.get("location", ""),
                json.dumps(data.get("symptoms", []), ensure_ascii=False),
                json.dumps(data.get("safety_signals", []), ensure_ascii=False),
                data.get("priority", "LOW"),
                data.get("safety_message"),
                data.get("recommended_action"),
                ticket_status,
                data.get("recommendation_status", "legacy"),
                json.dumps(data.get("recommendation_evidence", []), ensure_ascii=False),
                thread_id,
            )
        )
        conn.commit()
    return ticket_id


def get_ticket(ticket_id: str, db_path: str) -> dict[str, Any] | None:
    """Retrieve ticket details by ID."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
