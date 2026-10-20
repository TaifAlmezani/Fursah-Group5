import type { NeedsInformationResponse } from '../../types/maintenance';

export default function FollowUpResult({ r, active }: { r: NeedsInformationResponse; active: boolean }) {
  return (
    <div className="agent-row">
      <div className="avatar avatar--spacer" />
      <div className="followup">
        <div className="followup__kicker">نحتاج معلومة إضافية</div>
        {r.safety_message && <p role="alert" className="result__message">{r.safety_message}</p>}
        <div className="followup__q">{r.question}</div>
        {active && <div className="followup__hint">اكتب الإجابة في الأسفل، وسيكمل المساعد البلاغ نفسه.</div>}
      </div>
    </div>
  );
}
