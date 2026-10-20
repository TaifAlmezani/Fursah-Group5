/**
 * In-browser stand-in for the FastAPI backend (VITE_USE_MOCK=true).
 * Returns responses shaped exactly like the Stage 4 contracts.
 * Keyword routing is demo-only; the real backend uses LangGraph + ASL-4B-v1 + policies.
 */
import type { Asset, ContinuationRequest, MaintenanceRequest, MaintenanceResponse, Priority, TraceStep } from '../types/maintenance';
import { PRIORITY_AR, SYMPTOM_AR, TYPE_AR } from '../labels';

interface Extraction { asset_type: string | null; symptoms: string[]; safety_signals: string[] }
interface Thread {
  request_id: string; thread_id: string; location: string; description: string;
  ex: Extraction; trace: TraceStep[]; candidates: Asset[]; selected?: Asset;
  waiting?: 'location' | 'description' | 'asset'; done?: boolean;
  step_id?: string; lastResponse?: MaintenanceResponse;
}

const CATEGORY_OF: Record<string, string> = {
  air_conditioner: 'air_conditioning', printer: 'printing', electrical_panel: 'electrical',
  lighting: 'electrical', water_heater: 'plumbing', plumbing: 'plumbing',
};
const hex = () => Math.random().toString(16).slice(2, 6).toUpperCase();
const rnd = (a: number, b: number) => Math.round(a + Math.random() * (b - a));
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

const threads: Record<string, Thread> = {};
let ticketNo = 1042;
let forceError = false;

function extract(d: string): Extraction {
  let t: string | null = null;
  if (/مكيف|تكييف/.test(d)) t = 'air_conditioner';
  else if (/طابع/.test(d)) t = 'printer';
  else if (/سخان/.test(d)) t = 'water_heater';
  else if (/إضاءة|اضاءة|لمبة|نور/.test(d)) t = 'lighting';
  else if (/لوحة|كهرب/.test(d)) t = 'electrical_panel';
  else if (/موية|مياه|تسرب|مغسلة/.test(d)) t = 'plumbing';
  const s: string[] = [];
  if (/موية|مياه|تسرب|يهرب/.test(d)) s.push('water_leak');
  if (/صوت|إزعاج|ازعاج/.test(d)) s.push('abnormal_noise');
  if (/ورق|تعلق/.test(d)) s.push('paper_jam');
  if (/ما يبرد|حار/.test(d)) s.push('not_cooling');
  if (/تفصل|ترجع/.test(d)) s.push('flickering');
  if (/ما يشتغل|ما تطبع|خربان|خربانة|عطلان/.test(d) && !s.length) s.push('not_working');
  const safety = s.includes('water_leak') && /كهرب|لوحة|فيش|أفياش/.test(d) ? ['water_leak', 'electrical_risk'] : [];
  return { asset_type: t, symptoms: s, safety_signals: safety };
}

function resolve(loc: string, type: string | null): Asset[] {
  if (/مستودع/.test(loc)) return [];
  if (type === 'printer' && /الثالث|الدور/.test(loc))
    return ['301', '305', '310'].map(r => ({ asset_id: `PR-${r}-01`, asset_type: 'printer', location: `غرفة ${r}`, status: 'active' }));
  const code = (loc.match(/[A-Za-z]?\d+/) ?? ['G01'])[0].toUpperCase();
  const pre = ({ air_conditioner: 'AC', printer: 'PR', electrical_panel: 'EP', water_heater: 'WH', plumbing: 'PL', lighting: 'LT' } as Record<string, string>)[type ?? ''] ?? 'GN';
  return [{ asset_id: `${pre}-${code}-${type === 'air_conditioner' ? '02' : '01'}`, asset_type: type ?? 'unknown', location: loc, status: 'active' }];
}

