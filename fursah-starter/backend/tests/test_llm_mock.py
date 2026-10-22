"""Optional LLM path with MOCK credentials — no network, no real key.

Verifies that model output is strictly validated (hallucinated vocabulary is dropped) and
that a mocked reason flows into the grounded recommendation.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app import agent
from app.infrastructure.dependencies import ModelClientConfig
from app.schemas import (
    DiscoveryRequest,
    DiscoveryStatus,
    SearchConstraints,
    UserProfile,
)
from app.workflow import discover

MOCK_CONFIG = ModelClientConfig(
    provider="openai",
    model_name="mock/model",
    api_key="sk-mock-not-a-real-key",
    base_url="https://openrouter.ai/api/v1",
    timeout_seconds=5,
    max_retries=0,
)


def test_interpret_query_returns_keywords_only(monkeypatch):
    """Query interpretation yields only soft keywords — never hard filters (type/mode/city)."""
    async def fake_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        return '{"keywords": ["بايثون", "برمجة"], "city": "جدة", "delivery_modes": ["online"]}'

    monkeypatch.setattr(agent.LlmClient, "complete", fake_complete)
    client = agent.LlmClient(MOCK_CONFIG)
    hints = asyncio.run(agent.interpret_query(client, "q", UserProfile(), SearchConstraints()))
    assert hints == {"keywords": ["بايثون", "برمجة"]}
    assert "delivery_modes" not in hints and "city" not in hints


def test_non_arabic_reason_is_rejected(monkeypatch, deps):
    """A non-Arabic (e.g. Chinese) model reason is dropped for the deterministic Arabic one."""
    async def fake_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        return "{}" if json_mode else "这是一个数据分析研讨会"  # Chinese

    monkeypatch.setattr(agent.LlmClient, "complete", fake_complete)
    deps_with_model = replace(deps, model_config=MOCK_CONFIG)
    request = DiscoveryRequest(
        request_id="llm-1", query="أبحث عن ورشة برمجة",
        profile=UserProfile(interests=["البرمجة"]),
        constraints=SearchConstraints(opportunity_types=["workshop"]),
    )
    result = asyncio.run(discover(request, deps_with_model))
    assert result.status is DiscoveryStatus.OK
    for rec in result.recommendations:
        assert "这" not in rec.reason  # the Chinese reason never reaches the user
        assert any("؀" <= c <= "ۿ" for c in rec.reason)  # Arabic fallback used


def test_ungrounded_reason_is_rejected(monkeypatch, deps):
    """An Arabic but off-topic reason (no link to the opportunity) is dropped for the fallback."""
    async def fake_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        return "{}" if json_mode else "هذه فرصة ممتازة وننصح بها بشدة"  # no title/topic words

    monkeypatch.setattr(agent.LlmClient, "complete", fake_complete)
    deps_with_model = replace(deps, model_config=MOCK_CONFIG)
    request = DiscoveryRequest(
        request_id="llm-2", query="أبحث عن ورشة برمجة",
        profile=UserProfile(interests=["البرمجة"]),
        constraints=SearchConstraints(opportunity_types=["workshop"]),
    )
    result = asyncio.run(discover(request, deps_with_model))
    assert result.status is DiscoveryStatus.OK
    assert all(rec.reason != "هذه فرصة ممتازة وننصح بها بشدة" for rec in result.recommendations)


def test_rerank_drops_invented_ids(monkeypatch):
    """The re-rank is grounded: ids not in the pool are silently dropped, order preserved."""
    async def fake_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        return '{"ranked_ids": ["SRC-B", "SRC-INVENTED", "SRC-A"]}'

    monkeypatch.setattr(agent.LlmClient, "complete", fake_complete)
    client = agent.LlmClient(MOCK_CONFIG)
    pool = [{"opportunity_id": "SRC-A"}, {"opportunity_id": "SRC-B"}]
    order = asyncio.run(agent.rerank(client, "q", UserProfile(), pool))
    assert order == ["SRC-B", "SRC-A"]  # invented id removed, model order kept


def test_rerank_reorders_results_in_discover(monkeypatch, deps):
    """A mocked re-rank that reverses the pool must move the last candidate to the top."""
    import json
    import re
    captured = {}

    async def fake_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        if json_mode and "ranked_ids" in system:
            ids = re.findall(r'"id":\s*"([^"]+)"', user)
            captured["ids"] = ids
            return json.dumps({"ranked_ids": list(reversed(ids))})
        return "{}" if json_mode else "سبب مُولّد"

    from dataclasses import replace
    monkeypatch.setattr(agent.LlmClient, "complete", fake_complete)
    deps_with_model = replace(deps, model_config=MOCK_CONFIG)
    # A query with several exact matches, so the re-rank (which needs >= 2) actually runs.
    request = DiscoveryRequest(
        request_id="rr", query="عرض الأفكار أمام الجمهور",
        profile=UserProfile(skills=[]),  # [] = explicitly none; no skill-gate
        constraints=SearchConstraints(),
    )
    result = asyncio.run(discover(request, deps_with_model))
    assert result.status is DiscoveryStatus.OK
    assert len(captured.get("ids", [])) >= 2  # the re-rank ran over the exact set
    # Top recommendation is the candidate the model ranked first (the reversed pool's head),
    # and it is one of the retrieved exact candidates (grounded, not invented).
    assert result.recommendations[0].opportunity_id == captured["ids"][-1]
    assert result.recommendations[0].opportunity_id in set(captured["ids"])


def test_llm_failure_falls_back_to_deterministic(monkeypatch, deps):
    """A model transport failure must not break discovery — the deterministic reason is used."""
    async def failing_complete(self, system, user, *, json_mode, max_tokens=400, purpose="llm"):
        return None  # simulate a transport/model failure

    monkeypatch.setattr(agent.LlmClient, "complete", failing_complete)
    deps_with_model = replace(deps, model_config=MOCK_CONFIG)

    request = DiscoveryRequest(
        request_id="llm-2",
        query="أبحث عن ورشة برمجة",
        profile=UserProfile(),
        constraints=SearchConstraints(opportunity_types=["workshop"]),
    )
    result = asyncio.run(discover(request, deps_with_model))
    assert result.status is DiscoveryStatus.OK
    assert all(rec.reason for rec in result.recommendations)  # non-empty fallback reasons
