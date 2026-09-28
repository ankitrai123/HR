import { useEffect, useRef, useState } from 'react';
import { candidate } from '../data/candidate';
import { test } from '../data/test';
import { Brand } from './Brand';
import { Maximize, Minimize, Settings } from './Icons';

export type TextSize = 'normal' | 'large';

function formatClock(ms: number) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, '0')).join(':');
}

function formatSaved(seconds: number) {
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'} ago`;
  const m = Math.floor(seconds / 60);
  return `${m} minute${m === 1 ? '' : 's'} ago`;
}

interface Props {
  remainingMs: number;
  savedSecondsAgo: number;
  textSize: TextSize;
  onTextSizeChange: (size: TextSize) => void;
  onFinish: () => void;
}

export function TestHeader({ remainingMs, savedSecondsAgo, textSize, onTextSizeChange, onFinish }: Props) {
  const [isFullscreen, setIsFullscreen] = useState(() => !!document.fullscreenElement);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  useEffect(() => {
    if (!settingsOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!settingsRef.current?.contains(e.target as Node)) setSettingsOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [settingsOpen]);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };

  const timerClass = remainingMs <= 60_000 ? 'critical' : remainingMs <= 5 * 60_000 ? 'warning' : '';

  return (
    <header className="test-header">
      <Brand compact />
      <div className="test-meta">
        <strong>{candidate.name}</strong>
        <span className="test-meta-sub">
          {test.title} <span className="dot" aria-hidden="true">•</span>{' '}
          <span className="saved">Saved: {formatSaved(savedSecondsAgo)}</span>
        </span>
      </div>
      <div className="test-header-actions">
        <div className={`timer ${timerClass}`} role="timer" aria-live="off">
          <span>Test Time:</span>
          <strong>{formatClock(remainingMs)}</strong>
        </div>
        <button className="icon-btn" onClick={toggleFullscreen} aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'} title="Fullscreen">
          {isFullscreen ? <Minimize /> : <Maximize />}
        </button>
        <div className="popover-anchor" ref={settingsRef}>
          <button className="icon-btn" onClick={() => setSettingsOpen((o) => !o)} aria-label="Settings" aria-expanded={settingsOpen} title="Settings">
            <Settings />
          </button>
          {settingsOpen && (
            <div className="popover" role="dialog" aria-label="Display settings">
              <span className="popover-label">Text size</span>
              <div className="segmented">
                {(['normal', 'large'] as const).map((size) => (
                  <button key={size} className={textSize === size ? 'active' : ''} onClick={() => onTextSizeChange(size)}>
                    {size === 'normal' ? 'Normal' : 'Large'}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <button className="btn btn-finish" onClick={onFinish}>Finish Test</button>
      </div>
    </header>
  );
}
