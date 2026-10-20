export type BackendStatus =
  | 'needs_information'
  | 'needs_asset_selection'
  | 'success'
  | 'critical'
  | 'asset_not_found'
  | 'error';

export type UiState = 'idle' | 'loading' | BackendStatus;
export type Priority = 'low' | 'medium' | 'high' | 'critical';

export interface MaintenanceRequest {
  location?: string | null;
  description: string;
}

export type ContinuationRequest =
  | { input_type: 'text'; text: string; step_id: string }
  | { input_type: 'asset_selection'; asset_id: string; step_id: string };

export interface TraceStep {
  step: string;
  status: 'completed' | 'failed' | 'skipped';
  details?: string | null;
  duration_ms?: number | null;
}

export interface Asset {
  asset_id: string;
  asset_type: string;
  location: string;
  model?: string | null;
  status?: string | null;
}

export interface Ticket {
  ticket_id: string;
  status: 'created' | 'escalated';
}

export interface Analysis {
  category?: string | null;
  priority?: Priority | null;
  symptoms?: string[];
  safety_signals?: string[];
}

export interface EvidenceSource {
  procedure_id: string;
  source: string;
  section: string;
  score: number;
  source_sha256: string;
  index_generation: string;
}

interface Base {
  request_id: string;
  thread_id?: string | null;
  trace?: TraceStep[];
  safety_message?: string | null;
  description?: string;
  location?: string | null;
}

export interface SuccessResponse extends Base {
  status: 'success';
  ticket: Ticket;
  asset: Asset;
  analysis: Analysis;
  recommended_action?: string | null;
  recommendation_status?: 'grounded' | 'partial' | 'manual_review' | 'legacy';
  evidence?: EvidenceSource[];
}
export interface CriticalResponse extends Base {
  status: 'critical';
  ticket: Ticket;
  asset: Asset;
  analysis: Analysis;
  safety_message: string;
  recommended_action?: string | null;
  recommendation_status?: 'grounded' | 'partial' | 'manual_review' | 'legacy';
  evidence?: EvidenceSource[];
}
export interface NeedsInformationResponse extends Base {
  status: 'needs_information';
  step_id: string;
  missing_fields: string[];
  question: string;
}
export interface NeedsAssetSelectionResponse extends Base {
  status: 'needs_asset_selection';
  step_id: string;
  message: string;
  assets: Asset[];
}
export interface AssetNotFoundResponse extends Base {
  status: 'asset_not_found';
  message: string;
}
export interface ErrorResponse extends Base {
  status: 'error';
  message: string;
  error_code?: 'rag_unavailable' | 'model_unavailable' | 'invalid_model_output' | 'processing_failed';
  /** Client-only flag. Live POSTs are not blindly retried after an uncertain result. */
  retryable?: boolean;
}

export type MaintenanceResponse =
  | SuccessResponse
  | CriticalResponse
  | NeedsInformationResponse
  | NeedsAssetSelectionResponse
  | AssetNotFoundResponse
  | ErrorResponse;

/* ---- Frontend-only chat model ---- */
export type ChatMessage =
  | { id: number; kind: 'user'; text: string; location?: string }
  | { id: number; kind: 'working'; mode: 'create' | 'continue'; done: boolean; steps: TraceStep[] }
  | { id: number; kind: 'result'; response: MaintenanceResponse; active: boolean };

/** What the ticket card knows so far — filled only from user input and backend responses. */
export interface KnownTicket {
  description?: string;
  location?: string | null;
  missing?: string[];
  assetId?: string;
  assetType?: string;
  assetModel?: string | null;
  assetStatus?: string | null;
  category?: string;
  priority?: Priority;
  symptoms?: string[];
  ticketId?: string;
  ticketStatus?: 'created' | 'escalated';
}
