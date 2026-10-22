#  LLM layer (OpenRouter) used ONLY where a model genuinely helps:
#   1. interpret_query(): turn free Arabic text into retrieval hints (keywords / city / type).
#   2. write_reason():     phrase a short Arabic justification for an ALREADY-selected,
#                          evidence-grounded recommendation.
#
# The model never selects opportunities, invents IDs, or decides eligibility — those are
# deterministic and source-grounded in the workflow. Every call is bounded (timeout +
# retries) and has a deterministic fallback, so the whole application works with NO API key.
# That keeps the demo reliable and matches the project rule: "an LLM does not automatically
# gain access to your dataset."
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .infrastructure.dependencies import AppDependencies, ModelClientConfig
from .infrastructure.observability import start_span
from .schemas import SearchConstraints, UserProfile

# Vocabulary the model is allowed to emit back, so a hallucinated type/mode can never leak
# into retrieval. Anything outside these sets is dropped.
_KNOWN_TYPES = {"workshop", "course", "internship", "competition", "volunteering", "event"}
_KNOWN_MODES = {"in_person", "online", "hybrid"}


class LlmClient:
    """Thin async wrapper over an OpenRouter / OpenAI-compatible chat-completions endpoint."""

    def __init__(self, config: ModelClientConfig) -> None:
        self._config = config
        base = config.base_url.rstrip("/")
        # Tolerate a base_url given with or without the /v1 suffix.
        self._url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")

    @property
    def model_name(self) -> str:
        return self._config.model_name

    async def complete(
        self, system: str, user: str, *, json_mode: bool, max_tokens: int = 400,
        purpose: str = "llm",
    ) -> str | None:
        """Return the raw assistant message text, or None on any transport/model failure.

        Records ONE LLM span per logical call (not per retry) — these httpx calls don't go
        through LangChain, so the framework instrumentor can't see them (2.2). `purpose` names
        the caller (interpret_query / rerank / write_reason) so each span is identifiable.
        """
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        # Optional OpenRouter attribution headers.
        headers.setdefault("X-Title", "FURSAH")

        payload: dict[str, Any] = {
            "model": self._config.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        attempts = max(1, self._config.max_retries + 1)
        timeout = httpx.Timeout(self._config.timeout_seconds)
        # One span wraps the whole call (incl. retries), so a retried call is not traced twice.
        with start_span(
            f"llm.{purpose}",
            **{
                "openinference.span.kind": "LLM",
                "llm.model_name": self._config.model_name,
                "fursah.llm.purpose": purpose,
                "input.value": f"{system}\n\n{user}",
            },
        ) as span:
            for attempt in range(attempts):
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(self._url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage") or {}
                    span.set_attribute("output.value", content or "")
                    span.set_attribute("llm.token_count.prompt", int(usage.get("prompt_tokens", 0)))
                    span.set_attribute("llm.token_count.completion", int(usage.get("completion_tokens", 0)))
                    return content
                except Exception:
                    if attempt + 1 >= attempts:
                        span.set_attribute("output.value", "")
                        span.set_attribute("fursah.llm.failed", True)
                        return None
        return None


def build_llm_client(deps: AppDependencies) -> LlmClient | None:
    """Create a client only when a live model is actually configured; otherwise None."""
    if deps.model_config is None:
        return None
    return LlmClient(deps.model_config)


def _loads(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    text = text.strip()
    # Some models wrap JSON in a ```json fence; strip it defensively.
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def interpret_query(
    client: LlmClient, query: str, profile: UserProfile, constraints: SearchConstraints
) -> dict[str, Any]:
    """Ask the model for SOFT topic keywords from the Arabic query. Returns {} on any problem.

    Keywords only — they improve topic matching but are never applied as hard filters, so the
    model can broaden/enrich retrieval but can never silently constrain it (e.g. turning a city
    mention into an in-person-only filter). Hard filters come from the form + deterministic
    detection in the workflow.
    """
    system = (
        "استخرج كلمات مفتاحية موضوعية من طلب بحث عربي عن فرص تدريبية. "
        "أعد JSON بالشكل {\"keywords\": [\"...\"]} يحوي كلمات تصف الموضوع فقط "
        "(مثل: تحليل، بيانات، برمجة)، دون أسماء المدن أو أنواع الفعاليات. "
        "لا تخترع كلمات غير موجودة في المعنى. أعد قائمة فارغة عند عدم وضوح الموضوع."
    )
    user = f"الطلب: {query}"
    raw = await client.complete(system, user, json_mode=True, max_tokens=200, purpose="interpret_query")
    data = _loads(raw)
    keywords = data.get("keywords")
    if not isinstance(keywords, list):
        return {}
    return {"keywords": [k.strip() for k in keywords if isinstance(k, str) and k.strip()][:12]}


async def rerank(
    client: LlmClient, query: str, profile: UserProfile, candidates: list[dict[str, Any]]
) -> list[str] | None:
    """Semantic re-rank: the model orders the RETRIEVED candidates by relevance to the query.

    This is the RAG payoff — the model understands Arabic morphology/synonyms that keyword
    scoring cannot. It returns only IDs drawn from the given pool (best first, empty if none
    are relevant); any id not in the pool is dropped, so it can never invent a recommendation.
    Returns None on transport/parse failure, and the caller then keeps the deterministic order.
    """
    items = [
        {
            "id": record.get("opportunity_id"),
            "title": record.get("title"),
            "topic": record.get("topic"),
            "type": record.get("opportunity_type"),
            "location": record.get("location"),
            "mode": record.get("delivery_mode"),
        }
        for record in candidates
    ]
    system = (
        "أنت تعيد ترتيب فرص تدريبية حسب مدى ملاءمتها لطلب المستخدم. "
        "أعد JSON بالشكل {\"ranked_ids\": [\"...\"]} يحوي فقط معرّفات (id) من القائمة المعطاة، "
        "من الأنسب إلى الأقل، واحذف غير المناسب. "
        "أعد قائمة فارغة إذا لم تكن أي فرصة مناسبة. لا تخترع أي معرّف غير موجود في القائمة."
    )
    user = (
        f"الطلب: {query}\n"
        f"اهتمامات المستخدم: {', '.join(profile.interests) or 'غير محددة'}\n"
        f"الفرص:\n{json.dumps(items, ensure_ascii=False)}"
    )
    raw = await client.complete(system, user, json_mode=True, max_tokens=600, purpose="rerank")
    data = _loads(raw)
    ranked = data.get("ranked_ids")
    if not isinstance(ranked, list):
        return None

    valid = {str(record.get("opportunity_id")) for record in candidates}
    seen: set[str] = set()
    ordered: list[str] = []
    for identifier in ranked:
        text = str(identifier).strip() if identifier is not None else ""
        if text in valid and text not in seen:  # pool-only: invented ids are silently dropped
            seen.add(text)
            ordered.append(text)
    return ordered


_ARABIC = re.compile(r"[؀-ۿ]")
_ARABIC_WORD = re.compile(r"[؀-ۿ]{3,}")


def _is_arabic(text: str) -> bool:
    """True when the text is predominantly Arabic (guards against a model answering in another
    language — e.g. Qwen sometimes replies in Chinese)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    arabic = sum(1 for c in letters if _ARABIC.match(c))
    return arabic / len(letters) >= 0.6


def _mentions_opportunity(reason: str, record: dict[str, Any]) -> bool:
    """True when the reason actually references this opportunity's title/topic, so a generic or
    fabricated reason (describing a different activity) is rejected. Latin-only titles like
    'Power BI' cannot be checked this way, so they pass."""
    source = f"{record.get('title') or ''} {record.get('topic') or ''}"
    words = set(_ARABIC_WORD.findall(source))
    if not words:
        return True
    return any(word in reason for word in words)


async def write_reason(client: LlmClient, query: str, record: dict[str, Any]) -> str | None:
    """Phrase a one-sentence Arabic reason for a pre-selected, grounded recommendation.

    Returns None (so the caller uses the deterministic Arabic reason) unless the model's reply
    is Arabic AND references this opportunity — so a non-Arabic or fabricated reason is dropped.
    """
    facts = {
        "title": record.get("title"),
        "type": record.get("opportunity_type"),
        "location": record.get("location"),
        "delivery_mode": record.get("delivery_mode"),
        "topics": record.get("topics"),
    }
    system = (
        "اكتب بالعربية الفصحى فقط ولا تستخدم أي لغة أخرى. "
        "اكتب جملة واحدة قصيرة تشرح لماذا تناسب هذه الفرصة طلب المستخدم، معتمداً فقط على الحقائق المعطاة. "
        "استخدم عنوان الفرصة وموضوعها كما وردا، ولا تخترع نوع الفرصة أو موضوعها، ولا تؤكد الأهلية."
    )
    user = f"طلب المستخدم: {query}\nحقائق الفرصة: {json.dumps(facts, ensure_ascii=False)}"
    raw = await client.complete(system, user, json_mode=False, max_tokens=160, purpose="write_reason")
    if not raw:
        return None
    reason = raw.strip().strip('"').replace("\n", " ")
    if not reason or not _is_arabic(reason) or not _mentions_opportunity(reason, record):
        return None  # non-Arabic or ungrounded -> deterministic fallback
    return reason
