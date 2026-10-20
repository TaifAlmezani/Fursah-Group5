import type { AssetNotFoundResponse } from '../../types/maintenance';
import ResultCard from './ResultCard';

export default function AssetNotFoundResult({ r, active, onEdit }: { r: AssetNotFoundResponse; active: boolean; onEdit: () => void }) {
  return (
    <ResultCard tone="muted" icon="×" title="تعذر إنشاء البلاغ" subtitle="يرجى التواصل مع قسم الصيانة.">
      {r.safety_message && <p role="alert" className="result__message">{r.safety_message}</p>}
      <p className="result__message">{r.message}</p>
      {active && <div className="actions"><button className="btn btn--primary" onClick={onEdit}>تعديل البلاغ</button></div>}
    </ResultCard>
  );
}
