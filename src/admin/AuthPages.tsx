import { useState, type FormEvent } from 'react';
import { Brand } from '../components/Brand';
import { adminJson } from './api';
import type { Session } from './types';
import { ErrorNote, errorMessage } from './ui';

function AuthShell({ organization, title, subtitle, children }: {
  organization: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="auth-shell">
      <div className="auth-card card">
        <Brand organization={organization} subtitle="Admin console" />
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}

export function LoginPage({ organization, onSignedIn }: { organization: string; onSignedIn: (s: Session) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      onSignedIn(await adminJson<Session>('/api/auth/login', { method: 'POST', body: { email, password } }));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <AuthShell organization={organization} title="Sign in" subtitle="Admin access to employee assessments and reports.">
      <form className="form-stack" onSubmit={submit}>
        <label>Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <ErrorNote error={error} />
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="hint">Forgot your password? Ask another admin, or run <code>python manage.py reset-password</code> on the server.</p>
    </AuthShell>
  );
}

export function SetupPage({ organization, tokenRequired, onSignedIn }: {
  organization: string;
  tokenRequired: boolean;
  onSignedIn: (s: Session) => void;
}) {
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', setup_token: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.confirm) {
      setError('Passwords don’t match.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const { confirm: _confirm, ...body } = form;
      onSignedIn(await adminJson<Session>('/api/auth/setup', { method: 'POST', body }));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <AuthShell organization={organization} title="Create the admin account"
      subtitle="This is a one-time setup. You can add more admins later in Settings.">
      <form className="form-stack" onSubmit={submit}>
        <label>Your name<input value={form.name} onChange={set('name')} autoComplete="name" required autoFocus /></label>
        <label>Work email<input type="email" value={form.email} onChange={set('email')} autoComplete="username" required /></label>
        <label>Password
          <input type="password" value={form.password} onChange={set('password')} autoComplete="new-password" required />
          <span className="hint">At least 10 characters, with upper- and lower-case letters and a number.</span>
        </label>
        <label>Confirm password<input type="password" value={form.confirm} onChange={set('confirm')} autoComplete="new-password" required /></label>
        {tokenRequired && (
          <label>Setup token
            <input value={form.setup_token} onChange={set('setup_token')} required />
            <span className="hint">The value of ADMIN_SETUP_TOKEN on the server.</span>
          </label>
        )}
        <ErrorNote error={error} />
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
      </form>
    </AuthShell>
  );
}
