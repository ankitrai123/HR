import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Plus } from '../../components/Icons';
import { adminJson } from '../api';
import type { Admin, LlmStatus, Provider } from '../types';
import { ErrorNote, PageHeader, errorMessage, formatDateTime } from '../ui';

function AiProviderCard() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [current, setCurrent] = useState<LlmStatus | null>(null);
  const [providerId, setProviderId] = useState('anthropic');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [prices, setPrices] = useState({ input: '', output: '' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'' | 'fetch' | 'save' | 'remove'>('');

  const spec = providers.find((p) => p.id === providerId);
  const savedHere = current?.source === 'dashboard' && current.provider === providerId;

  const applyProvider = useCallback((id: string, list: Provider[], status: LlmStatus | null) => {
    const p = list.find((x) => x.id === id);
    const same = status?.source === 'dashboard' && status.provider === id;
    setProviderId(id);
    setApiKey('');
    setModels([]);
    setBaseUrl(same && status?.base_url ? status.base_url : p?.base_url ?? '');
    setModel(same ? status?.model ?? '' : id === 'anthropic' ? p?.model_hint ?? '' : '');
    setPrices(same ? { input: String(status?.input_price_per_mtok || ''), output: String(status?.output_price_per_mtok || '') }
      : { input: '', output: '' });
  }, []);

  useEffect(() => {
    adminJson<{ current: LlmStatus; providers: Provider[] }>('/api/admin/llm')
      .then((res) => {
        setProviders(res.providers);
        setCurrent(res.current);
        applyProvider(res.current.provider ?? 'anthropic', res.providers, res.current);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [applyProvider]);

  const payload = () => ({
    provider: providerId,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    ...(spec?.base_url_editable && baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
  });

  const fetchModels = async () => {
    setBusy('fetch');
    setError('');
    setMessage('');
    try {
      const res = await adminJson<{ models: string[] }>('/api/admin/llm/models', { method: 'POST', body: payload() });
      setModels(res.models);
      setMessage(`${res.models.length} models available — choose one below.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('save');
    setError('');
    setMessage('');
    try {
      const res = await adminJson<{ current: LlmStatus }>('/api/admin/llm', {
        method: 'PUT',
        body: {
          ...payload(), model: model.trim(),
          ...(prices.input !== '' ? { input_price_per_mtok: Number(prices.input) } : {}),
          ...(prices.output !== '' ? { output_price_per_mtok: Number(prices.output) } : {}),
        },
      });
      setCurrent(res.current);
      setApiKey('');
      setMessage('Connected and saved. The key is stored encrypted and won’t be shown again.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  const remove = async () => {
    if (!window.confirm('Disconnect this AI provider and delete the saved key?')) return;
    setBusy('remove');
    try {
      const res = await adminJson<{ current: LlmStatus }>('/api/admin/llm', { method: 'DELETE' });
      setCurrent(res.current);
      applyProvider(providerId, providers, res.current);
      setMessage('Disconnected. The saved key was deleted.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>AI provider</h2>
          <p className="muted">Used for AI report analysis and cohort insights. Only anonymised scores are sent — never
            names, emails or answers.</p>
        </div>
        <span className={`badge ${current?.available ? 'badge-completed' : 'badge-warn'}`}>
          {current?.available ? `${current.provider_label} · ${current.model}${current.source === 'environment' ? ' (server config)' : ''}`
            : 'Not configured'}
        </span>
      </div>
      <form onSubmit={save}>
        <div className="form-grid">
          <label>Provider
            <select value={providerId} onChange={(e) => applyProvider(e.target.value, providers, current)}>
              {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            {spec?.docs_url && <a className="hint-link" href={spec.docs_url} target="_blank" rel="noopener noreferrer">Get an API key ↗</a>}
          </label>
          <label>API key
            <input type="password" autoComplete="new-password" spellCheck={false} value={apiKey}
              onChange={(e) => setApiKey(e.target.value)} placeholder={spec?.requires_key ? spec.key_hint : 'optional'} />
            <span className="hint">
              {savedHere && current?.key_hint ? `Saved key ${current.key_hint} — leave blank to keep it.`
                : spec && !spec.requires_key ? 'Not required for this provider.' : ''}
            </span>
          </label>
          {spec?.base_url_editable && (
            <label>Base URL
              <input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
            </label>
          )}
          <label>Model
            <span className="input-with-button">
              <input list="llm-models" value={model} onChange={(e) => setModel(e.target.value)}
                placeholder={spec?.model_hint} spellCheck={false} required />
              <button type="button" className="btn btn-outline btn-sm" onClick={() => void fetchModels()} disabled={busy !== ''}>
                {busy === 'fetch' ? 'Fetching…' : 'Fetch models'}
              </button>
            </span>
            <datalist id="llm-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
          </label>
        </div>
        <details className="cost-details">
          <summary>Cost tracking (optional)</summary>
          <div className="form-grid">
            <label>Input $ per 1M tokens<input type="number" min="0" step="0.01" value={prices.input}
              onChange={(e) => setPrices((p) => ({ ...p, input: e.target.value }))} /></label>
            <label>Output $ per 1M tokens<input type="number" min="0" step="0.01" value={prices.output}
              onChange={(e) => setPrices((p) => ({ ...p, output: e.target.value }))} /></label>
          </div>
        </details>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy !== ''}>{busy === 'save' ? 'Testing connection…' : 'Save & test connection'}</button>
          {current?.source === 'dashboard' && (
            <button type="button" className="btn btn-ghost danger" onClick={() => void remove()} disabled={busy !== ''}>Disconnect</button>
          )}
          {message && <span className="success-text" role="status">{message}</span>}
        </div>
        <ErrorNote error={error} />
      </form>
    </section>
  );
}

interface AdminRow extends Admin {
  created_at: string;
  last_login_at: string | null;
}

function AdminsCard({ me }: { me: Admin }) {
  const [users, setUsers] = useState<AdminRow[]>([]);
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    adminJson<{ users: AdminRow[] }>('/api/admin/users').then((r) => setUsers(r.users))
      .catch((err) => setError(errorMessage(err)));
  }, []);
  useEffect(load, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await adminJson('/api/admin/users', { method: 'POST', body: form });
      setForm({ name: '', email: '', password: '' });
      setAdding(false);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (u: AdminRow) => {
    if (!window.confirm(`Remove ${u.name}'s admin access?`)) return;
    try {
      await adminJson(`/api/admin/users/${u.id}`, { method: 'DELETE' });
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>Admin accounts</h2>
          <p className="muted">Admins can invite employees and see every report.</p>
        </div>
        <button className="btn btn-outline btn-sm" onClick={() => setAdding((v) => !v)}><Plus size={14} /> Add admin</button>
      </div>
      {adding && (
        <form className="form-grid add-admin" onSubmit={add}>
          <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
          <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
          <label>Temporary password
            <input type="password" autoComplete="new-password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            <span className="hint">Share it securely; they can change it in Settings.</span>
          </label>
          <div className="form-actions"><button className="btn btn-primary">Create admin</button></div>
        </form>
      )}
      <ErrorNote error={error} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Name</th><th>Email</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="cell-strong">{u.name}{u.id === me.id && <span className="badge badge-sent">You</span>}</td>
                <td>{u.email}</td>
                <td className="cell-sub">{u.last_login_at ? formatDateTime(u.last_login_at) : 'Never'}</td>
                <td className="row-actions">
                  {u.id !== me.id && <button className="btn btn-ghost btn-sm danger" onClick={() => void remove(u)}>Remove</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PasswordCard() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setDone(false);
    if (form.next !== form.confirm) {
      setError('New passwords don’t match.');
      return;
    }
    try {
      await adminJson('/api/auth/change-password', {
        method: 'POST', body: { current_password: form.current, new_password: form.next },
      });
      setForm({ current: '', next: '', confirm: '' });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="card">
      <h2>Change password</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>Current password<input type="password" autoComplete="current-password" value={form.current}
          onChange={(e) => setForm({ ...form, current: e.target.value })} required /></label>
        <span />
        <label>New password<input type="password" autoComplete="new-password" value={form.next}
          onChange={(e) => setForm({ ...form, next: e.target.value })} required />
          <span className="hint">At least 10 characters, mixed case, with a number.</span></label>
        <label>Confirm new password<input type="password" autoComplete="new-password" value={form.confirm}
          onChange={(e) => setForm({ ...form, confirm: e.target.value })} required /></label>
        <div className="form-actions">
          <button className="btn btn-primary">Update password</button>
          {done && <span className="success-text" role="status">Password updated. Other sessions were signed out.</span>}
        </div>
      </form>
      <ErrorNote error={error} />
    </section>
  );
}

export function SettingsPage({ admin }: { admin: Admin }) {
  return (
    <>
      <PageHeader title="Settings" />
      <div className="settings-stack">
        <AiProviderCard />
        <AdminsCard me={admin} />
        {admin.id !== null && <PasswordCard />}
      </div>
    </>
  );
}
