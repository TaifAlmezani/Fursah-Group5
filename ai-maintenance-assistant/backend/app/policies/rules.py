from collections.abc import Sequence


# 1. Asset Type to Department Category Mapping
CATEGORY_MAP = {
    "air_conditioner": "HVAC",
    "printer": "IT Equipment",
    "plumbing": "Facilities & Plumbing",
    "electrical": "Electrical Systems",
    "other": "General Maintenance",
}


def category_for_asset_type(asset_type: str | None) -> str:
    """Deterministic mapping from asset type to maintenance department."""
    return CATEGORY_MAP.get(asset_type or "", "General Maintenance")


# 2. Priority Determination (Deterministic Business Rules)
def determine_priority(
    asset_type: str | None,
    symptoms: Sequence[str] = (),
    safety_signals: Sequence[str] = (),
) -> str:
    """Calculate priority level without AI hallucination risk."""
    signals = set(safety_signals)
    syms = set(symptoms)

    # Critical conditions (immediate danger or severe disruption)
    if "fire_or_smoke" in signals or "electrical_risk" in signals or "exposed_wires" in signals:
        return "CRITICAL"
    if "flooding" in signals and asset_type in ("electrical", "air_conditioner"):
        return "CRITICAL"

    # High conditions
    if "water_leak" in syms or "overheating" in syms or "power_issue" in syms:
        return "HIGH"

    # Medium conditions
    if "paper_jam" in syms or "low_cooling" in syms or "abnormal_noise" in syms:
        return "MEDIUM"

    return "LOW"


# 3. Safety Signals and Warning Messages
SAFETY_MESSAGES = {
    "electrical_risk": "تحذير أمان: يُمنع لمس الجهاز المبتل، يرجى فصل القاطع الكهربائي فوراً والابتعاد عن موقع التسريب.",
    "fire_or_smoke": "تحذير عالي الخطورة: يرجى إخلاء المنطقة فوراً واستخدام طفاية الحريق المناسبة إن لزم الأمر.",
    "flooding": "تحذير: تسريب مياه كثيف، يرجى إغلاق المحبس الرئيسي لتجنب أضرار إضافية.",
    "exposed_wires": "تحذير أمان: أسلاك مكشوفة! يُرجى عدم الاقتراب من الموقع لحين وصول الفني المختص.",
}

# Presentation order only; escalation remains governed by determine_priority.
SAFETY_WARNING_ORDER = (
    "fire_or_smoke",
    "electrical_risk",
    "exposed_wires",
    "flooding",
)


def evaluate_safety(safety_signals: Sequence[str] = ()) -> str | None:
    """Show every recognized warning once, in a stable presentation order."""
    signals = set(safety_signals)
    messages = [SAFETY_MESSAGES[signal] for signal in SAFETY_WARNING_ORDER if signal in signals]
    return " ".join(messages) or None
