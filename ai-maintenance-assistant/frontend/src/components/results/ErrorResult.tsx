import type { ErrorResponse } from '../../types/maintenance';
import ResultCard from './ResultCard';

export default function ErrorResult({ r, active, onRetry, onNew }: { r: ErrorResponse; active: boolean; onRetry: () => void; onNew: () => void }) {
  return (
    <ResultCard tone="error" icon="!" title="حدث خطأ">
      <p className="result__message">{r.message}</p>
      <div className="small muted">رقم الطلب: <span className="mono c-ink" dir="ltr">{r.request_id}</span></div>
      {active && (
        <div className="actions">
          {r.retryable && <button className="btn btn--primary" onClick={onRetry}>المحاولة مرة أخرى</button>}
          <button className="btn btn--outline" onClick={onNew}>بلاغ جديد</button>
        </div>
      )}
    </ResultCard>
  );
}
