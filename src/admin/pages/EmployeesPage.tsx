import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Mail, Plus, Search } from '../../components/Icons';
import { Link } from '../../router';
import { adminJson } from '../api';
import { useOrganization } from '../context';
import type { Invitation, InvitationStatus } from '../types';
import { CopyButton, ErrorNote, PageHeader, STATUS_LABELS, StatusBadge, errorMessage, formatDate } from '../ui';

const FILTERS: (InvitationStatus | 'all')[] = ['all', 'sent', 'opened', 'in_progress', 'completed', 'expired', 'revoked'];
const ACTIVE: InvitationStatus[] = ['sent', 'opened', 'in_progress'];

function mailto(inv: Invitation, organization: string) {
  const subject = `Your ${organization} assessment`;
  const body = [
    `Hi ${inv.employee_name},`,
    '',
    `Please complete your personality assessment using your personal link below. It takes about 45 minutes and must be finished in one sitting.`,
    '',
    inv.link,
    '',
    `The link is valid until ${formatDate(inv.expires_at)} and can only be used once. Please don't share it.`,
    '',
    `Thank you,`,
    organization,
  ].join('\n');
  return `mailto:${encodeURIComponent(inv.email ?? '')}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

interface ParsedRow {
  employee_name: string;
  email?: string;
  employee_code?: string;
  department?: string;
}

/** One employee per line: Name, Email, Employee ID, Department (comma- or tab-separated). */
function parseBulk(text: string): ParsedRow[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.split(/\t|,/).map((c) => c.trim()))
    .filter((cells) => cells[0] && !/^(employee\s*)?name$/i.test(cells[0]))
    .map(([employee_name, email, employee_code, department]) => ({
      employee_name,
      ...(email ? { email } : {}),
      ...(employee_code ? { employee_code } : {}),
      ...(department ? { department } : {}),
    }));
}

function InvitePanel({ onCreated }: { onCreated: () => void }) {
  const organization = useOrganization();
  const [mode, setMode] = useState<'single' | 'bulk'>('single');
  const [form, setForm] = useState({ employee_name: '', email: '', employee_code: '', department: '' });
  const [validDays, setValidDays] = useState(14);
  const [bulk, setBulk] = useState('');
  const [created, setCreated] = useState<Invitation[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const parsed = useMemo(() => parseBulk(bulk), [bulk]);

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (mode === 'single') {
        const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()));
        const inv = await adminJson<Invitation>('/api/admin/invitations', {
          method: 'POST', body: { ...body, valid_days: validDays },
        });
        setCreated([inv]);
        setForm({ employee_name: '', email: '', employee_code: '', department: '' });
      } else {
        const res = await adminJson<{ invitations: Invitation[] }>('/api/admin/invitations/bulk', {
          method: 'POST', body: { employees: parsed, valid_days: validDays },
        });
        setCreated(res.invitations);
        setBulk('');
      }
      onCreated();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const allLinks = created.map((i) => `${i.employee_name}\t${i.email ?? ''}\t${i.link}`).join('\n');

  return (
    <section className="card invite-card">
      <div className="card-head">
        <h2>Invite employees</h2>
        <div className="segmented" role="tablist">
          <button role="tab" aria-selected={mode === 'single'} className={mode === 'single' ? 'active' : ''}
            onClick={() => setMode('single')}>One employee</button>
          <button role="tab" aria-selected={mode === 'bulk'} className={mode === 'bulk' ? 'active' : ''}
            onClick={() => setMode('bulk')}>Several at once</button>
        </div>
      </div>
      <form onSubmit={submit}>
        {mode === 'single' ? (
          <div className="form-grid">
            <label>Full name *<input value={form.employee_name} onChange={set('employee_name')} required /></label>
            <label>Email<input type="email" value={form.email} onChange={set('email')} /></label>
            <label>Employee ID<input value={form.employee_code} onChange={set('employee_code')} placeholder="Generated if left blank" /></label>
            <label>Department<input value={form.department} onChange={set('department')} /></label>
          </div>
        ) : (
          <label className="bulk-label">
            One employee per line: <strong>Name, Email, Employee ID, Department</strong> (paste straight from a spreadsheet)
            <textarea rows={6} value={bulk} onChange={(e) => setBulk(e.target.value)}
              placeholder={'Meera Iyer, meera@example.com, E-1001, Engineering\nRahul Verma, rahul@example.com, E-1002, Sales'} />
            <span className="hint">{parsed.length} employee{parsed.length === 1 ? '' : 's'} detected</span>
          </label>
        )}
        <div className="form-actions">
          <label className="inline-label">Link valid for
            <select value={validDays} onChange={(e) => setValidDays(Number(e.target.value))}>
              {[3, 7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
            </select>
          </label>
          <button className="btn btn-primary" disabled={busy || (mode === 'bulk' && !parsed.length)}>
            <Plus size={16} /> {busy ? 'Creating…' : mode === 'single' ? 'Create link' : `Create ${parsed.length || ''} links`}
          </button>
        </div>
        <ErrorNote error={error} />
      </form>

      {created.length > 0 && (
        <div className="link-result" role="status">
          <div className="link-result-head">
            <strong>{created.length === 1 ? `Link ready for ${created[0].employee_name}` : `${created.length} links ready`}</strong>
            {created.length > 1 && <CopyButton text={allLinks} label="Copy all (name, email, link)" />}
          </div>
          {created.slice(0, 1).map((inv) => (
            <div key={inv.id} className="link-row">
              <input readOnly value={inv.link} onFocus={(e) => e.target.select()} aria-label="Assessment link" />
              <CopyButton text={inv.link} className="btn btn-primary btn-sm" />
              {inv.email && <a className="btn btn-outline btn-sm" href={mailto(inv, organization)}><Mail size={14} /> Email</a>}
            </div>
          ))}
          <p className="hint">Only this employee should use the link. It works once and expires on {formatDate(created[0].expires_at)}.</p>
        </div>
      )}
    </section>
  );
}

export function EmployeesPage() {
  const organization = useOrganization();
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<InvitationStatus | 'all'>('all');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [showInvite, setShowInvite] = useState(false);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      if (search.trim()) params.set('search', search.trim());
      const res = await adminJson<{ invitations: Invitation[]; counts: Record<string, number> }>(
        `/api/admin/invitations?${params}`);
      setInvitations(res.invitations);
      setCounts(res.counts);
      setError('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [filter, search]);

  useEffect(() => {
    const id = window.setTimeout(() => void load(), search ? 250 : 0);
    return () => window.clearTimeout(id);
  }, [load, search]);

  useEffect(() => {
    if (!loading && invitations.length === 0 && filter === 'all' && !search) setShowInvite(true);
  }, [loading, invitations.length, filter, search]);

  const act = async (inv: Invitation, action: 'revoke' | 'extend') => {
    if (action === 'revoke' && !window.confirm(`Revoke ${inv.employee_name}'s link? They won't be able to use it.`)) return;
    try {
      await adminJson(`/api/admin/invitations/${inv.id}/${action}`, {
        method: 'POST', body: action === 'extend' ? { days: 7 } : undefined,
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader title="Employees" subtitle="Send each employee a personal assessment link and track their progress."
        actions={<button className="btn btn-primary" onClick={() => setShowInvite((v) => !v)}><Plus size={16} /> Invite employees</button>} />
      {showInvite && <InvitePanel onCreated={() => void load()} />}

      <section className="card">
        <div className="toolbar">
          <div className="filter-chips" role="tablist" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f} role="tab" aria-selected={filter === f} className={`chip${filter === f ? ' active' : ''}`}
                onClick={() => setFilter(f)}>
                {f === 'all' ? 'All' : STATUS_LABELS[f]}
                <span className="chip-count">{f === 'all' ? total : counts[f] ?? 0}</span>
              </button>
            ))}
          </div>
          <label className="search">
            <Search size={16} />
            <input type="search" placeholder="Search name, email or ID" value={search}
              onChange={(e) => setSearch(e.target.value)} aria-label="Search employees" />
          </label>
        </div>
        <ErrorNote error={error} />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Employee</th><th className="hide-sm">Employee ID</th><th>Status</th><th className="hide-sm">Invited</th><th className="hide-sm">Expires / submitted</th><th /></tr>
            </thead>
            <tbody>
              {invitations.map((inv) => {
                const active = ACTIVE.includes(inv.status);
                return (
                  <tr key={inv.id}>
                    <td>
                      <div className="cell-strong">{inv.employee_name}</div>
                      <div className="cell-sub">{inv.email ?? 'No email'}</div>
                    </td>
                    <td className="hide-sm">
                      <div>{inv.employee_code}</div>
                      <div className="cell-sub">{inv.department ?? ''}</div>
                    </td>
                    <td>
                      <StatusBadge status={inv.status} />
                      {inv.submitted_late && <span className="badge badge-warn">Late</span>}
                    </td>
                    <td className="cell-sub hide-sm">{formatDate(inv.created_at)}</td>
                    <td className="cell-sub hide-sm">{inv.submitted_at ? formatDate(inv.submitted_at) : formatDate(inv.expires_at)}</td>
                    <td className="row-actions">
                      {inv.status === 'completed' && inv.assessment_id && (
                        <Link className="btn btn-primary btn-sm" href={`/admin/reports/${inv.assessment_id}`}>View report</Link>
                      )}
                      {active && <CopyButton text={inv.link} />}
                      {active && inv.email && (
                        <a className="btn btn-ghost btn-sm" href={mailto(inv, organization)} title="Open an email draft"><Mail size={14} /></a>
                      )}
                      {inv.status !== 'completed' && (
                        <button className="btn btn-ghost btn-sm" onClick={() => void act(inv, 'extend')}
                          title="Add 7 days to the link">{active ? '+7 days' : 'Reactivate'}</button>
                      )}
                      {active && (
                        <button className="btn btn-ghost btn-sm danger" onClick={() => void act(inv, 'revoke')}>Revoke</button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!loading && invitations.length === 0 && (
                <tr><td colSpan={6} className="empty">{total ? 'No employees match this filter.' : 'No employees invited yet.'}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
