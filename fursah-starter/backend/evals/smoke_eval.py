"""Quick keyless smoke check for the FURSAH discovery workflow.

NOTE: this is our earlier hand-made harness, kept as a fast local smoke test. The official
Day 4 evaluation is `evals/run_eval.py` (24 dev_cases + graders + Phoenix) — use that for
grading. This one needs no model, no Phoenix, and no cases file.

Runs a few labeled scenarios through the real workflow (keyless / deterministic) and scores:

  1. Per-case outcome: did the agent reach the expected status (ok / no_match / needs_info)
     with the expected shape (approximate flag, constraint_conflict, a required type, ...)?
  2. Cross-cutting invariants that must hold on EVERY recommendation, regardless of case:
       - grounding:   every source_id is a real source ID from the dataset
       - eligibility: never "confirmed" (the data never establishes it)
       - freshness:   no recommendation whose deadline has already passed

Run from fursah-starter/backend/:
    ..\\..\\.venv\\Scripts\\python.exe -m evals.run_eval
A JSON report is written next to this file.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.config import get_settings
from app.infrastructure.data_package import DatasetLoader
from app.infrastructure.dependencies import AppDependencies
from app.infrastructure.tracing import Tracer
from app.repository import OpportunityRepository
from app.schemas import DiscoveryRequest, SearchConstraints, UserProfile

EVAL_TIME = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))

# Each case: a request plus what we expect. Optional expectations default to "don't check".
CASES = [
    {
        "name": "exact_workshop_riyadh",
        "query": "ورشة في تحليل البيانات في الرياض",
        "expect": {"status": "ok", "approximate": False, "type_in_top": "workshop"},
    },
    {
        "name": "ok_online_present_ideas",
        "query": "عرض الأفكار أمام الجمهور عن بعد",
        "expect": {"status": "ok", "min_recs": 1},
    },
    {
        "name": "similar_fallback_no_exact",
        "query": "فرصة في الغوص والرياضات المائية",
        "expect": {"status": "ok", "approximate": True, "min_recs": 1},
    },
    {
        "name": "no_match_impossible",
        "query": "ورشة",
        "constraints": {"opportunity_types": ["internship"], "delivery_modes": ["online"],
                        "location_preference": ["نجران"], "max_budget_sar": 0},
        "expect": {"status": "no_match"},
    },
    {
        "name": "needs_info_city_conflict",
        "query": "أريد فرصة في جدة",
        "profile": {"city": "الرياض"},
        "expect": {"status": "needs_info", "constraint_conflict": True},
    },
    {
        "name": "city_conflict_resolved",
        "query": "أريد فرصة في جدة",
        "profile": {"city": "الرياض"},
        "constraint_resolution": "query",
        "expect": {"status": "ok"},
    },
    {
        "name": "volunteering_community",
        "query": "فرصة تطوع في خدمة المجتمع",
        "expect": {"status": "ok", "min_recs": 1},
    },
]


def _build_deps() -> tuple[AppDependencies, set[str]]:
    settings = get_settings()
    bridge = DatasetLoader(settings)
    repo = OpportunityRepository(bridge)
    deps = AppDependencies(settings=settings, bridge=bridge, repository=repo,
                           model_config=None, tracer=Tracer(), evaluation_time=EVAL_TIME)
    valid_source_ids = {sid for r in repo._load_records() for sid in r.get("source_ids", [])}
    return deps, valid_source_ids


def _request(case: dict) -> DiscoveryRequest:
    return DiscoveryRequest(
        request_id=case["name"],
        query=case["query"],
        profile=UserProfile(**case.get("profile", {})),
        constraints=SearchConstraints(**case.get("constraints", {})),
        constraint_resolution=case.get("constraint_resolution"),
    )


def _check_case(response, expect: dict) -> list[str]:
    """Return a list of failure messages for a single case (empty = pass)."""
    fails = []
    if response.status.value != expect["status"]:
        fails.append(f"status {response.status.value} != {expect['status']}")
    if "approximate" in expect and response.approximate != expect["approximate"]:
        fails.append(f"approximate {response.approximate} != {expect['approximate']}")
    if "constraint_conflict" in expect and response.constraint_conflict != expect["constraint_conflict"]:
        fails.append(f"constraint_conflict {response.constraint_conflict} != {expect['constraint_conflict']}")
    if "min_recs" in expect and len(response.recommendations) < expect["min_recs"]:
        fails.append(f"recs {len(response.recommendations)} < {expect['min_recs']}")
    if "type_in_top" in expect:
        top = response.recommendations[0] if response.recommendations else None
        if not top or top.opportunity_type != expect["type_in_top"]:
            got = top.opportunity_type if top else "none"
            fails.append(f"top type {got} != {expect['type_in_top']}")
    return fails


def _check_invariants(response, valid_ids: set[str]) -> dict[str, bool]:
    """Invariants that must hold on every recommendation of this response."""
    recs = response.recommendations
    eval_date: date = EVAL_TIME.date()

    def not_expired(rec) -> bool:
        if not rec.deadline:
            return True
        try:
            return date.fromisoformat(rec.deadline[:10]) >= eval_date
        except ValueError:
            return True

    return {
        "grounding": all(set(r.source_ids) <= valid_ids for r in recs),
        "eligibility_uncertain": all(r.eligibility_status.value == "uncertain" for r in recs),
        "no_expired": all(not_expired(r) for r in recs),
    }


async def main() -> int:
    from app.workflow import discover

    deps, valid_ids = _build_deps()
    results = []
    invariant_totals = {"grounding": 0, "eligibility_uncertain": 0, "no_expired": 0}
    cases_with_recs = 0
    passed = 0

    for case in CASES:
        response = await discover(_request(case), deps)
        case_fails = _check_case(response, case["expect"])
        invariants = _check_invariants(response, valid_ids)
        if response.recommendations:
            cases_with_recs += 1
        for key, ok in invariants.items():
            invariant_totals[key] += int(ok)
        ok = not case_fails and all(invariants.values())
        passed += int(ok)
        results.append({
            "name": case["name"], "pass": ok, "status": response.status.value,
            "recs": len(response.recommendations), "approximate": response.approximate,
            "failures": case_fails,
            "invariants": {k: v for k, v in invariants.items() if not v} or "all ok",
        })

    print("=" * 64)
    print("FURSAH agent evaluation  (keyless / deterministic)")
    print("=" * 64)
    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f"  [{mark}] {r['name']:<28} status={r['status']:<10} recs={r['recs']}")
        if r["failures"]:
            print(f"         case: {'; '.join(r['failures'])}")
        if r["invariants"] != "all ok":
            print(f"         invariants broken: {r['invariants']}")
    print("-" * 64)
    print(f"  cases passed: {passed}/{len(CASES)}")
    n = len(CASES)
    for key, total in invariant_totals.items():
        print(f"  {key:<22} {total}/{n} responses")
    print("=" * 64)

    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "eval_time": EVAL_TIME.isoformat(),
        "cases_passed": passed, "cases_total": n,
        "invariants": invariant_totals, "results": results,
    }
    out = Path(__file__).with_name("report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {out}")
    return 0 if passed == n else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
