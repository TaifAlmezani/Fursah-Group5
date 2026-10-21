# FURSAH — Demo Script (verified test cases)

Each case below is verified against the running backend. Type the **Query** into the search
box (and set the Profile/Constraints noted) at http://localhost:5173.

| # | What it shows | Query (copy) | Setup | Expected result |
|---|---|---|---|---|
| 1 | **OK — one precise result** (relevance floor, no padding) | `ورشة في تحليل البيانات في الرياض` | — | `ok`, **1** card: SRC‑0738 «لوحات Power BI خطوة بخطوة» (workshop, Riyadh, ~72%). Filters: النوع: ورشة، المدينة: الرياض |
| 2 | **OK — several results** | `عرض الأفكار أمام الجمهور عن بعد` | — | `ok`, **3** cards (SRC‑0024 88%, SRC‑0073 88%, …) |
| 3a | **No match — nothing relevant** | `فرصة في الرياضات المائية` | — | `no_match`. (Also shows the city fix: «الرياضات» no longer mistaken for «الرياض».) |
| 3b | **No match — over‑constrained** | `ورشة` | Constraints: Type=تدريب، Delivery=عن بعد، City=نجران، Max budget=0 | `no_match`; filters list every constraint applied |
| 4 | **Needs info — city conflict** (the clarify path) | `أريد فرصة في جدة` | Profile → City = `الرياض` | `needs_info`, "تعارض بين مدينة ملفك ومدينة طلبك"; `constraint_conflict=true`. Set a city / resolution → `ok` with Jeddah results |
| 5 | **Expired handling** | `دورة في صياغة سؤال بحثي عن بعد` | — | `ok`; recommends an **actionable** course (SRC‑0434). The expired SRC‑0013 (deadline 2026‑10‑14) is silently excluded. Cards show the deadline + "وقت الإغلاق غير محدد" |
| 6 | **Many announcements merged** | `عرض الأفكار أمام الجمهور عن بعد` → open **عرض التفاصيل** on SRC‑0024 | — | Details show `source_ids = [SRC‑0024, SRC‑0025]` — two announcements merged into one opportunity |

## Case 6b — merged announcements that CONFLICT (shown via the details API)

The clearest conflict example (SRC‑0526) is past its deadline, so it is not *recommended* — but
its details still expose the merge and the preserved conflicts. Open in the browser:

```
http://localhost:8000/api/v1/opportunities/SRC-0527
```

This returns:
- `canonical_id: "SRC-0526"` — asking for the **secondary** announcement ID (SRC‑0527) resolves
  to its parent opportunity (source‑alias resolution),
- `source_ids: ["SRC-0526", "SRC-0527"]` — both announcements,
- `data_warnings` containing the **preserved conflicts**: fee «50 vs 135» and sessions «5 vs 4»,
  and `application_status` shown rather than a guessed winner.

Other IDs to open directly: `/api/v1/opportunities/SRC-0001`, or any ID from a result card.

## Things to point out during the demo

- **Eligibility is always "غير مؤكدة" (uncertain).** The sources state requirements, never confirm
  a specific person qualifies, and the form doesn't collect age/study‑year — so the app never
  invents a confirmation. The reason appears as a caveat ("ملاحظات مهمة").
- **Unknowns are shown, not guessed:** unknown fee → "الرسوم غير مذكورة؛ … ليست بالضرورة مجانية";
  unknown deadline/skills → shown as unknown.
- **Interpreted filters** ("فهمنا بحثك بهذه القيود") echo what the system understood from free text
  — including a city or type detected from the query.
- The **skills clarification** (needs_info on `profile.skills`) fires when a skill‑gated opportunity
  is the *only* best match; in this dataset a non‑gated alternative usually exists, so the app
  recommends that instead — which is the desired behavior.

## Reset the backend if needed

From `fursah-starter\backend\` (single process, no `--reload` to avoid orphaned workers):

```powershell
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
