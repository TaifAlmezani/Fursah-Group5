import type { ReactNode } from 'react';

interface Props {
  tone: 'ok' | 'danger' | 'muted' | 'error';
  icon: string;
  title: string;
  subtitle?: string;
  ticketId?: string;
  children?: ReactNode;
}

export default function ResultCard({ tone, icon, title, subtitle, ticketId, children }: Props) {
  return (
    <div className="agent-row">
      <div className="avatar avatar--spacer" />
      <section className={`result result--${tone}`}>
        <header className="result__head">
          <span className="result__icon">{icon}</span>
          <div className="result__titles">
            <div className="result__title">{title}</div>
            {subtitle && <div className="result__sub">{subtitle}</div>}
          </div>
          {ticketId && <span className="mono result__ticket" dir="ltr">{ticketId}</span>}
        </header>
        <div className="result__body">{children}</div>
      </section>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <div className="field__label">{label}</div>
      <div className="field__value">{children}</div>
    </div>
  );
}
