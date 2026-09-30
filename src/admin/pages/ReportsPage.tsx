import { useEffect, useMemo, useState } from 'react';
import { Search } from '../../components/Icons';
import { Link } from '../../router';
import { adminJson } from '../api';
import type { AssessmentRow } from '../types';
import { ErrorNote, PageHeader, errorMessage, formatDateTime } from '../ui';

export function ReportsPage() {
  const [rows, setRows] = useState<AssessmentRow[]>([]);
  const [search, setSearch] = useState('');
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminJson<{ assessments: AssessmentRow[] }>('/api/admin/assessments?limit=500')
      .then((res) => setRows(res.assessments))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => (!flaggedOnly || r.response_quality !== 'Genuine' || r.status !== 'Completed')
      && (!q || r.name.toLowerCase().includes(q) || r.test_taker_id.toLowerCase().includes(q)));
  }, [rows, search, flaggedOnly]);

  return (
    <>
      <PageHeader title="Reports" subtitle="Results are visible to admins only. Employees never see their scores." />
      <section className="card">
        <div className="toolbar">
          <label className="check-inline">
            <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
            Only flagged or incomplete
          </label>
          <label className="search">
            <Search size={16} />
            <input type="search" placeholder="Search name or employee ID" value={search}
              onChange={(e) => setSearch(e.target.value)} aria-label="Search reports" />
          </label>
        </div>
        <ErrorNote error={error} />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Employee</th><th className="hide-sm">Submitted</th><th>Quality</th><th className="hide-sm">Strengths</th><th className="hide-sm">AI analysis</th><th /></tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.assessment_id}>
                  <td>
                    <div className="cell-strong">{r.name}</div>
                    <div className="cell-sub">{r.test_taker_id}</div>
                  </td>
                  <td className="cell-sub hide-sm">{formatDateTime(r.submitted_at)}</td>
                  <td>
                    {r.status !== 'Completed' ? <span className="badge badge-expired">Incomplete</span>
                      : r.response_quality === 'Genuine' ? <span className="badge badge-completed">Genuine</span>
                        : <span className="badge badge-warn">Flagged</span>}
                  </td>
                  <td className="cell-sub hide-sm">{r.strengths.slice(0, 3).join(', ') || '–'}</td>
                  <td className="cell-sub hide-sm">{r.has_premium ? 'Generated' : '–'}</td>
                  <td className="row-actions">
                    <Link className="btn btn-outline btn-sm" href={`/admin/reports/${r.assessment_id}`}>Open</Link>
                  </td>
                </tr>
              ))}
              {!loading && visible.length === 0 && (
                <tr><td colSpan={6} className="empty">{rows.length ? 'No reports match.' : 'No completed assessments yet.'}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
