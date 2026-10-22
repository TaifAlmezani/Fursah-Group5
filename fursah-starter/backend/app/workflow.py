# Discovery orchestration (LangGraph) — the API integration entry point.
#
# The graph is a small, explicit pipeline:
#
#   interpret -> retrieve -> assess --(conditional)--> { needs_info | no_match | rank } -> END
#
# Why LangGraph here: it gives one declarative place where the branch between a grounded
# answer, a clarification request and "no match" lives, with each stage traced. The stages
# themselves are deterministic and source-grounded — retrieval, ranking, eligibility and the
# source IDs are plain code over the repository, because the model cannot reach the dataset.
# The LLM (OpenRouter) is optional and bounded: it only enriches query understanding and
# phrases a reason for an already-selected recommendation, and the whole thing runs with no
# API key via deterministic fallbacks, so the demo is reliable.
from __future__ import annotations

import asyncio
import re
import time
import warnings
from datetime import datetime
from typing import Any, TypedDict

# LangGraph imports a serializer that emits a cosmetic pending-deprecation warning; silence it
# so the trace output stays clean. It does not affect how we use the graph.
warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="langgraph.checkpoint.*"
)
try:  # LangChain uses its own warning subclass for the same message.
    from langchain_core._api import LangChainPendingDeprecationWarning

    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
except Exception:  # pragma: no cover - best-effort cosmetic cleanup only
    pass

from langgraph.graph import END, START, StateGraph

from .agent import build_llm_client, interpret_query, rerank, write_reason
from .infrastructure.dependencies import AppDependencies
from .repository import SearchCriteria
from .schemas import (
    BrowseResponse,
    DiscoveryRequest,
    DiscoveryResponse,
    DiscoveryStatus,
    MatchFactor,
    MatchKind,
    Recommendation,
    UserProfile,
    SearchConstraints,
)
from .tools import (
    DEADLINE_EXPIRED,
    DEADLINE_SAME_DAY,
    DEADLINE_UNKNOWN,
    evaluate_deadline,
    search_opportunities,
)
from .validation import to_recommendation

# --------------------------------------------------------------------------
# Vocabulary (kept in sync with the frontend form choices and labels)
# --------------------------------------------------------------------------
CITIES = [
    "الرياض", "جدة", "مكة المكرمة", "المدينة المنورة", "الدمام", "الخبر", "الظهران",
    "الأحساء", "القطيف", "الجبيل", "الطائف", "تبوك", "بريدة", "عنيزة", "حائل", "أبها",
    "خميس مشيط", "جازان", "نجران", "الباحة", "سكاكا", "عرعر", "ينبع", "حفر الباطن",
]
CITY_ALIASES = {"مكة": "مكة المكرمة", "المدينة": "المدينة المنورة"}
TYPE_AR = {
    "workshop": "ورشة", "course": "دورة", "internship": "تدريب",
    "competition": "مسابقة", "volunteering": "تطوع", "event": "فعالية",
}
MODE_AR = {"in_person": "حضوري", "online": "عن بعد", "hybrid": "مدمج"}

# Query words that name a TYPE of opportunity (stem form). When the user types one and has
# not set an explicit type constraint, we filter by it — "ورشة" should mean workshops.
QUERY_TYPE_WORDS = {
    "ورشه": "workshop", "دوره": "course", "تدريب": "internship",
    "مسابقه": "competition", "منافسه": "competition", "تحدي": "competition",
    "تطوع": "volunteering", "فعاليه": "event", "لقاء": "event", "امسيه": "event",
}
# Prefixes carrying the definite article or doubled-lam. Stripping them lets «البيانات»,
# «للبيانات» and «بالرياض» match «بيانات» / «رياض». Bare single prepositions are NOT stripped,
# so a real word like «بيانات» is never mangled into «يانات».
_PREFIXES = ("وال", "فال", "بال", "كال", "لل", "ال")

_STOPWORDS = {
    "عن", "في", "من", "الى", "إلى", "على", "مع", "لي", "هل", "ما", "هذا", "هذه",
    "أبحث", "ابحث", "أريد", "اريد", "ودي", "عايز", "يكون", "أي", "او", "أو", "و",
    # Delivery-mode words are not topics (prevents «عن بعد» matching any online opportunity).
    "بعد", "حضوري", "حضوريا", "اونلاين", "عبر", "الانترنت", "بُعد",
}
_TASHKEEL = re.compile(r"[ؗ-ًؚ-ْٰـ]")
_TOKEN = re.compile(r"[A-Za-z؀-ۿ][A-Za-z0-9؀-ۿ]+")


