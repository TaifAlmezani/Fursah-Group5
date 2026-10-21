"""Storage and retrieval layer: SQLite-backed details, search filters, unknown handling."""
from __future__ import annotations

from app.repository import SearchCriteria


def test_is_ready(repo):
    assert repo.is_ready() is True


def test_get_details_src_0001(repo):
    details = repo.get_details("SRC-0001")
    assert details is not None
    assert details.opportunity_id == "SRC-0001"
    assert details.title  # non-blank
    assert "SRC-0001" in details.source_ids
    assert details.evidence_version  # carried from the prepared record


def test_missing_id_returns_none(repo):
    assert repo.get_details("DOES-NOT-EXIST") is None
    assert repo.get_record("DOES-NOT-EXIST") is None


def test_unknown_cost_stays_unknown(repo):
    """A record with no stated fee maps to cost=None (unknown), never 0, with a warning."""
    record = next(
        r for r in repo._load_records() if r.get("cost_sar") is None
    )
    details = repo.get_details(record["opportunity_id"])
    assert details is not None
    assert details.cost is None
    assert any("الرسوم" in w for w in details.data_warnings)


def test_source_alias_resolves_to_parent(repo):
    """A secondary announcement id opens its canonical opportunity."""
    multi = next(
        r for r in repo._load_records() if len(r.get("source_ids", [])) > 1
    )
    secondary = multi["source_ids"][1]
    details = repo.get_details(secondary)
    assert details is not None
    assert details.opportunity_id == multi["opportunity_id"]
    assert details.canonical_id == multi["opportunity_id"]  # flagged because an alias was asked


def test_search_type_and_mode_filter(repo):
    results = repo.search(SearchCriteria(opportunity_types=["workshop"], delivery_modes=["online"]))
    assert results
    assert all(r["opportunity_type"] == "workshop" for r in results)
    assert all(r["delivery_mode"] == "online" for r in results)


def test_search_excludes_cancelled(repo):
    results = repo.search(SearchCriteria(), limit=900)
    assert all(r.get("registration_statement") != "cancelled" for r in results)


def test_search_budget_keeps_free_and_unknown(repo):
    """Free-only budget keeps cost<=0 and unknown-cost (uncertain), never paid opportunities."""
    results = repo.search(SearchCriteria(max_budget_sar=0.0), limit=900)
    assert all(r.get("cost_sar") in (None, 0.0) for r in results)


def test_application_status_mapping(repo):
    record = {"registration_statement": "open", "conflicts": []}
    assert repo.application_status(record) == "open"
    conflicted = {"registration_statement": "closed", "conflicts": [{"field": "registration_statement"}]}
    assert repo.application_status(conflicted) == "requires_verification"
    assert repo.application_status({"registration_statement": None, "conflicts": []}) is None
