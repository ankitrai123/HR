import { API_BASE, parseError } from '../api';

export type InviteStatus = 'sent' | 'opened' | 'in_progress' | 'completed' | 'expired' | 'revoked' | 'invalid';

export interface InviteResponse {
  status: InviteStatus;
  organization: string;
  support: { email: string; phone: string };
  candidate?: { name: string; email: string | null; employee_code: string; department: string | null };
  window?: { opens: string; closes: string };
  started_at?: string | null;
  duration_minutes?: number;
}

const url = (token: string, suffix = '') => `${API_BASE}/api/invite/${encodeURIComponent(token)}${suffix}`;

export async function fetchInvite(token: string): Promise<InviteResponse> {
  const res = await fetch(url(token));
  if (res.status === 404) {
    return { status: 'invalid', organization: '', support: { email: '', phone: '' } };
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function startInvite(token: string): Promise<number> {
  const res = await fetch(url(token, '/start'), { method: 'POST' });
  if (!res.ok) throw await parseError(res);
  const body: { started_at: string } = await res.json();
  return Date.parse(body.started_at);
}

/** Sends the answers. The frontend stores options 0-based; the API expects 1..N. */
export async function submitInvite(token: string, answers: Record<number, number>): Promise<void> {
  const responses = Object.fromEntries(Object.entries(answers).map(([id, option]) => [id, option + 1]));
  const res = await fetch(url(token, '/submit'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ responses }),
  });
  if (res.status === 409) return; // already received (e.g. a retry after a dropped response)
  if (!res.ok) throw await parseError(res);
}
