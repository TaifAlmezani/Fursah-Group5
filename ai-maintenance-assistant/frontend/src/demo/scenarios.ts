export interface DemoScenario {
  key: string;
  label: string;
  tone: 'ok' | 'warn' | 'danger' | 'muted';
  location: string;
  description: string;
}

/** Presets only pre-fill the request. They never bypass the backend workflow. */
export const SCENARIOS: DemoScenario[] = [
  { key: 'normal', label: 'بلاغ طبيعي', tone: 'ok', location: 'غرفة الاجتماعات B12', description: 'المكيف يهرب موية وصوته عالي' },
  { key: 'missing', label: 'معلومات ناقصة', tone: 'warn', location: '', description: 'المكيف خربان' },
  { key: 'multi', label: 'أكثر من جهاز', tone: 'warn', location: 'الدور الثالث', description: 'الطابعة تعلق الورق وما تطبع' },
  { key: 'critical', label: 'حالة سلامة حرجة', tone: 'danger', location: 'غرفة الاجتماعات B12', description: 'المكيف يهرب موية على اللوحة الكهربائية' },
  { key: 'notfound', label: 'جهاز غير مسجل', tone: 'muted', location: 'المستودع 7', description: 'السخان ما يشتغل' },
  { key: 'error', label: 'تعطل الخادم', tone: 'danger', location: 'غرفة 204', description: 'الإضاءة تفصل وترجع' },
];
