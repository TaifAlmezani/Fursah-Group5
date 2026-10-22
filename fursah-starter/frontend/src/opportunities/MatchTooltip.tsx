import { useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import type { MatchFactor } from '../types';

const ICON: Record<string, string> = { match: '✓', mismatch: '✕', unknown: '؟' };
const KIND_LABEL: Record<string, string> = { match: 'مطابقة مؤكدة', mismatch: 'غير مطابق', unknown: 'غير مؤكد' };

/**
 * Interactive match percentage. Hidden by default; opens on hover, on click/tap (pinned), and
 * on keyboard focus; Escape closes a pinned popover. The popover is rendered in a portal and
 * positioned with fixed coordinates computed from the trigger, so it is never clipped by the
 * card and flips above when there is no room below. Explanations come from the real scoring
 * signals passed in `factors`; nothing is invented here.
 */
export default function MatchTooltip({ score, factors }: { score: number; factors: MatchFactor[] }) {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<CSSProperties>({ top: -9999, left: -9999 });
  const id = useId();
  const open = hovered || pinned;
  const rounded = Math.round(score);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = triggerRef.current?.getBoundingClientRect();
      const pop = popRef.current;
      if (!t || !pop) return;
      const margin = 8, gap = 6;
      const vw = window.innerWidth, vh = window.innerHeight;
      const w = pop.offsetWidth, h = pop.offsetHeight;
      let top = t.bottom + gap;
      if (top + h > vh - margin) top = Math.max(margin, t.top - h - gap); // flip up
      let left = Math.min(Math.max(margin, t.right - w), vw - w - margin); // RTL: align right edges
      setPos({ top, left });
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, factors.length]);

  useLayoutEffect(() => {
    if (!pinned) return;
    const onDown = (e: MouseEvent) => {
      if (!triggerRef.current?.contains(e.target as Node) && !popRef.current?.contains(e.target as Node)) {
        setPinned(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [pinned]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="opp__score opp__score--btn"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-describedby={open ? id : undefined}
        aria-label={`الملاءمة ${rounded}٪ — اعرف سبب النسبة`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => setPinned(p => !p)}
        onKeyDown={e => {
          if (e.key === 'Escape') { setPinned(false); setHovered(false); triggerRef.current?.blur(); }
        }}
      >
        <small>الملاءمة</small>
        <strong>{rounded}%</strong>
      </button>

      {open && createPortal(
        <div
          ref={popRef}
          id={id}
          role="dialog"
          aria-label="تفسير نسبة الملاءمة"
          className="match-pop"
          dir="rtl"
          style={{ position: 'fixed', ...pos }}
        >
          <div className="match-pop__title">لماذا نسبة الملاءمة {rounded}%؟</div>
          {factors.length === 0 ? (
            <p className="match-pop__empty">لا توجد تفاصيل تفسيرية متاحة لهذه الفرصة.</p>
          ) : (
            <ul className="match-pop__list">
              {factors.map((f, i) => (
                <li key={i} className={`match-factor match-factor--${f.kind}`}>
                  <span className="match-factor__icon" aria-hidden="true">{ICON[f.kind] ?? '•'}</span>
                  <span className="match-factor__text">{f.text}</span>
                  <span className="sr-only"> ({KIND_LABEL[f.kind] ?? ''})</span>
                </li>
              ))}
            </ul>
          )}
          <p className="match-pop__note">مستمد من منطق الترتيب الفعلي؛ لا يؤكد الأهلية.</p>
        </div>,
        document.body,
      )}
    </>
  );
}
