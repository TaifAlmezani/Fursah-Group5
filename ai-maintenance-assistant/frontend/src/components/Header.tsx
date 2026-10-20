import type { UiState } from '../types/maintenance';
import { STATUS_AR } from '../labels';
import Icon from './Icon';

const LOGO_LOCAL = '/logo-white.svg';
const LOGO_REMOTE = 'https://www.saai.sa/logo-white-cropped.svg';

export default function Header({ status, onNew, onDetails, demo }: { status: UiState; onNew: () => void; onDetails: () => void; demo: boolean }) {
  return (
    <header className="header">
      <a className="header__logo" href="https://www.saai.sa/" target="_blank" rel="noreferrer">
        <img src={LOGO_LOCAL} alt="ساعي" onError={e => { const i = e.currentTarget; if (i.src !== LOGO_REMOTE) i.src = LOGO_REMOTE; }} />
      </a>
      <div className="header__titles">
        <div className="header__title">مساعد الصيانة <span className="header__badge">ساعي</span></div>
        <div className="header__sub">من وصف المشكلة إلى الخطوة التالية.</div>
        {demo && <div className="header__sub">عرض تجريبي — بيانات محاكاة</div>}
      </div>
      <div className={`status-pill status-pill--${status}`} role="status">
        <span className="status-pill__dot" />
        <span>{STATUS_AR[status]}</span>
      </div>
      <button className="btn btn--outline btn--sm header__new" disabled={status === 'loading'} onClick={onNew}><Icon name="plus" />بلاغ جديد</button>
      <button className="btn btn--outline btn--sm header__details" onClick={onDetails}><Icon name="ticket" />تفاصيل البلاغ</button>
    </header>
  );
}
