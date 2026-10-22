"""Interested / saved opportunities: canonical-id resolution, idempotency, and the HTTP API."""
from __future__ import annotations


def test_add_is_remove_with_alias_resolution(repo):
    cid = "c-test-alias"
    multi = next(r for r in repo._load_records() if len(r.get("source_ids", [])) > 1)
    alias = multi["source_ids"][1]
    canonical = multi["opportunity_id"]

    # Saving via a secondary source id stores (and reports) the canonical opportunity id.
    assert repo.add_interest(cid, alias) == canonical
    assert repo.is_interested(cid, canonical) is True
    assert repo.is_interested(cid, alias) is True
    assert canonical in repo.interested_ids(cid)

    # Idempotent: saving again makes no duplicate row.
    repo.add_interest(cid, canonical)
    assert repo.interested_ids(cid).count(canonical) == 1

    repo.remove_interest(cid, alias)
    assert repo.is_interested(cid, canonical) is False


def test_add_unknown_opportunity_returns_none(repo):
    assert repo.add_interest("c-unknown", "NOPE-404") is None


def test_list_interested_returns_details(repo):
    cid = "c-test-list"
    repo.add_interest(cid, "SRC-0001")
    try:
        items = repo.list_interested(cid)
        assert any(d.opportunity_id == "SRC-0001" and d.title for d in items)
    finally:
        repo.remove_interest(cid, "SRC-0001")


def test_interested_endpoints(client):
    cid = "c-http-test"
    saved = client.post("/api/v1/interested", json={"client_id": cid, "opportunity_id": "SRC-0001"})
    assert saved.status_code == 200
    assert saved.json() == {"opportunity_id": "SRC-0001", "interested": True}

    listed = client.get(f"/api/v1/interested?client_id={cid}")
    assert listed.status_code == 200
    assert "SRC-0001" in listed.json()["opportunity_ids"]
    assert any(o["opportunity_id"] == "SRC-0001" for o in listed.json()["opportunities"])

    # Unknown opportunity -> 404, not a silent save.
    assert client.post("/api/v1/interested", json={"client_id": cid, "opportunity_id": "NOPE-9"}).status_code == 404

    removed = client.delete(f"/api/v1/interested/SRC-0001?client_id={cid}")
    assert removed.status_code == 200 and removed.json()["interested"] is False
    assert "SRC-0001" not in client.get(f"/api/v1/interested?client_id={cid}").json()["opportunity_ids"]
