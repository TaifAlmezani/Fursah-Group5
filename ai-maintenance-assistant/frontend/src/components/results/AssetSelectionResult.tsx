import { useId, useState } from 'react';
import type { NeedsAssetSelectionResponse } from '../../types/maintenance';
import { TYPE_AR } from '../../labels';

export default function AssetSelectionResult({ r, active, onConfirm }: { r: NeedsAssetSelectionResponse; active: boolean; onConfirm: (assetId: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const groupName = useId();
  return (
    <div className="agent-row">
      <div className="avatar avatar--spacer" />
      <div className="followup">
        <div className="followup__kicker">تم العثور على أكثر من جهاز</div>
        {r.safety_message && <p role="alert" className="result__message">{r.safety_message}</p>}
        <div className="followup__q">{r.message}</div>
        <div className="followup__hint" id={`${groupName}-hint`}>استخدم الأسهم للتنقل بين الأجهزة، ثم Tab للوصول إلى تأكيد الاختيار.</div>
        <div className="assets" role="radiogroup" aria-label="الأجهزة المطابقة" aria-describedby={`${groupName}-hint`}>
          {r.assets.map((a, index) => {
            const on = selected === a.asset_id;
            return (
              <label key={a.asset_id} className={`asset${on ? ' is-selected' : ''}${!active ? ' is-disabled' : ''}`}>
                <input className="asset__input" type="radio" name={groupName} value={a.asset_id}
                  checked={on} disabled={!active} autoFocus={active && index === 0} onChange={() => setSelected(a.asset_id)} />
                <span className="asset__top">
                  <span className="asset__room">{a.location.match(/(?:غرفة|room)\s+([A-Za-z]?\d+)/i)?.[1] ?? a.location}</span>
                  <span className="radio" aria-hidden="true"><span /></span>
                </span>
                <span className="asset__id mono" dir="ltr">{a.asset_id}</span>
                <span className="asset__desc">{TYPE_AR[a.asset_type] ?? a.asset_type} — {a.location}</span>
                <span className="asset__desc">{a.model || 'الموديل غير متوفر'} — {a.status === 'active' ? 'بالخدمة' : a.status === 'inactive' ? 'خارج الخدمة' : 'الحالة غير متوفرة'}</span>
              </label>
            );
          })}
        </div>
        {active && (
          <div><button className="btn btn--warn" disabled={!selected} onClick={() => selected && onConfirm(selected)}>تأكيد الاختيار ←</button></div>
        )}
      </div>
    </div>
  );
}
