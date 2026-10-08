import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../api';
import { Brand } from '../components/Brand';
import { FileText, Home, LogOut, Settings, Users } from '../components/Icons';
import { Link, navigate, usePathname } from '../router';
import { adminJson, setCsrfToken, UNAUTHORIZED_EVENT } from './api';
import { LoginPage, SetupPage } from './AuthPages';
import { DashboardPage } from './pages/DashboardPage';
import { EmployeesPage } from './pages/EmployeesPage';
import { ReportPage } from './pages/ReportPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { OrgContext } from './context';
import type { Admin, Session } from './types';
import './admin.css';

type AuthState =
  | { kind: 'loading' }
  | { kind: 'setup'; tokenRequired: boolean }
  | { kind: 'login' }
  | { kind: 'signed-in'; admin: Admin }
  | { kind: 'error'; message: string };

const NAV = [
  { href: '/admin', label: 'Dashboard', icon: Home },
  { href: '/admin/employees', label: 'Employees', icon: Users },
  { href: '/admin/reports', label: 'Reports', icon: FileText },
  { href: '/admin/settings', label: 'Settings', icon: Settings },
];

export function AdminApp() {
  const path = usePathname();
  const [auth, setAuth] = useState<AuthState>({ kind: 'loading' });
  const [organization, setOrganization] = useState('');

  const signedIn = useCallback((session: Session) => {
    setCsrfToken(session.csrf_token);
    setAuth({ kind: 'signed-in', admin: session.admin });
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const status = await adminJson<{
          setup_required: boolean;
          setup_token_required: boolean;
          organization: string;
        }>('/api/auth/status');
        setOrganization(status.organization);
        if (status.setup_required) {
          setAuth({
            kind: 'setup',
            tokenRequired: status.setup_token_required,
          });
          return;
        }
        try {
          signedIn(await adminJson<Session>('/api/auth/me'));
        } catch {
          setAuth({ kind: 'login' });
        }
      } catch (err) {
        setAuth({
          kind: 'error',
          // A 503 carries the server's reason (e.g. missing environment variables).
          message: err instanceof ApiError && err.status === 503
            ? err.message
            : 'Can’t reach the server. Check your connection and reload.',
        });
      }
    })();
  }, [signedIn]);

  useEffect(() => {
    const onUnauthorized = () => {
      setCsrfToken(null);
      setAuth((a) => (a.kind === 'signed-in' ? { kind: 'login' } : a));
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const signOut = async () => {
    try {
      await adminJson('/api/auth/logout', { method: 'POST' });
    } finally {
      setCsrfToken(null);
      setAuth({ kind: 'login' });
      navigate('/admin', true);
    }
  };

  if (auth.kind === 'loading')
    return (
      <div className="admin-scope">
        <div className="admin-loading">
          <span className="spinner spinner-lg" />
        </div>
      </div>
    );
  if (auth.kind === 'error')
    return (
      <div className="admin-scope">
        <div className="admin-loading">
          <p className="error-text">{auth.message}</p>
        </div>
      </div>
    );
  if (auth.kind === 'setup') {
    return (
      <div className="admin-scope">
        <SetupPage organization={organization} tokenRequired={auth.tokenRequired} onSignedIn={signedIn} />
      </div>
    );
  }
  if (auth.kind === 'login')
    return (
      <div className="admin-scope">
        <LoginPage organization={organization} onSignedIn={signedIn} />
      </div>
    );

  const reportMatch = path.match(/^\/admin\/reports\/([^/]+)$/);
  let page: React.ReactNode;
  if (reportMatch) page = <ReportPage assessmentId={decodeURIComponent(reportMatch[1])} />;
  else if (path.startsWith('/admin/employees')) page = <EmployeesPage />;
  else if (path.startsWith('/admin/reports')) page = <ReportsPage />;
  else if (path.startsWith('/admin/settings')) page = <SettingsPage admin={auth.admin} />;
  else page = <DashboardPage />;

  const active = (href: string) =>
    href === '/admin' ? path === '/admin' || path === '/admin/' : path.startsWith(href);

  return (
    <OrgContext.Provider value={organization}>
      <div className="admin-scope">
        <div className="admin-shell">
          <aside className="admin-sidebar">
            <Brand organization={organization} compact />
            <nav aria-label="Admin">
              {NAV.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  className={`nav-item${active(href) ? ' active' : ''}`}
                  aria-current={active(href) ? 'page' : undefined}
                >
                  <Icon size={18} /> <span>{label}</span>
                </Link>
              ))}
            </nav>
            <div className="sidebar-user">
              <div>
                <strong>{auth.admin.name}</strong>
                <span>{auth.admin.email}</span>
              </div>
              <button className="icon-btn" onClick={() => void signOut()} aria-label="Sign out" title="Sign out">
                <LogOut size={18} />
              </button>
            </div>
          </aside>
          <main className="admin-main">{page}</main>
        </div>
      </div>
    </OrgContext.Provider>
  );
}
