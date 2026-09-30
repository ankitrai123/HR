import { API_BASE, parseError } from '../api';

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

/** Fired when the server says the session is gone, so the app can show sign-in. */
export const UNAUTHORIZED_EVENT = 'admin:unauthorized';

interface Options {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
}

export async function adminFetch(path: string, { method = 'GET', body }: Options = {}): Promise<Response> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  if (res.status === 401 && !path.startsWith('/api/auth/login')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!res.ok) throw await parseError(res);
  return res;
}

export async function adminJson<T>(path: string, options?: Options): Promise<T> {
  return (await adminFetch(path, options)).json() as Promise<T>;
}

/** Downloads a server-generated file (e.g. a PDF report). */
export async function downloadFile(path: string, filename: string) {
  const blob = await (await adminFetch(path, { method: 'POST' })).blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
