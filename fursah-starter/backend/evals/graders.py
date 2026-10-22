"""Day 4 · 2.3: code graders, one per component from your 2.1 audit.

Every grader has the same signature:

    grader(case, response, spans) -> Grade | None

case      one line of dev_cases.jsonl. Its "expected" block holds:
            status                 "ok" or "no_match"
            acceptable_source_ids  recommending ANY source of these opportunities is correct
            excluded_source_ids    {source_id: reason}: recommending these is wrong, even
                                   next to an acceptable source in the same recommendation
            uncertain_source_ids   {source_id: reason}: availability unknown; a recommendation
                                   made only of these is not graded (always empty in no_match cases)
response  the DiscoveryResponse your workflow.discover() returned
spans     {span name: attributes} for this case's trace; the last span wins when a name
          repeats. spans.all(name) returns every span with that name, in order.

Return None when the case has nothing to check for this metric (e.g. no acceptable IDs).
Put the expected and the actual value in `reason`: it is printed under every failing case.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Grade:
    metric: str
    score: float  # 0..1
    reason: str = ""  # "expected X, got Y"


def tool_inputs(spans, tool_name: str) -> list[dict]:
    """Arguments of every call to `tool_name`, for any framework that records tool spans.

    LangChain, LangGraph and PydanticAI all record `tool.name` and the arguments as JSON in
    `input.value`. Without a framework, record them yourself on a custom span with the same keys.
    Exception: LangChain records a tool with ONE argument as the bare value, not JSON; that
    call comes back as {"raw": value}. Print tool_inputs(...) once to see what yours returns.
    """
    calls = []
    for attributes in spans.all_spans():
        if attributes.get("tool.name") == tool_name:
            value = attributes.get("input.value") or "{}"
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            calls.append(parsed if isinstance(parsed, dict) else {"raw": value})
    return calls


# --- Example (given) ---------------------------------------------------------------

def grade_status(case, response, spans):
    expected = case["expected"]["status"]
    got = response.status.value
    return Grade("e2e.status", float(got == expected), f"expected {expected!r}, got {got!r}")


# --- Your graders: one per deterministic or verifiable component in your 2.1 table ---

def _expected_sets(case):
    """Acceptable / excluded / uncertain SOURCE ids for a case (answers are source ids)."""
    expected = case["expected"]
    return (
        set(expected.get("acceptable_source_ids") or []),
        set(expected.get("excluded_source_ids") or {}),   # {source_id: reason}
        set(expected.get("uncertain_source_ids") or {}),
    )


def _recommended_source_ids(response):
    return {sid for rec in response.recommendations for sid in rec.source_ids}


def grade_search_recall(case, response, spans):
    """retrieve_node/search (Verifiable): did retrieval surface at least one acceptable source?
    Uses the 2.2 `tool.search_opportunities` span. Separates a retrieval miss from a ranking
    miss. N/A (None) for no_match cases, which have no acceptable sources."""
    acceptable, _, _ = _expected_sets(case)
    if not acceptable:
        return None
    attributes = spans.get("tool.search_opportunities") or {}
    candidates = set(attributes.get("candidate_source_ids") or [])
    hit = bool(candidates & acceptable)
    return Grade("search.recall", float(hit),
                 f"acceptable {sorted(acceptable)} retrieved: {hit} (candidates={len(candidates)})")


def grade_recommendations(case, response, spans):
    """discover final answer (Verifiable): judge each recommendation by its source ids —
    any excluded source => wrong; all-uncertain => not graded; >=1 acceptable & none excluded
    => right; in none of the lists (off topic) => wrong. Score = right / graded."""
    acceptable, excluded, uncertain = _expected_sets(case)
    if not acceptable and not excluded:
        return None  # nothing to grade (e.g. no_match): the status grader covers it
    graded = right = 0
    for rec in response.recommendations:
        sids = set(rec.source_ids)
        if sids & excluded:
            graded += 1                      # wrong: an excluded source is attached
        elif sids and sids <= uncertain:
            continue                         # not graded: availability genuinely unknown
        elif sids & acceptable:
            graded += 1; right += 1          # right: on topic, available, no excluded source
        else:
            graded += 1                      # wrong: off topic
    if graded == 0:
        return None
    return Grade("e2e.recommendations", right / graded,
                 f"{right}/{graded} right; acceptable any of {sorted(acceptable)}, "
                 f"got {[r.source_ids for r in response.recommendations]}")


def grade_no_excluded(case, response, spans):
    """assess_node exclusions (Verifiable): never recommend a source the case excludes."""
    _, excluded, _ = _expected_sets(case)
    if not excluded:
        return None
    recommended_excluded = _recommended_source_ids(response) & excluded
    return Grade("e2e.no_excluded", float(not recommended_excluded),
                 f"excluded sources recommended: {sorted(recommended_excluded)}")


def grade_rerank_grounded(case, response, spans):
    """rerank (Deterministic): the LLM order must only reorder the pool — final ids ⊆ pool.
    Applies only when the re-rank actually ran (needs a live model)."""
    attributes = spans.get("rank.rerank") or {}
    if not attributes.get("used_llm"):
        return None
    pool = set(attributes.get("deterministic_order") or [])
    final = set(attributes.get("final_order") or [])
    return Grade("rerank.grounded", float(final <= pool),
                 f"final order ⊆ pool: {final <= pool}")


GRADERS = [
    grade_status,
    grade_search_recall,
    grade_recommendations,
    grade_no_excluded,
    grade_rerank_grounded,
]
