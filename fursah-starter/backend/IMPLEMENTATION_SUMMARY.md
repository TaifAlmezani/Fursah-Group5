# FURSAH Backend — Implementation Summary

What was built on top of the supplied FastAPI shell to deliver a working, evidence-based
Arabic opportunity-discovery API, and how to run it.

## Architecture at a glance

```
raw_opportunities.csv  (1,000 announcements, unchanged)
      │  data/build_opportunities.py   (reproducible preparation)
      ▼
opportunities.json  (900 opportunities: merged by activity, conflicts + unknowns preserved)
      │  app/infrastructure/db.py       (SQLAlchemy -> SQLite, auto-built on first run)
      ▼
SQLite  (filter columns indexed + full prepared record kept as JSON)
      │
      ├── repository.py  ──► get_details(id)  → OpportunityDetailsResponse   (GET /opportunities/{id})
      │                   ──► search(criteria) → candidate records
      ▼
workflow.py  (LangGraph):  interpret → retrieve → assess → {needs_info | no_match | rank}
      │   tools.py (deterministic search + deadline)   validation.py (evidence gate)
      │   agent.py (OPTIONAL OpenRouter LLM: query hints + Arabic reason phrasing)
      ▼
DiscoveryResponse   (POST /api/v1/discover)   →  React frontend (unchanged contract)
```

## Core design decision: deterministic grounding, optional LLM

An LLM cannot reach the dataset, and a demo must be reliable. So **retrieval, ranking,
eligibility and every `source_id` are deterministic code** over the repository. The LLM
(OpenRouter, OpenAI-compatible) is used only where it genuinely helps and is always
bounded with a deterministic fallback:

1. `interpret_query` — turn the free Arabic query into retrieval hints (keywords / city /
   type). Output is strictly validated against known vocabulary, so the model can only
   narrow or enrich retrieval, never inject unsupported values.
2. `write_reason` — phrase one Arabic sentence for an **already-selected, grounded**
   recommendation.

**The whole application runs with no API key.** With `FURSAH_MODEL_API_KEY` blank it uses
the deterministic path end-to-end; a key only upgrades query understanding and reason
wording. This is why `/ready` reports ready without a provider.

*Why `httpx` directly instead of the `openai` SDK:* the two LLM touch-points are small
chat calls, and `httpx` is already a dependency — adding an SDK would be unnecessary
complexity for no benefit.

*Why LangGraph:* it gives one declarative place for the branch between a grounded answer,
a clarification request (`needs_info`) and "no match", with each stage traceable. The
nodes themselves stay simple and deterministic.

## What each module does

| Module | Responsibility |
|---|---|
| `app/infrastructure/db.py` | SQLAlchemy schema + SQLite engine/session; `rebuild_from_json`; source-alias table so a secondary announcement ID opens its parent. |
| `app/repository.py` | The only storage↔contract boundary. `is_ready`, `search(SearchCriteria)`, `get_details`, `get_record`, and full record→`OpportunityDetailsResponse` mapping (unknowns stay `None`). Auto-builds the DB from the prepared JSON on first use. |
| `app/tools.py` | Deterministic primitives: `search_opportunities`, `get_opportunity_details`, `evaluate_deadline`/`check_deadline` (date-only deadlines → a same-day deadline stays *uncertain*, not expired). |
| `app/agent.py` | Optional OpenRouter client (`httpx`) + `interpret_query` + `write_reason`, all bounded and validated. |
| `app/validation.py` | Evidence gate: verifies `source_ids` belong to the record, **never confirms eligibility** (kept `uncertain` with the reason as a caveat), preserves conflicts and unknowns as caveats. |
| `app/workflow.py` | LangGraph orchestration + `application_is_ready`. Resolves profile/query constraints once (incl. the city-conflict case), ranks, and maps to `DiscoveryResponse` within `workflow_timeout_seconds`. |

## Evidence-based validation & unknown handling

- Eligibility is **always `uncertain`** — the sources state requirements, never confirm a
  specific user qualifies, and the form does not collect age/study-year. The specific
  reason is surfaced as a caveat.
- Unknown cost → `null` (not free); unknown deadline/skills → `null`; source conflicts are
  kept as visible caveats and map registration to `requires_verification`.
- The four outcomes are honest: `ok` (1–3 grounded recs), `needs_info` (city conflict →
  `constraint_conflict=true`, or a skill the top match requires that the user left
  unanswered), `no_match`, and controlled `error`.

## Tests

`backend/tests/` — **30 tests, all passing**, with **no live model calls** (the LLM path is
exercised with a mocked client and mock credentials):
`test_repository.py`, `test_tools_validation.py`, `test_workflow.py` (all four outcomes +
constraint resolution), `test_api.py` (HTTP contract), `test_llm_mock.py`.

## How to run the demo

Windows PowerShell. The venv lives at the **repo root** (`Fursah-Group5\.venv`), so from
`backend\` it is `..\..\.venv\`. Using the absolute path works from anywhere:

```powershell
# 1. (optional — the API auto-builds the SQLite store on first run)
#    from fursah-starter\ :
.\.venv\Scripts\python.exe data\build_opportunities.py

# 2. Backend — from fursah-starter\backend\ :
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
#    or, unambiguous from any folder:
#    C:\Users\thuri\Desktop\Fursah-Group5\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 3. Frontend — from fursah-starter\frontend\ (second terminal):
npm run dev
```

Then open the frontend (http://localhost:5173) and `GET http://localhost:8000/docs`.

Run the tests (from `backend\`):

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests\ -q
```

### Enabling the live OpenRouter model (optional, do yourself)

The deterministic demo needs no key. To also exercise the LLM path, copy
`backend\.env.example` to `backend\.env`, set `FURSAH_MODEL_API_KEY` to your own OpenRouter
key, keep `FURSAH_MODEL_NAME` on a cost-efficient Arabic-capable model (e.g.
`google/gemini-2.0-flash-001`), and restart uvicorn. Keys stay in `.env` only — never in
source, logs or the frontend.

### Optional: Phoenix tracing (Day 4)

`pip install -r requirements-observability.txt`, set `FURSAH_PHOENIX_ENABLED=true`. The app
auto-instruments LangGraph/LangChain spans; it is a no-op when disabled.

## What works / what is optional

- **Works end-to-end:** data prep, SQLite storage, details, search, all four discovery
  outcomes, evidence validation, constraint resolution, LangGraph workflow, the full
  frontend (discovery cards + details panel), and the test suite — all keyless.
- **Optional / not required for the demo:** live OpenRouter calls (bring your own key);
  Phoenix tracing (install + enable). Fields the dataset does not contain
  (`capacity`, `required_documents_ar`, `application_steps_ar`) are correctly returned as
  `null`.
