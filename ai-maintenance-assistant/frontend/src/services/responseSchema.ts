import { z } from 'zod';

const trace = z.object({
  step: z.string(), status: z.enum(['completed', 'failed', 'skipped']),
  details: z.string().nullable().optional(), duration_ms: z.number().nullable().optional(),
});
const asset = z.object({
  asset_id: z.string(), asset_type: z.string(), location: z.string(),
  model: z.string().nullable().optional(), status: z.string().nullable().optional(),
});
const base = z.object({
  request_id: z.string(), thread_id: z.string().nullable().optional(),
  trace: z.array(trace).optional(),
  safety_message: z.string().nullable().optional(),
  description: z.string().optional(), location: z.string().nullable().optional(),
});
const completed = base.extend({
  ticket: z.object({ ticket_id: z.string(), status: z.enum(['created', 'escalated']) }),
  asset,
  analysis: z.object({
    category: z.string().nullable().optional(),
    priority: z.enum(['low', 'medium', 'high', 'critical']).nullable().optional(),
    symptoms: z.array(z.string()).optional(), safety_signals: z.array(z.string()).optional(),
  }),
  recommended_action: z.string().nullable().optional(),
  recommendation_status: z.enum(['grounded', 'partial', 'manual_review', 'legacy']).optional(),
  evidence: z.array(z.object({
    procedure_id: z.string(), source: z.string(), section: z.string(), score: z.number(),
    source_sha256: z.string(), index_generation: z.string(),
  })).optional(),
});

/** Validate HTTP data before it reaches components. Unknown fields are stripped. */
export const responseSchema = z.discriminatedUnion('status', [
  completed.extend({ status: z.literal('success'), ticket: z.object({ ticket_id: z.string().min(1), status: z.literal('created') }) }),
  completed.extend({ status: z.literal('critical'), safety_message: z.string().trim().min(1),
    ticket: z.object({ ticket_id: z.string().min(1), status: z.literal('escalated') }) }),
  base.extend({ status: z.literal('needs_information'), thread_id: z.string().min(1),
    step_id: z.string().min(1),
    missing_fields: z.array(z.string()), question: z.string() }),
  base.extend({ status: z.literal('needs_asset_selection'), thread_id: z.string().min(1),
    step_id: z.string().min(1),
    message: z.string(), assets: z.array(asset).min(1) }),
  base.extend({ status: z.literal('asset_not_found'), message: z.string() }),
  base.extend({ status: z.literal('error'), message: z.string(),
    error_code: z.enum(['rag_unavailable', 'model_unavailable', 'invalid_model_output', 'processing_failed']).optional() }),
]).superRefine((response, context) => {
  if (response.status === 'success' && response.analysis.priority === 'critical') {
    context.addIssue({ code: 'custom', message: 'Success cannot have critical priority' });
  }
  if (response.status === 'critical' && response.analysis.priority !== 'critical') {
    context.addIssue({ code: 'custom', message: 'Escalation requires critical priority' });
  }
});
