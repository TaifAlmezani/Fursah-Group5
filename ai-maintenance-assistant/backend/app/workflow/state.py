from typing import Any, TypedDict


class MaintenanceState(TypedDict, total=False):
    """The unified state passing across all LangGraph nodes."""
    # Identification & Tracing
    request_id: str
    thread_id: str
    status: str  # "processing", "needs_information", "needs_asset_selection", "success", "critical", "asset_not_found", "error"
    trace: list[dict[str, Any]]

    # Input Facts
    description: str
    location: str | None
    follow_up_answers: list[dict[str, Any]]

    # Extracted by LLM
    asset_type: str | None
    category: str | None
    symptoms: list[str]
    safety_signals: list[str]
    missing_fields: list[str]

    # Asset Resolution
    candidate_assets: list[dict[str, Any]]
    selected_asset: dict[str, Any] | None
    selected_asset_id: str | None

    # RAG & Policy
    retrieved_procedures: list[dict[str, Any]]
    priority: str | None  # "low", "medium", "high", "critical"
    safety_message: str | None

    # Recommendation & Output
    recommended_action: str | None
    recommendation_status: str
    recommendation_evidence: list[dict[str, Any]]
    ticket_id: str | None
    ticket_status: str | None  # "created" | "escalated"
    question: str | None
    message: str | None
    error: str | None
