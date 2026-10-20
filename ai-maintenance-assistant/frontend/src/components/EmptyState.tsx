import type { ReactNode } from 'react';
import type { DemoScenario } from '../demo/scenarios';
import Icon, { type IconName } from './Icon';

const scenarioIcons: Record<string, IconName> = { normal: 'snow', missing: 'info', multi: 'printer', critical: 'bolt', notfound: 'tool', error: 'info' };

export default function EmptyState({ scenarios, onPick, children }: { scenarios: DemoScenario[]; onPick: (s: DemoScenario) => void; children: ReactNode }) {
  return (
    <div className="chat__scroll">
      <div className="empty">
        <div className="empty__intro">
          <div className="empty__eyebrow"><span className="eyebrow-line" />مساحة عمل الصيانة</div>
          <h1 className="empty__title">كل بلاغ،<br /><span className="accent">بداية حل.</span></h1>
          <p className="empty__lead">صِف المشكلة بكلماتك. نساعدك في تحديد الجهاز،<br className="desktop-break" /> وتوضيح الأولوية والخطوة المناسبة.</p>
          <div className="maintenance-mark" aria-hidden="true"><div className="maintenance-mark__orbit" /><div className="maintenance-mark__core"><Icon name="tool" /></div><span className="maintenance-mark__spark"><Icon name="spark" /></span></div>
        </div>
        {children}
        <div className="examples-heading"><div><div className="empty__label">جرّب بمثال جاهز</div><p>اختر مثالًا لإرساله وتجربة مسار البلاغ.</p></div><Icon name="arrow" /></div>
        <div className="presets">
          {scenarios.map(s => (
            <button key={s.key} className={`preset preset--${s.key}`} onClick={() => onPick(s)} aria-label={s.label}>
              <span className={`preset__symbol tone--${s.tone}`}><Icon name={scenarioIcons[s.key] ?? 'tool'} /></span>
              <span className="preset__body">
                <span className={`preset__tag tone--${s.tone}`}>{s.label}</span>
                <span className="preset__text">{s.description}</span>
                <span className="preset__loc"><Icon name="pin" />{s.location || 'الموقع يُحدد أثناء البلاغ'}</span>
              </span>
              <Icon name="arrow" className="preset__arrow" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
