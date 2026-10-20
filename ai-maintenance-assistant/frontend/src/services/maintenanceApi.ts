import type { ContinuationRequest, MaintenanceRequest, MaintenanceResponse } from '../types/maintenance';
import { mockBackend } from './mockBackend';
import { responseSchema } from './responseSchema';

const BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api').replace(/\/$/, '');
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

const SAFE_ERROR = 'تعذر معالجة البلاغ حاليًا.';
const UNCERTAIN_RESULT = 'تعذر تأكيد نتيجة البلاغ. قد تكون المعالجة تمت؛ تحقق من النتيجة قبل إنشاء بلاغ جديد.';
const HTTP_ERRORS: Record<number, string> = {
  404: 'تعذر العثور على الطلب المطلوب استكماله.',
  409: 'تغيّرت خطوة البلاغ أو يجري تحديثه. حدّث الصفحة لعرض الحالة الحالية.',
  422: 'بيانات الطلب غير صالحة. تحقق من الحقول المطلوبة وطول النص.',
  502: 'تعذر فهم البلاغ من النموذج المحلي. يرجى إعادة صياغته والمحاولة.',
  503: 'النموذج المحلي غير جاهز. يرجى التواصل مع مسؤول النظام.',
};

async function request(url: string, method: 'POST' | 'GET', body?: unknown, signal?: AbortSignal): Promise<MaintenanceResponse> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(() => controller.abort(), 300_000);
  try {
    let res: Response;
    // A read may wait for an in-flight continuation. Only GET is retried.
    do {
      res = await fetch(url, { method,
        headers: { 'Content-Type': 'application/json' },
        ...(method === 'POST' ? { body: JSON.stringify(body) } : {}),
        signal: controller.signal });
      if (method === 'GET' && res.status === 409) await new Promise(resolve => setTimeout(resolve, 300));
    } while (method === 'GET' && res.status === 409 && !controller.signal.aborted);
    const json = await res.json().catch(() => ({}));
    const parsed = responseSchema.safeParse(json);
    if (!res.ok || !parsed.success) {
      // 404 unknown thread, 409 completed thread, 422 invalid body, 500 — never surface raw details.
      return { status: 'error', request_id: parsed.success ? parsed.data.request_id : '—',
        thread_id: parsed.success ? parsed.data.thread_id : undefined,
        ...(parsed.success && parsed.data.status === 'error' ? { error_code: parsed.data.error_code } : {}),
        message: res.status === 503 && parsed.success && parsed.data.status === 'error' && parsed.data.error_code === 'rag_unavailable'
          ? 'مراجع الصيانة غير جاهزة. يرجى التواصل مع مسؤول النظام.'
          : HTTP_ERRORS[res.status] ?? UNCERTAIN_RESULT, retryable: false };
    }
    if (parsed.data.status === 'error') return { ...parsed.data, message: SAFE_ERROR, retryable: false };
    return parsed.data;
  } catch {
    return { status: 'error', request_id: '—', message: UNCERTAIN_RESULT, retryable: false };
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}

export function createRequest(body: MaintenanceRequest): Promise<MaintenanceResponse> {
  if (USE_MOCK) return mockBackend.create(body).then(r => r.status === 'error' ? { ...r, retryable: true } : r);
  return request(`${BASE}/maintenance/requests`, 'POST', body);
}

export function continueRequest(threadId: string, body: ContinuationRequest): Promise<MaintenanceResponse> {
  if (USE_MOCK) return mockBackend.continue(threadId, body);
  return request(`${BASE}/maintenance/requests/${encodeURIComponent(threadId)}/continue`, 'POST', body);
}

export function getRequest(threadId: string, signal?: AbortSignal): Promise<MaintenanceResponse> {
  if (USE_MOCK) return mockBackend.read(threadId);
  return request(`${BASE}/maintenance/requests/${encodeURIComponent(threadId)}`, 'GET', undefined, signal);
}
