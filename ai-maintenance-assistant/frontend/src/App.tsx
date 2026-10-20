import { useEffect, useRef, useState } from 'react';
import type { ChatMessage, ContinuationRequest, KnownTicket, MaintenanceRequest, MaintenanceResponse, TraceStep, UiState } from './types/maintenance';
import { continueRequest, createRequest, getRequest, USE_MOCK } from './services/maintenanceApi';
import { mockBackend } from './services/mockBackend';
import { SCENARIOS, type DemoScenario } from './demo/scenarios';
import Header from './components/Header';
import EmptyState from './components/EmptyState';
import ChatThread from './components/ChatThread';
import MaintenanceRequestForm from './components/MaintenanceRequestForm';
import SidePanel from './components/SidePanel';
import Icon from './components/Icon';

type LastCall = { kind: 'create'; body: MaintenanceRequest } | { kind: 'continue'; body: ContinuationRequest };
const HIDDEN_IN_SUMMARY = ['request_received', 'input_validation', 'wait_for_input', 'completed'];
const SAVED_THREAD = 'saai.activeThread.v1';

function savedThreadId(): string | null {
  if (USE_MOCK) return null;
  try {
    const value = sessionStorage.getItem(SAVED_THREAD);
    return value && /^th_[a-f0-9]{8,32}$/.test(value) ? value : null;
  } catch { return null; }
}

function saveThread(threadId: string | null) {
  if (USE_MOCK) return;
  try {
    if (threadId) sessionStorage.setItem(SAVED_THREAD, threadId);
    else sessionStorage.removeItem(SAVED_THREAD);
  } catch { /* Storage can be disabled; current-page requests still work. */ }
}

function knownFromResponse(previous: KnownTicket, response: MaintenanceResponse): KnownTicket {
  const known = { ...previous, missing: response.status === 'needs_information' ? response.missing_fields : [] };
  if ('asset' in response) {
    known.assetId = response.asset.asset_id; known.assetType = response.asset.asset_type;
    known.assetModel = response.asset.model; known.assetStatus = response.asset.status;
    known.location = response.asset.location;
  }
  if ('analysis' in response) {
    known.priority = response.analysis.priority ?? undefined;
    known.category = response.analysis.category ?? known.category;
    known.symptoms = response.analysis.symptoms ?? known.symptoms;
  }
  if ('ticket' in response) { known.ticketId = response.ticket.ticket_id; known.ticketStatus = response.ticket.status; }
  return known;
}

