# Evaluability audit: team 5

Framework or SDK used: LangGraph (StateGraph orchestration). The LLM calls do NOT go through
LangChain — they are plain httpx to OpenRouter (`agent.LlmClient.complete`), so their spans are
added manually in 2.2.

| Component | Output | Kind of check | Missing signal |
|---|---|---|---|
| `interpret_node` (+ `agent.interpret_query`) | `SearchCriteria` (text_terms, opportunity_types, delivery_modes, locations, dates, budget) + `content_terms` + `conflict` flag; `interpret_query` returns `{"keywords": [...]}` | **Deterministic** — criteria built by fixed rules; LLM keywords are soft and validated, checkable from input+output | the resolved criteria and the keywords the model actually returned → `llm.interpret_query` span + the search span's `input.value` |
| `retrieve_node` → `tools.search_opportunities` → `repository.search` | a list of candidate records (opportunity_id, source_ids, title, topic, cost_sar, …) | **Verifiable** — recall needs the corpus and the case's `acceptable_source_ids` | the candidate **source IDs** returned (the tracer logged only a count) → `tool.search_opportunities` span `candidate_source_ids` |
| `assess_node` (`_actionable`, `tools.evaluate_deadline`, relevance filter, skill gap) | `outcome` (ok/no_match/needs_info), `ranked_all` (exact vs approximate), `approximate`; excluded candidates with a reason | **Verifiable** — the right outcome and the right exclusions need the case's expected status and `excluded_source_ids` | which candidates were excluded and why, the exact/approximate split, the outcome → `assess.filter` span (`excluded`, `off_topic_source_ids`, `exact_count`, `approximate_count`) |
| `rank_node` — `_score` | a relevance score, float 0–100 | **Deterministic** — a fixed formula over the record and query stems | the per-candidate score (surfaced as `relevance_score` on the recommendation) |
| `rank_node` — `agent.rerank` | an ordered list of `opportunity_id`s drawn only from the pool | **Deterministic** — "every returned id is in the pool" is checkable from input+output alone | the deterministic order vs the LLM order, and whether the LLM ran → `rank.rerank` span + the `llm.rerank` span (input/output/tokens) |
| `rank_node` — `agent.write_reason` / `_fallback_reason` | an Arabic reason string (LLM), or the deterministic fallback | **Subjective** — "is the reason helpful and faithful?" needs an LLM judge (the Arabic + grounding guards are the deterministic part) | the model's raw input/output and its token counts → `llm.write_reason` span |
| `validation.to_recommendation` (+ `verify_sources`) | `Recommendation` (verified `source_ids`, `eligibility_status` always `uncertain`, caveats, `match_factors`) or `None` when it cannot be grounded | **Deterministic** — `source_ids` ⊆ the record it was built from; eligibility is always `uncertain` | records dropped for lack of grounding (optional `validation.dropped` span) |
| `needs_info_node` / `no_match_node` | a `DiscoveryResponse` — `needs_info` with `missing_fields` and no recommendations; `no_match` empty | **Verifiable** — the correct outcome needs the case's expected status | none for the status itself: it is a field of the response the grader reads |
| `workflow.discover` (final answer) | `DiscoveryResponse` (status, recommendations[], their `source_ids`, missing_fields) | **Verifiable** — status vs expected, and recommended `source_ids` vs `acceptable`/`excluded` | none — the response IS what the grader receives; `request_id` is recorded on the `workflow.discover` root span to line it up with the JSONL trace |
| `repository.get_details` | `OpportunityDetailsResponse` for the details endpoint | **Verifiable** — details consistency (title/deadline/fee/source_ids) vs the recommendation; a separate endpoint | not in the `/discover` trace: it is a separate call, graded by its own team case |

**Subjective rows:** for each, what would an LLM judge need to see to grade it?

- `agent.write_reason`: the user's query + the opportunity's own facts (title/topic/the record) + the generated reason — so the judge can tell the reason faithfully explains *this* opportunity, invents nothing, and reads well.

**One label we changed after review, and why:**

- The ranking / final recommendations moved from **Subjective** to **Verifiable**: `dev_cases.jsonl` gives the expected source IDs (`acceptable_source_ids` / `excluded_source_ids`), so "did we recommend the right opportunities?" is a code check against those labels, not a matter of opinion. (We also corrected `agent.interpret_query` to **Deterministic** — it returns a fixed, validated keyword list checkable from its own input and output.)
