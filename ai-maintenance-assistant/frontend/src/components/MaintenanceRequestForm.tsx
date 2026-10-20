import { useId, useState } from 'react';
import Icon from './Icon';

interface Props {
  mode: 'new' | 'answer' | 'hidden';
  question?: string;
  note?: string;
  onSubmit: (text: string, location?: string) => void;
}

/** Collects the problem description (first turn) or a follow-up answer (same thread). */
export default function MaintenanceRequestForm({ mode, question, note, onSubmit }: Props) {
  const [text, setText] = useState('');
  const [location, setLocation] = useState('');
  const fieldId = useId();
  const answering = mode === 'answer';
  const submit = () => {
    const t = text.trim();
    if (!t) return;
    onSubmit(t, answering ? undefined : location.trim());
    setText('');
    setLocation('');
  };

  if (mode === 'hidden') return <div className="composer-wrap">{note && <div className="composer-note">{note}</div>}</div>;

  return (
    <div className="composer-wrap">
      <form className={`composer${answering ? ' composer--answer' : ''}`} onSubmit={e => { e.preventDefault(); submit(); }}>
        <label className="composer__label" htmlFor={`${fieldId}-description`}><Icon name={answering ? 'info' : 'tool'} />{answering ? 'نكمل تفاصيل البلاغ' : 'وش المشكلة اللي تواجهك؟'}</label>
        {answering && question && <div className="composer__context">إجابة على: {question}</div>}
        <div className="composer__row">
          <textarea
            id={`${fieldId}-description`}
            rows={3}
            maxLength={answering ? 2000 : 4000}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
            placeholder={answering ? 'اكتب إجابتك…' : 'صف المشكلة… مثال: المكيف يهرب موية وصوته عالي'}
            aria-label={answering ? 'إجابة المتابعة' : 'وصف المشكلة'}
          />
        </div>
        {!answering && <div className="composer__location"><Icon name="pin" /><label className="sr-only" htmlFor={`${fieldId}-location`}>الموقع (اختياري)</label><input id={`${fieldId}-location`} value={location} onChange={e => setLocation(e.target.value)} maxLength={2000} placeholder="الموقع (اختياري) — مثل: غرفة B12" /></div>}
        <div className="composer__footer">
          <span className="composer__tip">{answering ? 'إجابتك تُكمل نفس البلاغ.' : 'اذكر الجهاز والعطل. والباقي خطوة بخطوة.'}</span>
          <button type="submit" className={`btn ${answering ? 'btn--warn' : 'btn--primary'}`} disabled={!text.trim()}>
            {answering ? 'متابعة ←' : 'تحليل البلاغ ←'}
          </button>
        </div>
      </form>
    </div>
  );
}
