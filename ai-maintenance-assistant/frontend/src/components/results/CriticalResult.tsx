import type { CriticalResponse } from '../../types/maintenance';
import ResultCard, { Field } from './ResultCard';
import EvidenceReferences from './EvidenceReferences';

export default function CriticalResult({ r, active, onNew }: { r: CriticalResponse; active: boolean; onNew: () => void }) {
  return (
    <ResultCard tone="danger" icon="!" title="حالة صيانة حرجة" subtitle="تتطلب الحالة تصعيدًا فوريًا." ticketId={r.ticket.ticket_id}>
      <Field label="خطر السلامة"><span className="c-danger-soft">{r.safety_message}</span></Field>
      <Field label={r.recommendation_status === 'manual_review' ? 'الفحص المطلوب' : 'الإجراء المقترح'}><div style={{ whiteSpace: 'pre-line' }}>{r.recommended_action}</div></Field>
      <EvidenceReferences evidence={r.evidence} />
      {active && <div className="actions"><button className="btn btn--danger-outline" onClick={onNew}>بلاغ جديد</button></div>}
    </ResultCard>
  );
}