def _norm(text: str) -> str:
    """Light Arabic normalization so matching is robust to alef/ya/ta-marbuta variants."""
    text = (text or "").lower().strip()
    text = _TASHKEEL.sub("", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"),
                     ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(src, dst)
    return text


def _strip_prefix(token: str) -> str:
    for prefix in _PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 3:
            return token[len(prefix):]
    return token


def _stems(text: str) -> set[str]:
    """Normalized, prefix-stripped stems used for topic matching (set form)."""
    return {
        _strip_prefix(t)
        for t in _TOKEN.findall(_norm(text))
        if t not in _STOPWORDS and len(t) >= 2
    }


def _tokens(text: str) -> list[str]:
    return [
        _strip_prefix(t)
        for t in _TOKEN.findall(_norm(text))
        if t not in _STOPWORDS and len(t) >= 2
    ]


# Structural stems describe the KIND of opportunity, not its topic, so they are excluded
# from the content-relevance test (otherwise "ورشة" alone would match any workshop).
_STRUCTURAL_STEMS = {
    "ورشه", "دوره", "تدريب", "مسابقه", "منافسه", "تحدي", "تطوع", "فعاليه", "لقاء",
    "امسيه", "عمل", "فرصه", "فرص", "برنامج", "نشاط", "جلسه",
}
# Every stem that appears in a known city name, excluded from content terms.
_CITY_STEMS = set().union(*(_stems(c) for c in CITIES), *(_stems(a) for a in CITY_ALIASES))


def _content_terms(query: str) -> list[str]:
    """Topic-bearing stems from the query (city names and type/filler words removed)."""
    return sorted(_stems(query) - _STRUCTURAL_STEMS - _CITY_STEMS)


def _detect_query_types(query: str) -> list[str]:
    stems = _stems(query)
    return sorted({kind for stem, kind in QUERY_TYPE_WORDS.items() if stem in stems})


def _record_stems(record: dict[str, Any]) -> set[str]:
    """All topic stems a record exposes: title, topic, description, organizer, topics."""
    stems = _stems(
        " ".join(str(record.get(k) or "") for k in ("title", "topic", "description", "organizer"))
    )
    for topic in record.get("topics") or []:
        stems |= _stems(str(topic))
    return stems


def _detect_city(query: str) -> str | None:
    """Find a known city named in the query by matching whole stems, not substrings.

    Stem matching avoids false hits like «الرياضات» (sports) matching the city «الرياض».
    """
    stems = _stems(query)
    for alias, full in CITY_ALIASES.items():
        alias_stems = _stems(alias)
        if alias_stems and alias_stems <= stems and not _stems(full) <= stems:
            return full
    for city in CITIES:
        city_stems = _stems(city)
        if city_stems and city_stems <= stems:
            return city
    return None


# --------------------------------------------------------------------------
# LangGraph state
# --------------------------------------------------------------------------
class DiscoveryState(TypedDict, total=False):
    deps: AppDependencies
    request: DiscoveryRequest
    evaluation_time: datetime
    llm: Any

    criteria: SearchCriteria
    content_terms: list[str]            # topic stems that drive the relevance floor
    interpreted_filters: list[str]
    conflict: dict[str, str] | None     # unresolved city conflict details
    candidates: list[dict[str, Any]]
    ranked_all: list[tuple[dict[str, Any], float, bool]]  # (record, score, is_approximate)
    approximate: bool                   # True when no exact match: closest shown instead
    outcome: str                        # 'conflict' | 'no_match' | 'skills' | 'rank'
    skill_gap: list[str]
    log: list[dict[str, Any]]           # agent execution log (stages, tools, model calls)
    all_recommendations: list[Recommendation]  # full ranking for browse / show-more
    response: DiscoveryResponse


# Message + per-card caveat used when no exact match exists and we fall back to the closest.
_APPROX_MESSAGE = "لا توجد مطابقة تامة لطلبك؛ هذه أقرب الفرص المتاحة مرتبة حسب الأولوية."
_APPROX_CAVEAT = "هذه الفرصة أقرب خيار متاح وليست مطابقة تامة لطلبك."


def _append_log(
    state: DiscoveryState, step: str, component: str, detail: str, started: float
) -> list[dict[str, Any]]:
    """Return the running agent log with one step appended (timed from `started`)."""
    entries = list(state.get("log", []))
    entries.append({
        "seq": len(entries) + 1,
        "step": step,
        "component": component,
        "detail": detail,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    })
    return entries


# --------------------------------------------------------------------------
# Constraint resolution + interpretation
# --------------------------------------------------------------------------
def _resolve_locations(
    request: DiscoveryRequest,
) -> tuple[list[str], dict[str, str] | None]:
    """Resolve the effective city filter once; report an unresolved profile/query conflict.

    A temporary override (constraint_resolution) applies to THIS request only and never
    changes the saved profile. An explicit location_preference is an answered constraint and
    always wins, so it cannot be in conflict.
    """
    profile = request.profile
    constraints = request.constraints

    explicit = [loc.strip() for loc in (constraints.location_preference or []) if loc.strip()]
    if explicit:
        return explicit, None

    query_city = _detect_city(request.query)
    profile_city = (profile.city or "").strip() or None

    if query_city and profile_city and query_city != profile_city:
        if request.constraint_resolution == "query":
            return [query_city], None
        if request.constraint_resolution == "profile":
            return [profile_city], None
        return [], {"profile_city": profile_city, "query_city": query_city}

    if query_city:
        return [query_city], None
    if profile_city:
        return [profile_city], None
    return [], None


def _build_interpreted_filters(criteria: SearchCriteria) -> list[str]:
    filters: list[str] = []
    if criteria.opportunity_types:
        filters.append("النوع: " + "، ".join(TYPE_AR.get(t, t) for t in criteria.opportunity_types))
    if criteria.delivery_modes:
        filters.append("طريقة الحضور: " + "، ".join(MODE_AR.get(m, m) for m in criteria.delivery_modes))
    if criteria.locations:
        filters.append("المدينة: " + "، ".join(criteria.locations))
    if criteria.available_from:
        filters.append(f"متاح من: {criteria.available_from.isoformat()}")
    if criteria.available_to:
        filters.append(f"متاح حتى: {criteria.available_to.isoformat()}")
    if criteria.max_duration_days is not None:
        filters.append(f"أقصى مدة: {criteria.max_duration_days} يوم")
    if criteria.max_budget_sar is not None:
        filters.append(f"أقصى رسوم: {criteria.max_budget_sar:g} ريال")
    return filters


async def interpret_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    request = state["request"]
    profile = request.profile
    constraints = request.constraints
    llm_used = False

    locations, conflict = _resolve_locations(request)

    # Query keywords + profile interests as stems for topic matching.
    terms = _tokens(request.query)
    for interest in profile.interests:
        terms += list(_stems(interest))

    # Topic-bearing content terms (city/type/filler removed) drive the relevance floor.
    content = _content_terms(request.query)

    types = list(constraints.opportunity_types)
    modes = list(constraints.delivery_modes)
    # A type named in the query (e.g. «ورشة») filters when none was set explicitly.
    if not types:
        types = _detect_query_types(request.query)

    # Optional LLM enrichment — SOFT keywords only. The model must never add hard filters
    # (delivery mode, type, city): inferring e.g. "in-person" from «في الرياض» wrongly drops
    # online matches. Hard filters come only from the form + deterministic detection above.
    llm = state.get("llm")
    if llm is not None:
        try:
            hints = await interpret_query(llm, request.query, profile, constraints)
            llm_used = bool(hints.get("keywords"))
        except Exception:
            hints = {}
        for keyword in hints.get("keywords", []):
            stems = _stems(keyword)
            terms += list(stems)
            content += [s for s in stems if s not in _STRUCTURAL_STEMS and s not in _CITY_STEMS]

    criteria = SearchCriteria(
        text_terms=sorted({t for t in terms if t}),
        opportunity_types=types,
        delivery_modes=modes,
        locations=locations,
        available_from=constraints.available_from,
        available_to=constraints.available_to,
        max_duration_days=constraints.max_duration_days,
        max_budget_sar=constraints.max_budget_sar,
    )
    detail = (
        f"terms={len(criteria.text_terms)}, types={criteria.opportunity_types or '-'}, "
        f"modes={criteria.delivery_modes or '-'}, cities={criteria.locations or '-'}, "
        f"llm={'hints' if llm_used else ('fallback' if llm is not None else 'off')}"
    )
    return {
        "criteria": criteria,
        "conflict": conflict,
        "content_terms": sorted(set(content)),
        "interpreted_filters": _build_interpreted_filters(criteria),
        "log": _append_log(state, "interpret", "agent", detail, started),
    }


def retrieve_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    # A city conflict is answered by the user, not by retrieval, so skip the query.
    if state.get("conflict"):
        return {
            "candidates": [],
            "log": _append_log(state, "tool.search", "repository", "skipped (city conflict)", started),
        }
    records = search_opportunities(state["criteria"], state["deps"].repository)
    # Only present records that have a title (the contract needs one).
    records = [r for r in records if (r.get("title") or "").strip()]
    return {
        "candidates": records,
        "log": _append_log(state, "tool.search", "repository", f"{len(records)} candidates", started),
    }


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------
def _score(record: dict[str, Any], content_terms, profile: UserProfile) -> float:
    """Relevance 0–100, driven by how much of the query's TOPIC a record covers.

    Topic words carry the match (not structural words like «ورشة» or the city), and a hit in
    the title/topic counts more than one buried in the description. A candidate that matches no
    topic word scores low (interest/constraints only), so exact matches always rank above the
    approximate "closest" ones and the percentage reflects real fit.
    """
    content = set(content_terms)
    title = _stems(f"{record.get('title') or ''} {record.get('topic') or ''}")
    body = _record_stems(record)
    interests = set().union(*(_stems(i) for i in profile.interests)) if profile.interests else set()
    topics = set().union(*(_stems(t) for t in record.get("topics") or [])) if record.get("topics") else set()

    interest_points = min(18.0, 9.0 * len(interests & topics))
    if content:
        body_hit = content & body
        if body_hit:
            coverage = len(body_hit) / len(content)          # share of query topic words found
            title_coverage = len(content & title) / len(content)
            topic_points = 48.0 + 32.0 * coverage + 20.0 * title_coverage  # 48..100
        else:
            topic_points = 22.0  # no topic word matched: an approximate / interest-only candidate
    else:
        topic_points = 40.0      # query carried no topic words: lean on interests + constraints

    score = topic_points + interest_points
    reg = record.get("registration_statement")
    score += 3.0 if reg == "open" else (-3.0 if reg == "not_yet_open" else (-8.0 if reg == "closed" else 0.0))
    if record.get("conflicts"):
        score -= 4.0
    return round(max(5.0, min(100.0, score)), 1)


def _actionable(record: dict[str, Any], evaluation_time: datetime) -> bool:
    """Exclude what the user cannot act on: expired deadlines and closed registration."""
    if evaluate_deadline(record, evaluation_time) == DEADLINE_EXPIRED:
        return False
    if record.get("registration_statement") in {"closed", "cancelled"}:
        return False
    return True


def assess_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    if state.get("conflict"):
        return {"outcome": "conflict",
                "log": _append_log(state, "assess", "agent", "city conflict -> needs_info", started)}

    request = state["request"]
    evaluation_time = state["evaluation_time"]
    actionable = [r for r in state["candidates"] if _actionable(r, evaluation_time)]
    if not actionable:
        return {"outcome": "no_match",
                "log": _append_log(state, "assess", "agent", "no actionable candidates", started)}

    # Exact matches satisfy the topic relevance floor; the rest share the SAME hard constraints
    # (city, type, budget) and become the "closest" fallback for show-more / no exact match.
    content = set(state.get("content_terms") or [])
    exact = actionable
    if content:
        interests = (
            set().union(*(_stems(i) for i in request.profile.interests))
            if request.profile.interests else set()
        )

        def _relevant(record: dict[str, Any]) -> bool:
            if content & _record_stems(record):
                return True
            topics = (
                set().union(*(_stems(t) for t in record.get("topics") or []))
                if record.get("topics") else set()
            )
            return bool(interests & topics)

        exact = [r for r in actionable if _relevant(r)]

    def _rank(records: list[dict[str, Any]]):
        return sorted(
            ((r, _score(r, content, request.profile)) for r in records),
            key=lambda pair: pair[1], reverse=True,
        )

    approximate = not exact
    if exact:
        # Exact matches first (priority order), then the closest others for "show all".
        exact_ids = {r.get("opportunity_id") for r in exact}
        rest = [r for r in actionable if r.get("opportunity_id") not in exact_ids]
        ordered = [(r, s, False) for r, s in _rank(exact)] + [(r, s, True) for r, s in _rank(rest)]
    else:
        # No exact match: show the closest actionable opportunities, all flagged approximate.
        ordered = [(r, s, True) for r, s in _rank(actionable)]

    # Decision-relevant skill gap applies only when there IS an exact best match that states a
    # required skill the user left unanswered (null). In fallback mode we don't ask — we show.
    if not approximate:
        top_record = ordered[0][0]
        required = top_record.get("required_skills")
        if request.profile.skills is None and isinstance(required, list) and required:
            return {"outcome": "skills", "ranked_all": ordered,
                    "skill_gap": [str(s) for s in required],
                    "log": _append_log(state, "assess", "agent",
                                       f"exact={len(exact)}, skill gap -> needs_info", started)}

    detail = (f"no exact match -> {len(ordered)} closest shown"
              if approximate else f"exact={len(exact)}, closest-extra={len(ordered) - len(exact)}")
    return {"outcome": "rank", "ranked_all": ordered, "approximate": approximate,
            "log": _append_log(state, "assess", "agent", detail, started)}


def _route(state: DiscoveryState) -> str:
    return {
        "conflict": "needs_info",
        "skills": "needs_info",
        "no_match": "no_match",
    }.get(state.get("outcome", "rank"), "rank")


# --------------------------------------------------------------------------
# Terminal nodes (build the public response)
# --------------------------------------------------------------------------
def _base(state: DiscoveryState, **kwargs) -> dict[str, Any]:
    # The agent log stays in state["log"] and goes to the BACKEND tracer (see discover());
    # it is deliberately NOT placed on the public response. Users see messages, not traces.
    return {
        "request_id": state["request"].request_id,
        "interpreted_filters": state.get("interpreted_filters", []),
        **kwargs,
    }


def needs_info_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    request = state["request"]
    if state.get("outcome") == "conflict":
        conflict = state["conflict"] or {}
        message = "تعارض بين مدينة ملفك ومدينة طلبك؛ أي مدينة تقصد؟"
        missing_fields = ["constraints.location_preference"]
        explanations = [
            f"مدينة الملف: {conflict.get('profile_city', '')}، "
            f"مدينة الطلب: {conflict.get('query_city', '')}. "
            "حدّد المدينة المطلوبة أو اختر مصدر الحسم (الملف أو الطلب)."
        ]
        constraint_conflict = True
    else:  # skills
        skills = "، ".join(state.get("skill_gap", []))
        message = "تتطلب الفرصة الأنسب مهارات محددة؛ هل لديك هذه المهارات؟"
        missing_fields = ["profile.skills"]
        explanations = [
            f"تطلب الفرصة الأعلى مطابقةً: {skills}. "
            "لم تُحدَّد مهاراتك بعد، والأهلية تعتمد عليها."
        ]
        constraint_conflict = False

    kind = "conflict" if state.get("outcome") == "conflict" else "skills"
    log = _append_log(state, "respond", "workflow", f"needs_info ({kind})", started)
    response = DiscoveryResponse(
        **_base({**state, "log": log}),
        status=DiscoveryStatus.NEEDS_INFO,
        message=message,
        recommendations=[],
        missing_fields=missing_fields,
        missing_explanations=explanations,
        constraint_conflict=constraint_conflict,
    )
    return {"response": response, "all_recommendations": [], "log": log}


def no_match_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    log = _append_log(state, "respond", "workflow", "no_match", started)
    response = DiscoveryResponse(
        **_base({**state, "log": log}),
        status=DiscoveryStatus.NO_MATCH,
        message="لم نجد فرصة تدعم الأدلة مطابقتها لطلبك ضمن القيود المحددة.",
    )
    return {"response": response, "all_recommendations": [], "log": log}


def _fallback_reason(record: dict[str, Any]) -> str:
    """Grounded Arabic reason built only from stated facts (used with or without the LLM)."""
    type_label = TYPE_AR.get(record.get("opportunity_type"), "فرصة")
    title = record.get("title") or ""
    where = ""
    if record.get("delivery_mode") == "online":
        where = " عن بُعد"
    elif record.get("location"):
        where = f" في {record['location']}"
    topic = record.get("topic")
    tail = f" وتتناول {topic}" if topic else ""
    return f"{type_label} «{title}»{where}{tail}، وتطابق كلمات طلبك واهتماماتك."


def explain_match(
    record: dict[str, Any],
    criteria: SearchCriteria,
    content: set[str],
    profile: UserProfile,
    *,
    is_approx: bool,
    evaluation_time: datetime,
    application_status: str | None,
) -> list[MatchFactor]:
    """Auditable breakdown of the relevance score — every factor comes from a real signal.

    Nothing here invents weights or claims; it reports what the deterministic scoring and the
    filters actually saw, and clearly separates confirmed matches, mismatches and unknowns.
    """
    factors: list[MatchFactor] = []

    if content:
        hit = sorted(content & _record_stems(record))
        if hit:
            factors.append(MatchFactor(text=f"يطابق كلمات بحثك: {'، '.join(hit)}", kind=MatchKind.MATCH))
        elif is_approx:
            factors.append(MatchFactor(text="لا يطابق كلمات بحثك مباشرة", kind=MatchKind.MISMATCH))

    topic_stems = (
        set().union(*(_stems(t) for t in record.get("topics") or []))
        if record.get("topics") else set()
    )
    if profile.interests:
        shared = [i for i in profile.interests if _stems(i) & topic_stems]
        if shared:
            factors.append(MatchFactor(text=f"يطابق اهتمامك: {'، '.join(shared)}", kind=MatchKind.MATCH))

    opp_type = record.get("opportunity_type")
    if criteria.opportunity_types and opp_type in criteria.opportunity_types:
        factors.append(MatchFactor(text=f"النوع مطابق: {TYPE_AR.get(opp_type, opp_type)}", kind=MatchKind.MATCH))

    if criteria.locations:
        location = record.get("location")
        if location in criteria.locations:
            factors.append(MatchFactor(text=f"المدينة مطابقة: {location}", kind=MatchKind.MATCH))
        elif record.get("delivery_mode") == "online":
            factors.append(MatchFactor(text="عن بُعد — غير مقيّد بمدينة", kind=MatchKind.MATCH))

    mode = record.get("delivery_mode")
    if criteria.delivery_modes and mode in criteria.delivery_modes:
        factors.append(MatchFactor(text=f"طريقة الحضور مطابقة: {MODE_AR.get(mode, mode)}", kind=MatchKind.MATCH))

    cost = record.get("cost_sar")
    if criteria.max_budget_sar is not None:
        if isinstance(cost, (int, float)) and cost <= criteria.max_budget_sar:
            factors.append(MatchFactor(text=f"ضمن ميزانيتك: {cost:g} ريال", kind=MatchKind.MATCH))
        elif cost is None:
            factors.append(MatchFactor(text="الرسوم غير مذكورة؛ قد لا تكون ضمن ميزانيتك", kind=MatchKind.UNKNOWN))
    elif cost is None:
        factors.append(MatchFactor(text="الرسوم غير مذكورة", kind=MatchKind.UNKNOWN))

    registration = {
        "open": ("التسجيل مفتوح", MatchKind.MATCH),
        "not_yet_open": ("لم يبدأ التسجيل بعد", MatchKind.UNKNOWN),
        "closed": ("التسجيل مغلق", MatchKind.MISMATCH),
        "requires_verification": ("حالة التسجيل متعارضة بين المصادر", MatchKind.UNKNOWN),
    }.get(application_status or "")
    if registration:
        factors.append(MatchFactor(text=registration[0], kind=registration[1]))

    deadline_state = evaluate_deadline(record, evaluation_time)
    if deadline_state == DEADLINE_SAME_DAY:
        factors.append(MatchFactor(text="ينتهي التقديم اليوم والساعة غير محددة", kind=MatchKind.UNKNOWN))
    elif deadline_state == DEADLINE_UNKNOWN:
        factors.append(MatchFactor(text="موعد التقديم غير مؤكد", kind=MatchKind.UNKNOWN))

    # Eligibility is never confirmed from this data.
    factors.append(MatchFactor(text="الأهلية غير مؤكدة من البيانات المتاحة", kind=MatchKind.UNKNOWN))

    if is_approx:
        factors.append(MatchFactor(text="ليست مطابقة تامة لطلبك", kind=MatchKind.MISMATCH))

    return factors[:8]


async def rank_node(state: DiscoveryState) -> DiscoveryState:
    started = time.perf_counter()
    request = state["request"]
    evaluation_time = state["evaluation_time"]
    llm = state.get("llm")
    repo = state["deps"].repository
    approximate = state.get("approximate", False)

    # RAG re-rank: the model may reorder ONLY the exact (topic-relevant) matches by meaning —
    # it never promotes an off-topic "closest" item, and it never changes the score. So a weak
    # model can refine the order of relevant results but cannot surface an irrelevant one with
    # a fabricated percentage. The scores stay deterministic and honest; the reason, the
    # tooltip factors and the number always agree.
    ranked_all = state["ranked_all"]
    exact = [(record, score) for record, score, is_approx in ranked_all if not is_approx]
    tail = [item for item in ranked_all if item[2]]  # approximate "closest" items, kept as-is
    reranked = False
    if llm is not None and len(exact) >= 2:
        try:
            order = await rerank(llm, request.query, request.profile, [rec for rec, _ in exact])
        except Exception:
            order = None
        if order:
            position = {oid: i for i, oid in enumerate(order)}
            exact.sort(key=lambda pair: position.get(pair[0]["opportunity_id"], len(order)))
            reranked = True
    ranked_all = [(record, score, False) for record, score in exact] + tail

    # Build the FULL ordered list so browse can paginate; /discover shows only the top slice.
    # Only the items /discover shows get an LLM-written reason, to bound cost.
    criteria = state["criteria"]
    content = set(state.get("content_terms") or [])
    all_recs: list[Recommendation] = []
    approx_flags: list[bool] = []
    llm_reasons = 0
    for index, (record, score, is_approx) in enumerate(ranked_all):
        reason = None
        if llm is not None and index < 3:
            try:
                reason = await write_reason(llm, request.query, record)
                if reason:
                    llm_reasons += 1
            except Exception:
                reason = None
        if not reason:
            reason = _fallback_reason(record)

        application_status = repo.application_status(record)
        rec = to_recommendation(
            record,
            reason=reason,
            relevance_score=round(score, 1),
            application_status=application_status,
            evaluation_time=evaluation_time,
            extra_caveats=[_APPROX_CAVEAT] if is_approx else None,
            match_factors=explain_match(
                record, criteria, content, request.profile,
                is_approx=is_approx, evaluation_time=evaluation_time,
                application_status=application_status,
            ),
        )
        if rec is not None:
            all_recs.append(rec)
            approx_flags.append(is_approx)

    if not all_recs:
        # Everything that ranked failed grounding; return an honest no-match.
        return no_match_node(state)

    # /discover shows exact matches only (no off-topic padding). When there is no exact match
    # at all we show the closest ones instead — that is the "no match -> show similar" path.
    if approximate:
        shown = all_recs[:3]
    else:
        shown = [rec for rec, is_approx in zip(all_recs, approx_flags) if not is_approx][:3]

    message = _APPROX_MESSAGE if approximate else (
        "هذه فرص تدعم الأدلة مطابقتها لطلبك. الأهلية تحتاج تحققك من الشروط."
    )
    log = _append_log(
        state, "rank", "agent",
        f"rerank={'llm' if reranked else 'deterministic'}, ranked={len(all_recs)}, "
        f"shown={len(shown)}, approx={approximate}, llm_reasons={llm_reasons}",
        started,
    )
    response = DiscoveryResponse(
        **_base({**state, "log": log}),
        status=DiscoveryStatus.OK,
        message=message,
        recommendations=shown,
        approximate=approximate,
    )
    return {"response": response, "all_recommendations": all_recs,
            "approximate": approximate, "log": log}


# --------------------------------------------------------------------------
# Graph assembly (compiled once)
# --------------------------------------------------------------------------
_GRAPH = None


def build_graph():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH
    graph = StateGraph(DiscoveryState)
    graph.add_node("interpret", interpret_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("assess", assess_node)
    graph.add_node("needs_info", needs_info_node)
    graph.add_node("no_match", no_match_node)
    graph.add_node("rank", rank_node)

    graph.add_edge(START, "interpret")
    graph.add_edge("interpret", "retrieve")
    graph.add_edge("retrieve", "assess")
    graph.add_conditional_edges(
        "assess", _route,
        {"needs_info": "needs_info", "no_match": "no_match", "rank": "rank"},
    )
    graph.add_edge("needs_info", END)
    graph.add_edge("no_match", END)
    graph.add_edge("rank", END)

    _GRAPH = graph.compile()
    return _GRAPH


# --------------------------------------------------------------------------
# Public API-integration entry points
# --------------------------------------------------------------------------
def application_is_ready(deps: AppDependencies) -> bool:
    """Ready when the store holds opportunities and the workflow graph compiles.

    The model client is optional (deterministic fallbacks cover its absence), so readiness
    does not require a live provider — the application is fully usable with no API key.
    """
    try:
        if not deps.repository.is_ready():
            return False
        build_graph()
        return True
    except Exception:
        return False


def _emit_log(deps: AppDependencies, request_id: str, log: list[dict[str, Any]]) -> None:
    """Send the agent steps to the BACKEND tracer only (stdout / JSONL, and Phoenix when
    enabled). These technical steps are intentionally never placed on the public response."""
    for entry in log:
        try:
            deps.tracer.emit(
                request_id=request_id,
                step=str(entry.get("step", "step")),
                component=str(entry.get("component", "workflow")),
                outcome=str(entry.get("detail", "")),
                elapsed_ms=float(entry.get("elapsed_ms", 0.0)),
            )
        except Exception:
            pass


async def discover(request: DiscoveryRequest, deps: AppDependencies) -> DiscoveryResponse:
    """Public request + dependencies -> DiscoveryResponse, within the workflow time budget."""
    evaluation_time = deps.evaluation_time or deps.settings.resolve_evaluation_time()
    initial: DiscoveryState = {
        "deps": deps,
        "request": request,
        "evaluation_time": evaluation_time,
        "llm": build_llm_client(deps),
    }
    graph = build_graph()
    try:
        final = await asyncio.wait_for(
            graph.ainvoke(initial),
            timeout=deps.settings.workflow_timeout_seconds,
        )
    except asyncio.TimeoutError:
        return DiscoveryResponse(
            request_id=request.request_id,
            status=DiscoveryStatus.ERROR,
            message="تجاوز البحث المدة المسموحة قبل الوصول إلى نتيجة آمنة.",
            error_code="FURSAH_TIMEOUT",
        )
    _emit_log(deps, request.request_id, final.get("log", []))
    return final["response"]


async def discover_all(
    request: DiscoveryRequest, deps: AppDependencies, offset: int = 0, limit: int = 3
) -> BrowseResponse:
    """Paginated full ranking for 'show more / show all'.

    Runs the same workflow deterministically (no LLM reasons, so paging stays fast and
    consistent) and returns a slice of the full ordered list. needs_info / no_match surface
    as an empty page with that status, so the frontend only pages real results.
    """
    offset = max(0, offset)
    limit = max(1, min(limit, 50))
    evaluation_time = deps.evaluation_time or deps.settings.resolve_evaluation_time()
    initial: DiscoveryState = {
        "deps": deps,
        "request": request,
        "evaluation_time": evaluation_time,
        "llm": None,  # browse is deterministic: grounded fallback reasons for every item
    }
    graph = build_graph()
    try:
        final = await asyncio.wait_for(
            graph.ainvoke(initial), timeout=deps.settings.workflow_timeout_seconds
        )
    except asyncio.TimeoutError:
        return BrowseResponse(
            request_id=request.request_id, status=DiscoveryStatus.ERROR,
            message="تجاوز البحث المدة المسموحة.", total=0, offset=offset, limit=limit,
        )

    _emit_log(deps, request.request_id, final.get("log", []))
    response = final["response"]
    all_recs = final.get("all_recommendations", [])
    return BrowseResponse(
        request_id=request.request_id,
        status=response.status,
        message=response.message,
        total=len(all_recs),
        offset=offset,
        limit=limit,
        recommendations=all_recs[offset:offset + limit],
        interpreted_filters=response.interpreted_filters,
        approximate=final.get("approximate", False),
    )
