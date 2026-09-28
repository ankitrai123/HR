import { useState } from 'react';
import { Bell, X } from './Icons';

const DISMISS_KEY = 'psychometric:notificationPrompt';

function initiallyVisible() {
  if (typeof Notification === 'undefined' || Notification.permission !== 'default') return false;
  try {
    return localStorage.getItem(DISMISS_KEY) !== 'dismissed';
  } catch {
    return true;
  }
}

export function NotificationBanner() {
  const [visible, setVisible] = useState(initiallyVisible);
  if (!visible) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, 'dismissed');
    } catch {
      // ignore
    }
    setVisible(false);
  };

  const enable = async () => {
    try {
      await Notification.requestPermission();
    } finally {
      dismiss();
    }
  };

  return (
    <div className="notice-banner" role="region" aria-label="Notifications">
      <Bell size={16} />
      <span>Get notified about registration deadlines and assessment updates.</span>
      <div className="notice-actions">
        <button className="btn btn-sm btn-primary" onClick={enable}>Enable</button>
        <button className="btn btn-sm btn-ghost-light" onClick={dismiss}>Later</button>
      </div>
      <button className="icon-btn notice-close" onClick={dismiss} aria-label="Dismiss">
        <X size={14} />
      </button>
    </div>
  );
}
