from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ==========================================
# 1. LLM Structured Output Schemas
# ==========================================

class IssueExtraction(BaseModel):
    """Output from the Extraction Agent."""
    asset_type: Literal["air_conditioner", "printer", "plumbing", "electrical", "heater", "other"] | None = Field(..., description="air_conditioner, printer, plumbing, electrical, other, or null")
    location: str | None = Field(..., description="Extracted room or office location")
    symptoms: list[Literal["water_leak", "abnormal_noise", "not_working", "low_cooling", "paper_jam", "power_issue", "overheating"]] = Field(..., description="Canonical list of symptoms")
    safety_signals: list[Literal["electrical_risk", "fire_or_smoke", "flooding", "exposed_wires"]] = Field(..., description="Safety hazards")
    missing_fields: list[Literal["asset_type", "location", "symptoms"]] = Field(..., description="Missing fields")


class RecommendationOutput(BaseModel):
    """Output from the Recommendation Agent."""
    recommended_action: str = Field(description="Short Arabic recommendation based only on SOP excerpts")
    recommendation_status: Literal["grounded", "partial", "manual_review"] = "grounded"
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class FollowUpAnswer(BaseModel):
    """User clarification response item."""
    field: str
    answer: str


# ==========================================
# 2. Database & Knowledge Schemas
# ==========================================

class AssetItem(BaseModel):
    """Asset record from database."""
    asset_id: str
    asset_type: str
    asset_name_ar: str | None = None
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    model: str | None = None
    status: str | None = None

    @property
    def location(self) -> str:
        loc = self.room or f"Building {self.building}"
        return f"{loc}"


class ProcedureChunk(BaseModel):
    """Retrieved SOP knowledge chunk from RAG."""
    source: str
    content: str
    score: float = 0.0
    procedure_id: str = ""
    section: str = ""
    asset_type: str = ""
    symptoms: list[str] = Field(default_factory=list)
    safety_signals: list[str] = Field(default_factory=list)
    source_sha256: str = ""
    index_generation: str = ""


# ==========================================
# 3. Frontend-Compatible API Schemas
# ==========================================

class TraceStep(BaseModel):
    """Trace execution step matching frontend requirements."""
    step: str
    status: Literal["completed", "failed", "skipped"] = "completed"
    details: str | None = None
    duration_ms: float | None = None


class AssetResponse(BaseModel):
    """Asset object returned to frontend."""
    asset_id: str
    asset_type: str
    location: str
    model: str | None = None
    status: str | None = None


class TicketResponse(BaseModel):
    """Ticket object returned to frontend."""
    ticket_id: str
    status: Literal["created", "escalated"] = "created"


class AnalysisResponse(BaseModel):
    """Analysis object returned to frontend."""
    category: str | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    symptoms: list[str] = Field(default_factory=list)
    safety_signals: list[str] = Field(default_factory=list)


class MaintenanceRequest(BaseModel):
    """Incoming user maintenance report."""
    description: str = Field(..., min_length=1, max_length=4000, description="Free text description of the issue")
    location: str | None = Field(default=None, max_length=2000, description="Optional explicit location")

    @field_validator("description", "location", mode="before")
    @classmethod
    def trim_input(cls, value):
        return value.strip() if isinstance(value, str) else value


class ContinuationRequest(BaseModel):
    """Continuation payload sent by the frontend on resume."""
    input_type: Literal["text", "asset_selection"]
    step_id: str = Field(min_length=1, max_length=128)
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    asset_id: str | None = Field(default=None, min_length=1)

    @field_validator("text", "asset_id", "step_id", mode="before")
    @classmethod
    def trim_input(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_input_kind(self):
        if self.input_type == "text" and (self.text is None or self.asset_id is not None):
            raise ValueError("Text continuation requires only text")
        if self.input_type == "asset_selection" and (self.asset_id is None or self.text is not None):
            raise ValueError("Asset selection requires only asset_id")
        return self


# Discriminated union responses matching Zod responseSchema
class SuccessResponse(BaseModel):
    status: Literal["success"] = "success"
    request_id: str
    thread_id: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    ticket: TicketResponse
    asset: AssetResponse
    analysis: AnalysisResponse
    recommended_action: str | None = None
    recommendation_status: Literal["grounded", "partial", "manual_review", "legacy"] = "legacy"
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class CriticalResponse(BaseModel):
    status: Literal["critical"] = "critical"
    request_id: str
    thread_id: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    ticket: TicketResponse
    asset: AssetResponse
    analysis: AnalysisResponse
    safety_message: str
    recommended_action: str | None = None
    recommendation_status: Literal["grounded", "partial", "manual_review", "legacy"] = "legacy"
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class NeedsInformationResponse(BaseModel):
    status: Literal["needs_information"] = "needs_information"
    request_id: str
    thread_id: str
    step_id: str
    trace: list[TraceStep] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    question: str
    safety_message: str | None = None


class NeedsAssetSelectionResponse(BaseModel):
    status: Literal["needs_asset_selection"] = "needs_asset_selection"
    request_id: str
    thread_id: str
    step_id: str
    trace: list[TraceStep] = Field(default_factory=list)
    message: str
    assets: list[AssetResponse] = Field(default_factory=list)
    safety_message: str | None = None


class AssetNotFoundResponse(BaseModel):
    status: Literal["asset_not_found"] = "asset_not_found"
    request_id: str
    thread_id: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    message: str
    safety_message: str | None = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    request_id: str
    thread_id: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    message: str
    retryable: bool = False


# Union response type
MaintenanceResponse = (
    SuccessResponse
    | CriticalResponse
    | NeedsInformationResponse
    | NeedsAssetSelectionResponse
    | AssetNotFoundResponse
    | ErrorResponse
)
