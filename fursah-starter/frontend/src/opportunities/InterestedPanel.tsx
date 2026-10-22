import { useEffect, useState } from 'react';
import type { OpportunityDetails, Recommendation } from '../types';
import { listInterested, removeInterest } from '../api/client';
import { label, modeLabel } from '../labels';
import Drawer from '../components/Drawer';

/** A details record is enough to open the details drawer, which re-fetches by id anyway. */
function toRec(d: OpportunityDetails): Recommendation {
  return {
    opportunity_id: d.opportunity_id, title: d.title, source_ids: d.source_ids,
    eligibility_status: 'uncertain', reason: '', caveats: [],
    opportunity_type: d.opportunity_type, location: d.location, delivery_mode: d.delivery_mode,
    deadline: d.deadline, application_status: d.application_status,
    evidence_version: d.evidence_version, relevance_score: null, match_factors: [],
  };
}

/** The "الفرص المهتم بها" section: this browser's saved opportunities. */
export default function InterestedPanel({ onClose, onOpenDetails, onRemoved }: {
  onClose: () => void;
  onOpenDetails: (rec: Recommendation) => void;
  onRemoved: (opportunityId: string) => void;
}) {
  const [items, setItems] = useState<OpportunityDetails[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    listInterested().then(result => { if (alive) setItems(result?.opportunities ?? []); });
    return () => { alive = false; };
  }, []);

  async function remove(id: string) {
    setBusy(id);
    const ok = await removeInterest(id);
    setBusy(null);
    if (ok) { setItems(list => (list ?? []).filter(d => d.opportunity_id !== id)); onRemoved(id); }
  }

  return (
    <Drawer title="الفرص المهتم بها" onClose={onClose}>
      {items === null && <p className="muted">جارٍ تحميل الفرص المحفوظة…</p>}
      {items !== null && items.length === 0 && (
        <p className="muted">لم تحفظ أي فرصة بعد. استخدم زر «مهتم» على أي فرصة لإضافتها هنا.</p>
      )}
      {items?.map(d => {
        const meta = [label(d.opportunity_type), d.location, modeLabel(d.delivery_mode)].filter(Boolean).join(' · ');
        return (
          <article key={d.opportunity_id} className="card saved-item">
            <div className="saved-item__titles">
              <h3 className="opp__title">{d.title}</h3>
              <div className="opp__meta">{meta || '—'}</div>
            </div>
            <div className="opp__actions">
              <button className="btn btn--primary btn--sm" onClick={() => onOpenDetails(toRec(d))}>عرض التفاصيل</button>
              <button
                className="btn btn--sm btn--outline"
                disabled={busy === d.opportunity_id}
                onClick={() => remove(d.opportunity_id)}
              >إزالة</button>
              <span className="spacer" />
              <span className="opp__sources" dir="ltr">{d.source_ids.join(', ')}</span>
            </div>
          </article>
        );
      })}
    </Drawer>
  );
}
