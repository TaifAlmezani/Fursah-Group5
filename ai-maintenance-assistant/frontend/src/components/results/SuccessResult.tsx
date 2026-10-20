import type { SuccessResponse } from '../../types/maintenance';
import { PRIORITY_AR, symptomsText } from '../../labels';
import ResultCard, { Field } from './ResultCard';
import EvidenceReferences from './EvidenceReferences';

export default function SuccessResult({ r, active, onNew, onShowTrace }: { r: SuccessResponse; active: boolean; onNew: () => void; onShowTrace: () => void }) {
  const pri = r.analysis.priority;
  return (
    <ResultCard tone="ok" icon="✓" title="تم إنشاء بلاغ الصيانة" ticketId={r.ticket.ticket_id}
      subtitle={`${r.asset.asset_id} · ${r.asset.location}${pri ? ` · الأولوية ${PRIORITY_AR[pri]}` : ''}`}>
      {r.safety_message && <p role="alert" className="result__message">{r.safety_message}</p>}
      <Field label="المشكلة المكتشفة">{symptomsText(r.analysis.symptoms) || '—'}</Field>
      <Field label={r.recommendation_status === 'manual_review' ? 'الفحص المطلوب' : 'الإجراء المقترح'}><div style={{ whiteSpace: 'pre-line' }}>{r.recommended_action}</div></Field>
      <EvidenceReferences evidence={r.evidence} />
      {active && (
        <div className="actions">
          <button className="btn btn--outline" onClick={onNew}>بلاغ جديد</button>
          <button className="btn btn--ghost-outline" onClick={onShowTrace}>عرض مسار التنفيذ</button>
        </div>
      )}
    </ResultCard>
  );
}
