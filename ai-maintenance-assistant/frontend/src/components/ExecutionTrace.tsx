import type { TraceStep } from '../types/maintenance';
import { STEP_AR } from '../labels';

/** Execution evidence only — no chain-of-thought, secrets, or raw errors. */
export default function ExecutionTrace({ trace, threadId, requestId }: { trace: TraceStep[]; threadId: string | null; requestId: string | null }) {
  if (!trace.length) return <p className="muted small">ستظهر هنا خطوات سير العمل بعد إرسال البلاغ.</p>;
  return (
    <div className="trace">
      {(threadId || requestId) && (
        <div className="trace__ids mono" dir="ltr"><span>{threadId}</span><span>{requestId}</span></div>
      )}
      <ol className="trace__list">
        {trace.map((t, i) => {
          const kind = t.status === 'failed' ? 'failed' : t.step === 'wait_for_input' ? 'waiting' : t.status === 'skipped' ? 'skipped' : 'done';
          const mark = { failed: '×', waiting: '‖', skipped: '–', done: '✓' }[kind];
          return (
            <li key={i} className={`trace__step trace__step--${kind}`}>
              <span className="trace__rail"><span className="trace__dot">{mark}</span><span className="trace__line" /></span>
              <div className="trace__content">
                <div className="trace__head">
                  <span className="trace__label">{STEP_AR[t.step] ?? t.step}</span>
                  {t.duration_ms != null ? <span className="mono trace__ms" dir="ltr">{t.duration_ms}ms</span> : null}
                </div>
                {t.details && <div className="trace__details">{t.details}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
