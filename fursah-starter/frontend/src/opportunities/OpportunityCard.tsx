import type { EligibilityStatus, Recommendation } from '../types';
import { UNKNOWN, fmtDeadline, label, modeLabel } from '../labels';
import MatchTooltip from './MatchTooltip';


export function EligibilityBadge({ status }: { status: EligibilityStatus }) {
  const ok = status === 'confirmed';
  return (
    <span className={`elig elig--${ok ? 'confirmed' : 'uncertain'}`}>
      <span className="elig__icon" aria-hidden="true">{ok ? '✓' : '?'}</span>
      الأهلية: {ok ? 'مؤكدة' : 'غير مؤكدة'}
    </span>
  );
}

/** Interested ("مهتم") toggle. Saved state is driven by the parent; aria-pressed exposes it. */
export function InterestButton({ saved, onToggle, busy }: { saved: boolean; onToggle: () => void; busy?: boolean }) {
  return (
    <button
      type="button"
      className={`btn btn--sm interest-btn ${saved ? 'interest-btn--on' : 'btn--outline'}`}
      aria-pressed={saved}
      aria-label={saved ? 'إزالة من قائمة المهتم بها' : 'حفظ في قائمة المهتم بها'}
      title={saved ? 'إزالة من المهتم بها' : 'حفظ كمهتم'}
      disabled={busy}
      onClick={onToggle}
    >
      <span aria-hidden="true">{saved ? '★' : '☆'}</span> مهتم
    </button>
  );
}

interface Props {
  rec: Recommendation;
  onOpen: () => void;
  saved: boolean;
  onToggleSave: () => void;
}

export default function OpportunityCard({ rec, onOpen, saved, onToggleSave }: Props) {
  const meta = [label(rec.opportunity_type), rec.location, modeLabel(rec.delivery_mode)].filter(Boolean).join(' · ') || 'النوع والموقع غير معروفين';
  return (
    <article className="card opp">
      <div className="opp__top">
        <div className="opp__titles">
          <h3 className="opp__title">{rec.title}</h3>
          <div className="opp__meta">{meta}</div>
        </div>
        {rec.relevance_score != null && (
          <MatchTooltip score={rec.relevance_score} factors={rec.match_factors ?? []} />
        )}
      </div>

      <div className="opp__status">
        <EligibilityBadge status={rec.eligibility_status} />
        <span className="kv"><span>آخر موعد</span> {fmtDeadline(rec.deadline) ?? UNKNOWN}</span>
        <span className="kv"><span>حالة التقديم</span> {rec.application_status ? label(rec.application_status) : UNKNOWN}</span>
      </div>
      {rec.eligibility_status !== 'confirmed' && <div className="opp__note">بعض المتطلبات لا تزال بحاجة إلى تحقق.</div>}

      {rec.reason && (
        <div className="block">
          <div className="section-label">لماذا تناسبك</div>
          <div className="block__text">{rec.reason}</div>
        </div>
      )}

      {rec.caveats.length > 0 && (
        <div className="notice">
          <div className="notice__title">ملاحظات مهمة</div>
          <ul className="list list--tight">
            {rec.caveats.map((c, i) => <li key={i}>! {c}</li>)}
          </ul>
        </div>
      )}

      {rec.next_action && <div className="opp__next"><strong>الخطوة التالية:</strong> {rec.next_action}</div>}

      <div className="opp__actions">
        <button className="btn btn--primary btn--sm" onClick={onOpen}>عرض التفاصيل</button>
        <InterestButton saved={saved} onToggle={onToggleSave} />
        <span className="spacer" />
        {rec.source_ids.length > 0 && <span className="opp__sources" dir="ltr">{rec.source_ids.join(', ')}</span>}
      </div>
    </article>
  );
}
