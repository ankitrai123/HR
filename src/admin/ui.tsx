import { useState, type ReactNode } from 'react';
import { Check, Copy } from '../components/Icons';
import type { InvitationStatus } from './types';

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

export const formatDateTime = (iso: string | null | undefined) => (iso ? dateTime.format(new Date(iso)) : '–');
export const formatDate = (iso: string | null | undefined) => (iso ? dateOnly.format(new Date(iso)) : '–');

export const STATUS_LABELS: Record<InvitationStatus, string> = {
  sent: 'Not opened',
  opened: 'Opened',
  in_progress: 'In progress',
  completed: 'Completed',
  expired: 'Expired',
  revoked: 'Revoked',
};

export function StatusBadge({ status }: { status: InvitationStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function CopyButton({ text, label = 'Copy link', className = 'btn btn-outline btn-sm' }: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API unavailable (e.g. non-secure context): fall back to a prompt.
      window.prompt('Copy this link:', text);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <button type="button" className={className} onClick={() => void copy()}>
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : label}
    </button>
  );
}

export function ErrorNote({ error }: { error: string }) {
  return error ? <p className="error-text" role="alert">{error}</p> : null;
}

export const errorMessage = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');
