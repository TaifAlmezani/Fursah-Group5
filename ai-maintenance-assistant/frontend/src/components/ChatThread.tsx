import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../types/maintenance';
import WorkingMessage from './WorkingMessage';
import SuccessResult from './results/SuccessResult';
import CriticalResult from './results/CriticalResult';
import FollowUpResult from './results/FollowUpResult';
import AssetSelectionResult from './results/AssetSelectionResult';
import AssetNotFoundResult from './results/AssetNotFoundResult';
import ErrorResult from './results/ErrorResult';

interface Props {
  messages: ChatMessage[];
  onSelectAsset: (assetId: string) => void;
  onNew: () => void;
  onShowTrace: () => void;
  onRetry: () => void;
  onEdit: () => void;
}

export default function ChatThread({ messages, onSelectAsset, onNew, onShowTrace, onRetry, onEdit }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    ref.current?.querySelector('.thread__item:last-child')?.scrollIntoView({ block: 'nearest', behavior: reduced ? 'instant' : 'smooth' });
  }, [messages]);

  return (
    <div className="chat__scroll" ref={ref}>
      <div className="thread">
        {messages.map(m => (
          <div key={m.id} className="thread__item">
            {m.kind === 'user' && (
              <div className="msg-user">
                {m.location && <div className="msg-user__loc"><span className="ring" />{m.location}</div>}
                <div className="msg-user__bubble">{m.text}</div>
              </div>
            )}
            {m.kind === 'working' && <WorkingMessage msg={m} onShowTrace={onShowTrace} />}
            {m.kind === 'result' && (() => {
              const r = m.response;
              switch (r.status) {
                case 'success': return <SuccessResult r={r} active={m.active} onNew={onNew} onShowTrace={onShowTrace} />;
                case 'critical': return <CriticalResult r={r} active={m.active} onNew={onNew} />;
                case 'needs_information': return <FollowUpResult r={r} active={m.active} />;
                case 'needs_asset_selection': return <AssetSelectionResult r={r} active={m.active} onConfirm={onSelectAsset} />;
                case 'asset_not_found': return <AssetNotFoundResult r={r} active={m.active} onEdit={onEdit} />;
                case 'error': return <ErrorResult r={r} active={m.active} onRetry={onRetry} onNew={onNew} />;
              }
            })()}
          </div>
        ))}
      </div>
    </div>
  );
}
