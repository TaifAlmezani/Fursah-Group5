import type { KnownTicket, UiState } from '../types/maintenance';
import { CATEGORY_AR, PRIORITY_AR, TYPE_AR, symptomsText } from '../labels';
import Icon from './Icon';

/** Mirrors backend-provided data only. The frontend never infers priority or asset type. */
export default function TicketCard({ known: k, view, started }: { known: KnownTicket; view: UiState; started: boolean }) {
  const escalated = k.ticketStatus === 'escalated';
  const stamp = escalated ? 'تم التصعيد' : k.ticketId ? 'تم الإنشاء'
    : view === 'asset_not_found' ? 'لم يُنشأ' : view === 'error' ? 'متوقف' : started ? 'مسودة' : 'فارغ';
  const stampTone = escalated ? 'danger' : k.ticketId ? 'ok' : 'muted';
  const missingLocation = k.missing?.includes('location');

  const rows: { label: string; value?: string | null; ltr?: boolean; missing?: boolean; cls?: string }[] = [
    { label: 'الوصف', value: k.description },
    { label: 'الموقع', value: k.location, missing: missingLocation },
    { label: 'الأصل', value: k.assetId, ltr: true },
    { label: 'الموديل', value: k.assetId ? k.assetModel || 'غير متوفر' : undefined },
    { label: 'حالة الجهاز', value: k.assetId ? k.assetStatus === 'active' ? 'بالخدمة' : k.assetStatus === 'inactive' ? 'خارج الخدمة' : 'غير متوفرة' : undefined },
    { label: 'التصنيف', value: k.category ? CATEGORY_AR[k.category] ?? k.category : k.assetType ? TYPE_AR[k.assetType] : '' },
    { label: 'الأعراض', value: symptomsText(k.symptoms, '، ') },
    { label: 'الأولوية', value: k.priority ? PRIORITY_AR[k.priority] : '', cls: k.priority ? `pri pri--${k.priority}` : '' },
    { label: 'الحالة', value: k.ticketStatus ? (escalated ? 'تم التصعيد' : 'تم الإنشاء') : '' },
  ];

  if (!started) return <div className="ticket ticket--empty"><div className="ticket-empty__art" aria-hidden="true"><Icon name="ticket" /><span><Icon name="plus" /></span></div><div className="ticket-empty__label">من المشكلة إلى الإجراء</div><h3>بلاغك يبدأ من هنا</h3><p>بعد وصف المشكلة، تظهر تفاصيل البلاغ والجهاز والأولوية في هذا المكان.</p><ol className="ticket-empty__steps"><li><span>01</span>صِف المشكلة ومكانها</li><li><span>02</span>نراجع التفاصيل معك</li><li><span>03</span>تستلم البلاغ والتوصية</li></ol></div>;

  return (
    <div className={`ticket${escalated ? ' ticket--critical' : ''}`}>
      <div className="ticket__head">
        <div>
          <div className="ticket__kicker">بلاغ صيانة</div>
          <div className={`ticket__id mono${k.ticketId ? '' : ' is-empty'}`} dir="ltr">{k.ticketId ?? 'MNT-····'}</div>
        </div>
        <div className={`ticket__stamp tone--${stampTone}`}>{stamp}</div>
      </div>
      <dl className="ticket__rows">
        {rows.map(r => (
          <div key={r.label} className="ticket__row">
            <dt>{r.label}</dt>
            <dd dir={r.ltr ? 'ltr' : undefined} className={[r.value ? '' : r.missing ? 'is-missing' : 'is-empty', r.cls ?? ''].join(' ')}>
              {r.value || (r.missing ? 'مطلوب — بانتظار إجابتك' : '—')}
            </dd>
          </div>
        ))}
      </dl>
      <p className="ticket__foot">{k.ticketId ? 'احتفظ برقم البلاغ للمتابعة مع فريق الصيانة.' : 'تكتمل التفاصيل مع تقدم البلاغ.'}</p>
    </div>
  );
}
