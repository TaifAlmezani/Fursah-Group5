import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { KnownTicket, TraceStep, UiState } from '../types/maintenance';
import TicketCard from './TicketCard';
import ExecutionTrace from './ExecutionTrace';
import Icon from './Icon';

interface Props {
  tab: 'ticket' | 'trace';
  onTab: (t: 'ticket' | 'trace') => void;
  known: KnownTicket;
  view: UiState;
  started: boolean;
  trace: TraceStep[];
  threadId: string | null;
  requestId: string | null;
  open: boolean;
  onClose: () => void;
}

function containTabFocus(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== 'Tab') return;
  const elements = [...event.currentTarget.querySelectorAll<HTMLElement>('button, a[href], input, textarea, [tabindex]')]
    .filter(element => element.tabIndex >= 0 && !element.hasAttribute('disabled') && element.getClientRects().length > 0);
  const first = elements[0];
  const last = elements[elements.length - 1];
  if (first && last && ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last))) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}

export default function SidePanel({ tab, onTab, known, view, started, trace, threadId, requestId, open, onClose }: Props) {
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setMobile(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (!mobile || !dialog.current) return;
    const element = dialog.current;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [mobile, open]);

  const content = <>
    <div className="side__heading"><div><span className="side__eyebrow">في مكان واحد</span><h2 id={`${id}-title`}>تفاصيل البلاغ</h2></div>{mobile ? <button className="icon-button" aria-label="إغلاق تفاصيل البلاغ" onClick={onClose}><Icon name="close" /></button> : <Icon name="ticket" />}</div>
    <div className="tabs" role="tablist" aria-label="تفاصيل البلاغ" onKeyDown={e => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
        e.preventDefault();
        const next = e.key === 'Home' ? 'ticket' : e.key === 'End' ? 'trace' : tab === 'ticket' ? 'trace' : 'ticket';
        onTab(next);
        e.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus();
      }
    }}>
      <button id={`${id}-ticket`} data-tab="ticket" role="tab" aria-controls={`${id}-panel`} aria-selected={tab === 'ticket'} tabIndex={tab === 'ticket' ? 0 : -1} className={`tab${tab === 'ticket' ? ' is-active' : ''}`} onClick={() => onTab('ticket')}><Icon name="ticket" />البلاغ</button>
      <button id={`${id}-trace`} data-tab="trace" role="tab" aria-controls={`${id}-panel`} aria-selected={tab === 'trace'} tabIndex={tab === 'trace' ? 0 : -1} className={`tab${tab === 'trace' ? ' is-active' : ''}`} onClick={() => onTab('trace')}><Icon name="list" />مسار التنفيذ {trace.length > 0 && <span className="tab__count">{trace.length}</span>}</button>
    </div>
    <div className="side__body" id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} tabIndex={0}>
      {tab === 'ticket' ? <TicketCard known={known} view={view} started={started} /> : <ExecutionTrace trace={trace} threadId={threadId} requestId={requestId} />}
      {!started && tab === 'ticket' && <div className="side-guide"><Icon name="pin" /><div><strong>الموقع يصنع الفرق</strong><p>اسم المبنى، الدور أو رقم الغرفة يساعدنا نوصل للجهاز الصحيح.</p></div></div>}
    </div>
    <div className="side__foot"><Icon name="shield" /><span>الأولوية تتحدد حسب تفاصيل البلاغ ومخاطر السلامة.</span></div>
  </>;

  return mobile
    ? <dialog ref={dialog} className="side side--dialog" aria-labelledby={`${id}-title`} onKeyDown={containTabFocus} onCancel={onClose} onClose={onClose}>{content}</dialog>
    : <aside className="side" aria-labelledby={`${id}-title`}>{content}</aside>;
}