export default function App() {
  const [savedThread] = useState(savedThreadId);
  const [restoring, setRestoring] = useState(Boolean(savedThread));
  const [view, setView] = useState<UiState>(savedThread ? 'loading' : 'idle');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [known, setKnown] = useState<KnownTicket>({});
  const [threadId, setThreadId] = useState<string | null>(null);
  const [stepId, setStepId] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [tab, setTab] = useState<'ticket' | 'trace'>('ticket');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [lastCall, setLastCall] = useState<LastCall | null>(null);
  const idRef = useRef(0);
  const inFlight = useRef(false);
  const nextId = () => ++idRef.current;

  useEffect(() => {
    if (!savedThread) return;
    const controller = new AbortController();
    inFlight.current = true;
    getRequest(savedThread, controller.signal).then(response => {
      if (controller.signal.aborted) return;
      const restored: ChatMessage[] = [];
      if (response.description) restored.push({ id: ++idRef.current, kind: 'user', text: response.description, location: response.location ?? undefined });
      restored.push({ id: ++idRef.current, kind: 'result', response, active: true });
      setMessages(restored);
      setKnown(knownFromResponse({ description: response.description, location: response.location }, response));
      setTrace(response.trace ?? []);
      setThreadId(response.thread_id ?? savedThread);
      setStepId(response.status === 'needs_information' || response.status === 'needs_asset_selection' ? response.step_id : null);
      setRequestId(response.request_id);
      setView(response.status);
    }).finally(() => {
      if (!controller.signal.aborted) { inFlight.current = false; setRestoring(false); }
    });
    return () => controller.abort();
  }, [savedThread]);

  async function run(call: LastCall, userText?: string, location?: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    const workingId = nextId();
    const prevLen = call.kind === 'create' ? 0 : trace.length;
    setView('loading');
    setLastCall(call);
    setMessages(ms => [
      ...ms.map(m => (m.kind === 'result' ? { ...m, active: false } : m)),
      ...(userText ? [{ id: nextId(), kind: 'user' as const, text: userText, location }] : []),
      { id: workingId, kind: 'working', mode: call.kind, done: false, steps: [] },
    ]);

    let res: MaintenanceResponse;
    try {
      res = call.kind === 'create'
        ? await createRequest(call.body)
        : await continueRequest(threadId ?? '', call.body);
    } catch {
      res = { status: 'error', request_id: '—', message: 'تعذر تأكيد نتيجة البلاغ حاليًا.', retryable: false };
    } finally {
      inFlight.current = false;
    }
    const newTrace = res.trace ?? (call.kind === 'create' ? [] : trace);
    const newSteps = newTrace.slice(prevLen).filter(t => !HIDDEN_IN_SUMMARY.includes(t.step));

    setKnown(k => {
      const n = knownFromResponse(k, res);
      if (res.status !== 'error' && call.kind === 'continue' && call.body.input_type === 'text' && k.missing?.includes('location')) n.location = call.body.text;
      if ('asset' in res) n.location = res.asset.location;
      return n;
    });
    setTrace(newTrace);
    if (res.thread_id) { setThreadId(res.thread_id); saveThread(res.thread_id); }
    setStepId(res.status === 'needs_information' || res.status === 'needs_asset_selection' ? res.step_id : null);
    setRequestId(res.request_id);
    setView(res.status);
    setMessages(ms => [
      ...ms.map(m => (m.id === workingId && m.kind === 'working' ? { ...m, done: true, steps: newSteps } : m)),
      { id: nextId(), kind: 'result', response: res, active: true },
    ]);
  }

  function start(description: string, location: string, scenario?: DemoScenario) {
    if (inFlight.current) return;
    const d = description.trim();
    if (!d) return;
    if (scenario?.key === 'error' && USE_MOCK) mockBackend.failNext();
    const loc = location.trim() || null;
    setTrace([]);
    setThreadId(null);
    setRequestId(null);
    setKnown({ description: d, location: loc, missing: [] });
    run({ kind: 'create', body: { location: loc, description: d } }, d, loc ?? undefined);
  }

  function reset() {
    if (inFlight.current) return;
    setView('idle'); setMessages([]); setTrace([]); setKnown({});
    saveThread(null);
    setThreadId(null); setStepId(null); setRequestId(null); setLastCall(null);
    setTab('ticket'); setDetailsOpen(false);
  }

  const lastQuestion = [...messages].reverse().find(
    (m): m is Extract<ChatMessage, { kind: 'result' }> => m.kind === 'result' && m.response.status === 'needs_information',
  );
  const question = lastQuestion && lastQuestion.response.status === 'needs_information' ? lastQuestion.response.question : '';

  const formMode = restoring ? 'hidden' : messages.length === 0 ? 'new' : view === 'needs_information' ? 'answer' : 'hidden';
  const note = view === 'loading' ? 'المساعد يعالج البلاغ…'
    : view === 'needs_asset_selection' ? 'اختر الجهاز من القائمة أعلاه للمتابعة.'
    : view === 'error' ? 'تحقق من نتيجة الطلب قبل إنشاء بلاغ جديد.'
    : ['success', 'critical', 'asset_not_found'].includes(view) ? 'انتهى هذا البلاغ. ابدأ بلاغًا جديدًا من الأعلى.' : '';

  const composer = <MaintenanceRequestForm mode={formMode} question={question} note={note}
    onSubmit={(text, location) => formMode === 'answer'
      ? stepId && run({ kind: 'continue', body: { input_type: 'text', text, step_id: stepId } }, text)
      : start(text, location ?? '')} />;
  const stage = view === 'idle' ? 0 : view === 'success' || view === 'critical' ? 2 : 1;

  return (
    <div className="app" dir="rtl">
      <a className="skip-link" href="#maintenance-main">انتقل إلى البلاغ</a>
      <Header status={view} onNew={reset} onDetails={() => setDetailsOpen(true)} demo={USE_MOCK} />
      <div className="workspace-bar"><div className="workspace-bar__label"><Icon name="tool" /><span>مساحة الصيانة</span><span className="workspace-bar__divider">/</span><strong>{messages.length ? 'متابعة البلاغ' : 'بلاغ جديد'}</strong></div><ol className="journey" aria-label="مراحل البلاغ">{['وصف المشكلة', 'مراجعة التفاصيل', 'النتيجة'].map((label, index) => <li key={label} className={index < stage ? 'is-done' : index === stage ? 'is-current' : ''} aria-current={index === stage ? 'step' : undefined}><span>{index < stage ? <Icon name="check" /> : `0${index + 1}`}</span>{label}</li>)}</ol></div>
      <div className="layout">
        <main className={`chat${messages.length ? ' chat--active' : ''}`} id="maintenance-main" tabIndex={-1}>
          {restoring ? <div className="empty" role="status">جارٍ استعادة البلاغ…</div> : messages.length === 0
            ? <EmptyState scenarios={SCENARIOS.filter(s => USE_MOCK || s.key !== 'error')} onPick={s => start(s.description, s.location, s)}>{composer}</EmptyState>
            : <ChatThread
                messages={messages}
                onSelectAsset={assetId => stepId && run({ kind: 'continue', body: { input_type: 'asset_selection', asset_id: assetId, step_id: stepId } }, `الجهاز ${assetId}`)}
                onNew={reset}
                onShowTrace={() => { setTab('trace'); setDetailsOpen(true); }}
                onRetry={() => lastCall && run(lastCall)}
                onEdit={reset}
              />}
          {(messages.length > 0 || restoring) && composer}
        </main>
        <SidePanel tab={tab} onTab={setTab} known={known} view={view} started={messages.length > 0}
          trace={trace} threadId={threadId} requestId={requestId} open={detailsOpen} onClose={() => setDetailsOpen(false)} />
      </div>
      <footer className="app-footer"><span>ساعي · مساعد الصيانة</span><span>تفاصيل أوضح. إجراء أنسب.</span></footer>
    </div>
  );
}
