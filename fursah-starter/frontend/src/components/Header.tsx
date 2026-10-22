
const LOGO_REMOTE = 'https://www.saai.sa/logo-white-cropped.svg';

export default function Header({ onEditProfile, onShowSaved, savedCount }: {
  onEditProfile: () => void; onShowSaved: () => void; savedCount: number;
}) {
  return (
    <header className="header">
      <div className="container header__inner">
        <div className="brand">
          <a className="brand__logo" href="https://www.saai.sa/" target="_blank" rel="noreferrer">
            <img
              src={LOGO_REMOTE}
              alt="ساعي"
              onError={e => { e.currentTarget.hidden = true; }}
            />
          </a>
          <div>
            <div className="brand__name">فرصة <span className="brand__latin">FURSAH</span></div>
            <div className="brand__tag">بيانات تدريبية خيالية · مشروع تعليمي</div>
          </div>
        </div>
        <div className="header__actions">
          <button className="btn btn--outline" onClick={onShowSaved}>
            <span aria-hidden="true">★</span> الفرص المهتم بها{savedCount ? ` (${savedCount})` : ''}
          </button>
          <button className="btn btn--outline" onClick={onEditProfile}>الملف الشخصي</button>
        </div>
      </div>
    </header>
  );
}