function step(th: Thread, name: string, details: string | null, ms: number | null = rnd(4, 30), status: TraceStep['status'] = 'completed') {
  th.trace.push({ step: name, status, details, duration_ms: ms });
}
const out = (th: Thread, o: { status: string; [key: string]: unknown }) => {
  if (o.status === 'needs_information' || o.status === 'needs_asset_selection') th.step_id = crypto.randomUUID();
  const response = { request_id: th.request_id, thread_id: th.thread_id,
    ...(o.status.startsWith('needs_') ? { step_id: th.step_id } : {}), ...o, trace: th.trace.slice() } as MaintenanceResponse;
  th.lastResponse = response;
  return response;
};

function runFrom(th: Thread, from: 'complete' | 'sop'): MaintenanceResponse {
  const ex = th.ex;
  const noun = TYPE_AR[ex.asset_type ?? ''] ? 'ال' + TYPE_AR[ex.asset_type!] : 'الجهاز';
  if (from === 'complete') {
    const missing: string[] = [];
    if (!th.location) missing.push('location');
    if (!ex.asset_type) missing.push('asset_type');
    step(th, 'check_completeness', missing.length ? `ناقص: ${missing.join(', ')}` : 'المعلومات مكتملة');
    if (missing.length) {
      step(th, 'wait_for_input', 'تم إيقاف سير العمل مؤقتًا', 0);
      th.waiting = missing.includes('location') ? 'location' : 'description';
      return out(th, {
        status: 'needs_information', missing_fields: missing,
        question: missing.includes('location') ? `في أي غرفة أو موقع يوجد ${noun}؟` : 'ما نوع الجهاز الذي يواجه المشكلة؟',
      });
    }
    const c = (th.candidates = resolve(th.location, ex.asset_type));
    step(th, 'asset_lookup', c.length === 0 ? 'لا توجد نتائج' : c.length > 1 ? `${c.length} نتائج مطابقة` : c[0].asset_id, rnd(8, 20));
    if (!c.length) { th.done = true; return out(th, { status: 'asset_not_found', message: 'تعذر العثور على جهاز مسجل يطابق الموقع والبلاغ.' }); }
    if (c.length > 1) {
      step(th, 'wait_for_input', 'بانتظار اختيار الجهاز', 0);
      th.waiting = 'asset';
      return out(th, { status: 'needs_asset_selection', message: `حدد ${noun} المقصودة:`, assets: c });
    }
    th.selected = c[0];
  }
  const a = th.selected!;
  const src = ({ air_conditioning: 'air_conditioning.md', printing: 'printers.md', electrical: 'electrical.md', plumbing: 'plumbing.md' } as Record<string, string>)[CATEGORY_OF[ex.asset_type ?? '']] ?? 'plumbing.md';
  step(th, 'retrieve_sop', `تم استرجاع 3 مقاطع\nالمصدر: ${src}`, rnd(60, 140));
  const crit = ex.safety_signals.length > 0;
  const pri: Priority = crit ? 'critical' : ex.symptoms.includes('water_leak') ? 'high' : 'medium';
  step(th, 'evaluate_safety', `الأولوية: ${PRIORITY_AR[pri]}\nالتصعيد: ${crit ? 'نعم' : 'لا'}`, rnd(1, 4));
  const tid = `MNT-${ticketNo++}`;
  step(th, 'create_ticket', tid, rnd(8, 18));
  const total = th.trace.reduce((s, t) => s + (t.duration_ms ?? 0), 0);
  step(th, 'completed', `الزمن الكلي: ${(total / 1000).toFixed(2)} ثانية`, null);
  th.done = true;
  const action = crit ? 'إبعاد الأشخاص عن المنطقة واتباع إجراءات السلامة الكهربائية.'
    : ex.asset_type === 'air_conditioner' && ex.symptoms.includes('water_leak') ? 'فحص تصريف المياه وصينية التصريف.'
    : ex.asset_type === 'air_conditioner' ? 'فحص وحدة التكييف والتأكد من سلامة الفلاتر والتوصيلات.'
    : ex.asset_type === 'printer' ? 'فتح مسار الورق وإزالة الورق العالق وفحص البكرات.'
    : 'فحص الجهاز وفق إجراء الصيانة المعتمد.';
  const asset = { asset_id: a.asset_id, asset_type: a.asset_type, location: a.location };
  if (crit) return out(th, {
    status: 'critical', ticket: { ticket_id: tid, status: 'escalated' }, asset,
    analysis: { priority: 'critical', safety_signals: ex.safety_signals },
    safety_message: 'تسرب مياه بالقرب من معدات كهربائية.', recommended_action: action,
  });
  return out(th, {
    status: 'success', ticket: { ticket_id: tid, status: 'created' }, asset,
    analysis: { category: CATEGORY_OF[a.asset_type], priority: pri, symptoms: ex.symptoms }, recommended_action: action,
  });
}

