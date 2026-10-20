import type { Priority, UiState } from './types/maintenance';

export const TYPE_AR: Record<string, string> = {
  air_conditioner: 'مكيف', printer: 'طابعة', electrical_panel: 'لوحة كهربائية',
  water_heater: 'سخان', plumbing: 'تمديدات مياه', lighting: 'إضاءة',
  electrical: 'معدات كهربائية', other: 'جهاز آخر',
};
export const CATEGORY_AR: Record<string, string> = {
  air_conditioning: 'تكييف', printing: 'طباعة', electrical: 'كهرباء', plumbing: 'سباكة',
  general: 'صيانة عامة',
};
export const SYMPTOM_AR: Record<string, string> = {
  water_leak: 'تسرب مياه', abnormal_noise: 'صوت غير طبيعي', paper_jam: 'انحشار الورق',
  not_cooling: 'ضعف التبريد', not_working: 'الجهاز لا يعمل', electrical_risk: 'خطر كهربائي',
  flickering: 'انقطاع متكرر',
  low_cooling: 'ضعف التبريد', power_issue: 'مشكلة في التغذية الكهربائية',
  overheating: 'ارتفاع الحرارة', smoke: 'دخان',
};
export const PRIORITY_AR: Record<Priority, string> = { low: 'منخفضة', medium: 'متوسطة', high: 'مرتفعة', critical: 'حرجة' };
export const STEP_AR: Record<string, string> = {
  request_received: 'استلام الطلب', input_validation: 'التحقق من البيانات', issue_extraction: 'تحليل المشكلة',
  check_completeness: 'التحقق من اكتمال المعلومات', asset_lookup: 'البحث عن الأصل', wait_for_input: 'بانتظار المستخدم',
  resume: 'استئناف سير العمل', retrieve_sop: 'استرجاع إجراء الصيانة', evaluate_safety: 'تقييم السلامة',
  create_ticket: 'إنشاء البلاغ', completed: 'اكتملت المعالجة',
  extract_issue: 'تحليل المشكلة', lookup_asset: 'البحث عن الأصل',
  apply_clarification: 'تطبيق المعلومات الإضافية', apply_asset_selection: 'اعتماد اختيار الجهاز',
  evaluate_policy: 'تقييم الأولوية والسلامة', compose_recommendation: 'إعداد التوصية',
  recommendation_generation: 'توليد التوصية', finalize_response: 'إعداد النتيجة',
  handle_error: 'معالجة الخطأ',
};
export const STATUS_AR: Record<UiState, string> = {
  idle: 'جاهز', loading: 'جاري المعالجة', needs_information: 'نحتاج معلومات إضافية',
  needs_asset_selection: 'حدد الجهاز', success: 'تم إنشاء البلاغ', critical: 'حالة حرجة',
  asset_not_found: 'تعذر العثور على الجهاز', error: 'حدث خطأ',
};
export const LOADING_NEW = ['استلام الطلب', 'تحليل المشكلة', 'التحقق من اكتمال المعلومات', 'البحث عن الجهاز', 'استرجاع إجراء الصيانة', 'تقييم الأولوية والسلامة'];
export const LOADING_CONTINUE = ['استئناف البلاغ نفسه', 'التحقق من الجهاز', 'استرجاع إجراء الصيانة', 'تقييم الأولوية والسلامة', 'إنشاء البلاغ'];

export const symptomsText = (s?: string[], sep = ' مع ') => (s ?? []).map(x => SYMPTOM_AR[x] ?? x).join(sep);
