# FURSAH

**An Arabic-first opportunity discovery and recommendation platform**  
**Backend:** FastAPI · LangGraph · SQLAlchemy · SQLite  
**Frontend:** React · TypeScript · Vite  
**Optional AI:** Qwen via OpenRouter  
**Observability:** Arize Phoenix · OpenTelemetry

FURSAH helps users discover opportunities that align with their interests and constraints. It combines structured retrieval, constraint handling, grounded recommendations, and an optional language-model reranking step. The application can run without an API key using a deterministic fallback.

> **Project status:** The implementation checklist below describes the initial Days 1–3 build, followed by the changes made during Day 4 evaluation. Day 4 results are from deterministic runs without live model calls. Counts and scores are recorded results, not guarantees for future versions.

## Contents

- [Architecture and workflow](#architecture-and-workflow)
- [Implementation checklist](#implementation-checklist)
- [Day 4: Evaluation and observability](#day-4-evaluation-and-observability)
- [Evaluation results](#evaluation-results)
- [Local development](#local-development)
- [Configuration and security](#configuration-and-security)
- [Project notes](#project-notes)

## Architecture and workflow

The discovery workflow uses LangGraph to interpret the request, retrieve candidates, assess constraints, and either request clarification, return no match, or rank eligible results.

```text
User request
    |
    v
Interpret query and resolve constraints
    |
    v
Retrieve candidates (SQLite / SQLAlchemy)
    |
    v
Assess eligibility, dates, costs, and relevance
    |
    +--> needs_info (unresolved constraints)
    +--> no_match   (no relevant matches)
    |
    v
Rank candidates (Qwen via OpenRouter, when available)
    |
    +--> deterministic fallback (no key / timeout / invalid output)
    |
    v
Validate evidence and return grounded recommendations
```

The model may reorder only opportunities retrieved from the database. Unknown costs, dates, and eligibility are not invented.

## Implementation checklist

### 1. Storage and retrieval

- [x] **SQLite persistence with SQLAlchemy:** Indexed filtering columns and a JSON copy of each prepared record preserve source evidence. The database is initialized from the prepared JSON when required.  
  **Files:** `backend/app/repository.py`, `backend/app/infrastructure/db.py`
- [x] **Constraint-based candidate search:** Filters by opportunity type, delivery mode, city, dates, and budget; excludes cancelled records. Unknown values are handled explicitly rather than silently converted into facts.  
  **Function:** `repository.search()`
- [x] **Opportunity details and source aliases:** A secondary announcement/source ID can resolve to its parent opportunity. Public response fields preserve unknown values as `null`.  
  **Function:** `repository.get_details()`

### 2. Discovery workflow (LangGraph)

- [x] **StateGraph pipeline:** Interpretation, retrieval, assessment, and ranking, with `ok`, `needs_info`, `no_match`, and error handling.  
  **File:** `backend/app/workflow.py`
- [x] **City-conflict resolution:** Conflicting profile and query cities can lead to `needs_info` without modifying the saved user profile.
- [x] **Arabic-aware query matching:** Text normalization, light stemming/prefix handling, opportunity-type detection, and city matching.
- [x] **Topic-coverage ranking:** Query-topic coverage with greater weight on titles, replacing an overly flat keyword score.
- [x] **Initial approximate-match behavior:** The original implementation could return the closest opportunities when exact matches were unavailable, with a clear caveat. **Day 4 subsequently changed this:** unrelated results now return `no_match` to improve relevance and evaluation alignment.

### 3. Grounded RAG and optional Qwen reranking

- [x] **OpenRouter integration:** Qwen can semantically rerank a retrieved candidate pool. Model-generated IDs that are not in the candidate pool are rejected.  
  **File:** `backend/app/agent.py`
- [x] **Optional query interpretation and Arabic explanation generation:** Outputs are bounded and validated against known values.
- [x] **Deterministic fallback:** Missing API credentials, timeouts, or malformed model output do not prevent discovery; the deterministic ranker is used instead.

### 4. Evidence validation and tools

- [x] **Evidence validation:** Source IDs are checked against their opportunity records. Eligibility is not fabricated, and caveats cover warnings, conflicts, deadlines, and unknown fees.  
  **File:** `backend/app/validation.py`
- [x] **Deterministic tools:** Search, details retrieval, and deadline evaluation. Date-only deadlines are handled conservatively on the deadline day.  
  **File:** `backend/app/tools.py`

### 5. API and response contracts

- [x] **Opportunity discovery:** `POST /api/v1/discover`
- [x] **Paginated browsing:** `POST /api/v1/discover/all`, an additive endpoint for showing more results.
- [x] **Opportunity details:** `GET /api/v1/opportunities/{id}`
- [x] **Health checks:** `GET /health`, `GET /ready`
- [x] **Additive response models:** Support for browsing and approximate-result metadata without breaking the existing discovery contract.
- [x] **Backend execution instrumentation:** Internal stages and model/tool activity can be traced through Phoenix. The earlier `execution_log` response field and its frontend display were removed during Day 4; technical traces belong in backend observability rather than the user interface.

**Files:** `backend/app/routes.py`, `backend/app/schemas.py`, `backend/app/main.py`

### 6. Frontend

- [x] **Show more / show all:** Fetches additional result pages, appends them, and deduplicates opportunities.  
  **Files:** `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/opportunities/SearchResults.tsx`
- [x] **Typed API responses:** TypeScript definitions cover discovery and browsing responses.  
  **File:** `frontend/src/types.ts`
- [x] **User-facing experience without technical execution logs:** The original collapsible agent-log panel was removed from the frontend during Day 4.

### 7. Tests and configuration

- [x] **Initial pytest suite:** 38 tests passed at the recorded Days 1–3 checkpoint, covering repository, tools, validation, workflow outcomes, API contracts, browsing, and mocked LLM paths.  
  **Directory:** `backend/tests/`
- [x] **Initial smoke evaluation:** Seven labeled scenarios plus cross-cutting invariants passed (7/7). This legacy check was retained as `backend/evals/smoke_eval.py` after the Day 4 materials were integrated.
- [x] **Configuration hygiene:** Environment-variable examples, dependency declarations, and ignore rules for secrets, local databases, dependencies, and caches.

## Day 4: Evaluation and observability

**Goal:** Evaluate the agent developed in Days 1–3, identify weaknesses using evidence, and make focused changes rather than rebuilding the system.

### 2.1 — Audit: What can be evaluated?

The team completed `day4/2.1-audit/audit_template.md`, recording each component's output, check type, and missing diagnostic signal.

| Check type | Meaning | Example |
| --- | --- | --- |
| **Deterministic** | Can be checked directly from inputs and outputs | Every reranked ID must belong to the retrieved candidate pool |
| **Verifiable** | Requires comparison with source records or labeled evaluation cases | Retrieved opportunities match the expected relevant sources |
| **Subjective** | Requires a quality judgment or rubric | The clarity and usefulness of an Arabic explanation |

Missing signals identified in the audit informed the custom spans added in the next stage.

### 2.2 — Instrumentation: Phoenix tracing

The workflow uses LangGraph, while direct model requests are sent through `httpx`. LangChain instrumentation alone does not capture every custom model/tool operation, so manual spans supplement the framework traces.

| Span | Location | Recorded information |
| --- | --- | --- |
| `workflow.discover` | Discovery entry points | Request ID and fixed evaluation time; parent span for a search |
| `llm.<purpose>` | `agent.LlmClient.complete` | Model purpose, inputs/outputs, token information where available, and calling operation |
| `tool.search_opportunities` | Retrieval node | Search arguments, candidate opportunity IDs, and source IDs |
| `assess.filter` | Assessment node | Excluded sources and reasons, match/approximate counts, and outcome |
| `rank.rerank` | Ranking node | Deterministic ordering, model ordering, and whether the model was used |

Instrumentation is optional and designed to be inert when Phoenix is disabled. A no-key test search confirmed that the custom spans appeared under a single workflow trace.

### 2.3 — Component graders

The official Day 4 evaluation uses `backend/evals/run_eval.py`, `backend/evals/graders.py`, and `backend/evals/dev_cases.jsonl` (24 development cases). The team left the provided `run_eval.py` unchanged.

| Grader | Purpose |
| --- | --- |
| `grade_status` | Compare actual and expected workflow status |
| `grade_search_recall` | Check whether retrieval found at least one acceptable source, using retrieval trace data |
| `grade_recommendations` | Assess recommendations against acceptable, excluded, and uncertain source labels |
| `grade_no_excluded` | Check that excluded sources are not recommended |
| `grade_rerank_grounded` | Ensure model reranking uses only IDs from the retrieved pool, when model reranking is active |

The team also added `backend/evals/team_cases.jsonl`, including a city-conflict case expected to return `needs_info`; that case passed in the reported run.

### 2.4 — Diagnosis and targeted fixes

The baseline run reported **16/24 status matches (0.67)**. The traces revealed several recurring failure patterns:

| Observed problem | Diagnosis | Change |
| --- | --- | --- |
| `no_match` cases returned `ok` | Approximate-match behavior surfaced off-topic opportunities | Return `no_match` when no meaningful topic match exists; focus matching on titles, topics, and tags |
| A case expected `ok` but returned `needs_info` | An extra skills clarification conflicted with the evaluation expectation | Remove the skills-question branch while keeping eligibility caveats |
| Relevant sources were missing from retrieval | The candidate cap of 60 truncated the pool | Raise the retrieval limit to 500 |
| Unknown-cost opportunities appeared in budget-constrained results | Missing fees could not be confirmed to fit the budget | Exclude unknown-fee records when a budget is explicitly provided |

**Product trade-off:** Remote opportunities remain visible despite a city constraint. This was retained as a product choice, although it reduces agreement with some evaluation exclusions.

## Evaluation results

### Day 4 baseline versus after targeted fixes

| Metric | Baseline | After fixes | Interpretation |
| --- | ---: | ---: | --- |
| `e2e.status` | 0.67 | **0.92** | Better alignment with expected workflow outcomes |
| `search.recall` | 0.50 | **0.94** | More acceptable sources retrieved |
| `e2e.recommendations` | 0.24 | **0.57** | Improved recommendation correctness |
| `e2e.no_excluded` | 0.67 | **0.58** | Declined, partly due to the decision to keep remote opportunities visible |

These results were measured **without live LLM calls**, using the deterministic fallback. They should not be presented as Qwen-enabled evaluation scores.

**Remaining issues:** Status mismatches in `DEV-21` and `DEV-23`, recall in `DEV-07`, and recommendation discrepancies related to city, date, and type constraints. A perfect score was not required.

### Running the official evaluation

From `fursah-starter/backend`:

```powershell
python -m evals.run_eval --label baseline
```

To compare runs, use distinct labels and retain the resulting reports. If OpenRouter is configured, evaluation may make **paid model calls**; check your configuration and budget first.

The original seven-case check is available separately:

```powershell
python -m evals.smoke_eval
```

## Local development

### Prerequisites

- Python with a project virtual environment
- Node.js and npm
- Optional OpenRouter API key for Qwen reranking
- Optional Phoenix packages for tracing

### Backend

From the repository root:

```powershell
cd fursah-starter/backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API documentation: <http://127.0.0.1:8000/docs>  
Health endpoint: <http://127.0.0.1:8000/health>

### Frontend

In a separate terminal, from the repository root:

```powershell
cd fursah-starter/frontend
npm install
npm run dev
```

The frontend typically runs at <http://localhost:5173>; use the address shown by Vite.

### Optional Phoenix tracing

Install the observability dependencies from `fursah-starter/backend`:

```powershell
python -m pip install -r requirements-observability.txt
phoenix serve
```

Phoenix UI: <http://localhost:6006>

Set the following in your **local, uncommitted** `backend/.env`:

```dotenv
FURSAH_PHOENIX_ENABLED=true
FURSAH_PHOENIX_INSTRUMENT=langchain
FURSAH_EVALUATION_TIME=2026-10-18T12:00:00+03:00
```

The fixed timestamp is for the **Day 4 classroom evaluation dataset**. Clear `FURSAH_EVALUATION_TIME` for normal, real-time application use. Restart the backend after changing environment settings.

## Configuration and security

- The application works **without an OpenRouter key** using deterministic ranking.
- For Qwen reranking, configure the appropriate OpenRouter environment variables using `backend/.env.example` as a guide. Do not put actual credentials in documentation or source control.
- Keep `backend/.env`, API keys, local database files containing user data, `node_modules`, virtual environments, and caches out of Git.
- Do not expose raw prompts, credentials, or technical trace payloads in the public frontend or API responses.
- Phoenix traces are intended for developer-side diagnosis; review logging and data-retention settings before using real user data.

## Project notes

- **Initial Days 1–3 checkpoint:** Branch `feature`, commit `d2e620d`; 38 passing tests and 7/7 smoke evaluation cases were reported at that checkpoint.
- **Day 4:** Official 24-case evaluation and component-level grading were added, along with Phoenix spans and targeted improvements.
- **Documentation scope:** This README records the supplied implementation and evaluation summary. It does not independently verify the current branch, latest test run, or deployment status.

---

**FURSAH — Team 5**