export const mockBackend = {
  /** Demo helper: make the next create() fail at asset_lookup. */
  failNext() { forceError = true; },

  async create(body: MaintenanceRequest): Promise<MaintenanceResponse> {
    await sleep(2300);
    const th: Thread = {
      request_id: `REQ-${hex()}`, thread_id: `THR-${hex()}`, location: (body.location ?? '').trim(),
      description: body.description, ex: extract(body.description), trace: [], candidates: [],
    };
    threads[th.thread_id] = th;
    step(th, 'request_received', null, 1);
    step(th, 'input_validation', null, 1);
    const ex = th.ex;
    const lines = ['النموذج: ASL-4B-v1', `النوع: ${TYPE_AR[ex.asset_type ?? ''] ?? 'غير محدد'}`];
    if (ex.symptoms.length) lines.push('الأعراض:', ...ex.symptoms.map(s => '- ' + SYMPTOM_AR[s]));
    if (ex.safety_signals.length) lines.push('إشارات السلامة: ' + ex.safety_signals.map(s => SYMPTOM_AR[s]).join('، '));
    step(th, 'issue_extraction', lines.join('\n'), rnd(290, 420));
    if (forceError) {
      forceError = false;
      step(th, 'asset_lookup', 'ASSET_DB_UNAVAILABLE', rnd(1000, 1200), 'failed');
      return { status: 'error', request_id: th.request_id, message: 'تعذر معالجة البلاغ حاليًا.', trace: th.trace.slice() };
    }
    return runFrom(th, 'complete');
  },

  async continue(threadId: string, body: ContinuationRequest): Promise<MaintenanceResponse> {
    await sleep(1800);
    const th = threads[threadId];
    if (!th || th.done || body.step_id !== th.step_id) return { status: 'error', request_id: '—', message: 'تعذر متابعة هذا البلاغ.' };
    if ((body.input_type === 'asset_selection') !== (th.waiting === 'asset')) return { status: 'error', request_id: '—', message: 'نوع الإجابة لا يطابق السؤال الحالي.' };
    step(th, 'resume', body.input_type === 'text' ? `إدخال المستخدم: ${body.text}` : `تم اختيار: ${body.asset_id}`, 1);
    if (body.input_type === 'asset_selection') {
      th.selected = th.candidates.find(c => c.asset_id === body.asset_id);
      if (!th.selected) return { status: 'error', request_id: '—', message: 'اختيار الجهاز غير صالح.' };
      return runFrom(th, 'sop');
    }
    if (th.waiting === 'location') th.location = body.text.trim();
    else { th.description += ' ' + body.text; th.ex = extract(th.description); }
    return runFrom(th, 'complete');
  },
  async read(threadId: string): Promise<MaintenanceResponse> {
    const th = threads[threadId];
    if (!th?.lastResponse) return { status: 'error', request_id: '—', message: 'تعذر العثور على الطلب.' };
    return { ...th.lastResponse, description: th.description, location: th.location };
  },
};
