import type { ChatMessage } from '../types/maintenance';
import { STEP_AR } from '../labels';

type Working = Extract<ChatMessage, { kind: 'working' }>;

export default function WorkingMessage({ msg, onShowTrace }: { msg: Working; onShowTrace: () => void }) {
  const totalMs = msg.steps.reduce((a, t) => a + (t.duration_ms ?? 0), 0);

  return (
    <div className="agent-row">
      <div className="avatar">س</div>
      <div className="agent-row__body">
        {!msg.done ? (
          <ul className="live-steps" aria-live="polite">
            <li className="is-current"><span className="live-steps__mark"><span className="pulse" /></span>
              {msg.mode === 'create' ? 'جاري معالجة البلاغ…' : 'جاري استكمال البلاغ…'}
            </li>
          </ul>
        ) : (
          <button className="step-summary" onClick={onShowTrace} title="عرض مسار التنفيذ">
            {!msg.steps.length && <span>لم تصل خطوات تنفيذ إضافية من الخادم.</span>}
            {msg.steps.map((t, i) => (
              <span key={i} className="step-summary__item">
                <span className={t.status === 'failed' ? 'c-danger' : 'c-accent'}>{t.status === 'failed' ? '×' : t.status === 'skipped' ? '–' : '✓'}</span>
                {STEP_AR[t.step] ?? t.step}
                {i < msg.steps.length - 1 && <span className="step-summary__sep">·</span>}
              </span>
            ))}
            {totalMs > 0 && <span className="mono" dir="ltr">{(totalMs / 1000).toFixed(2)}s</span>}
          </button>
        )}
      </div>
    </div>
  );
}
