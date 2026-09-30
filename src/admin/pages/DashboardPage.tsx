import { useEffect, useState, type MouseEvent, type ReactNode } from 'react';
import { Sparkles } from '../../components/Icons';
import { Link } from '../../router';
import { adminJson } from '../api';
import type { Analytics, AssessmentRow, CohortReport } from '../types';
import { ErrorNote, PageHeader, errorMessage, formatDateTime } from '../ui';

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function useTooltip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const bind = (content: ReactNode) => ({
    onMouseMove: (e: MouseEvent) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseLeave: () => setTip(null),
  });
  const node = tip && (
    <div className="viz-tip" role="tooltip" style={{ left: Math.min(tip.x + 12, window.innerWidth - 220), top: tip.y - 40 }}>
      {tip.content}
    </div>
  );
  return { bind, node };
}

function Tile({ label, value, sub, href }: { label: string; value: ReactNode; sub?: string; href?: string }) {
  const body = (
    <>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {sub && <span className="tile-sub">{sub}</span>}
    </>
  );
  return href ? <Link className="tile tile-link" href={href}>{body}</Link> : <div className="tile">{body}</div>;
}

function StenHistogram({ dist }: { dist: Record<string, number> }) {
  const { bind, node } = useTooltip();
  const counts = Array.from({ length: 10 }, (_, i) => dist[String(i + 1)] ?? 0);
  const max = Math.max(1, ...counts);
  const total = counts.reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="hist" role="img" aria-label="Histogram of Sten scores across all dimensions">
        {counts.map((n, i) => (
          <div key={i} className="hist-col" {...bind(<><b>Sten {i + 1}</b> · {n} scores{total ? ` (${Math.round((n / total) * 100)}%)` : ''}</>)}>
            <div className="hist-bar" style={{ height: `${(n / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="hist-axis">{counts.map((_, i) => <span key={i}>{i + 1}</span>)}</div>
      {node}
    </>
  );
}

function DimensionTable({ dims }: { dims: Analytics['dimensions'] }) {
  const { bind, node } = useTooltip();
  const levels = [['Low', 'lvl-low'], ['Moderate', 'lvl-mid'], ['High', 'lvl-high']] as const;
  return (
    <>
      <div className="legend" aria-hidden="true">
        <span><i className="lvl-low" />Low (1–4)</span>
        <span><i className="lvl-mid" />Moderate (5–6)</span>
        <span><i className="lvl-high" />High (7–10)</span>
        <span><i className="dot" />Mean Sten</span>
      </div>
      <div className="table-wrap">
        <table className="data-table dim-table">
          <thead><tr><th>Dimension</th><th>Mean Sten (1–10)</th><th /><th>Level mix</th><th>L · M · H</th></tr></thead>
          <tbody>
            {Object.entries(dims).map(([dim, d]) => {
              const n = d.n || 1;
              const pct = (k: string) => Math.round(((d.levels[k] ?? 0) / n) * 100);
              return (
                <tr key={dim}>
                  <td>{dim}</td>
                  <td>
                    <div className="track" {...bind(<><b>{dim}</b> · mean {d.mean_sten.toFixed(2)} (range {d.min_sten}–{d.max_sten})</>)}>
                      <span className="track-dot" style={{ left: `${((d.mean_sten - 1) / 9) * 100}%` }} />
                    </div>
                  </td>
                  <td className="num">{d.mean_sten.toFixed(1)}</td>
                  <td>
                    <div className="level-stack">
                      {levels.map(([k, cls]) => (d.levels[k] ?? 0) > 0 && (
                        <span key={k} className={cls} style={{ width: `${pct(k)}%` }}
                          {...bind(<><b>{dim}</b> · {k}: {d.levels[k]} ({pct(k)}%)</>)} />
                      ))}
                    </div>
                  </td>
                  <td className="num mix">{pct('Low')} · {pct('Moderate')} · {pct('High')}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {node}
    </>
  );
}

function CohortCard({ hasData }: { hasData: boolean }) {
  const [cohort, setCohort] = useState<CohortReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async () => {
    setBusy(true);
    setError('');
    try {
      setCohort(await adminJson<CohortReport>('/api/admin/cohort-analysis', { method: 'POST' }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <div className="card-head">
        <h2><Sparkles size={18} /> Cohort insights</h2>
        <button className="btn btn-primary btn-sm" disabled={busy || !hasData} onClick={() => void run()}>
          {busy ? 'Analysing…' : cohort ? 'Refresh' : 'Analyse cohort'}
        </button>
      </div>
      <ErrorNote error={error} />
      {cohort ? (
        <div className="ai-body">
          <p>{cohort.summary}</p>
          <h3>Observations</h3>
          <ul>{cohort.observations.map((o) => <li key={o}>{o}</li>)}</ul>
          <h3>Recommendations</h3>
          <ul>{cohort.recommendations.map((o) => <li key={o}>{o}</li>)}</ul>
          <p className="hint">
            {cohort.generated_by ? `Generated by ${cohort.generated_by.provider_label} · ${cohort.generated_by.model}`
              : 'Pre-written summary (no AI provider configured).'} Based on {cohort.candidates} assessments.
          </p>
        </div>
      ) : (
        <p className="muted">
          {hasData ? 'AI analysis of anonymised, aggregated results across all employees.'
            : 'Available once employees have completed assessments.'}
        </p>
      )}
    </section>
  );
}

export function DashboardPage() {
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [recent, setRecent] = useState<AssessmentRow[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      adminJson<Analytics>('/api/analytics'),
      adminJson<{ counts: Record<string, number> }>('/api/admin/invitations'),
      adminJson<{ assessments: AssessmentRow[] }>('/api/admin/assessments?limit=5'),
    ])
      .then(([a, inv, rec]) => {
        setAnalytics(a);
        setCounts(inv.counts);
        setRecent(rec.assessments);
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  if (error) return <><PageHeader title="Dashboard" /><ErrorNote error={error} /></>;
  if (!analytics) return <div className="admin-loading"><span className="spinner spinner-lg" /></div>;

  const a = analytics.assessments;
  const invited = Object.values(counts).reduce((x, y) => x + y, 0);
  const pending = (counts.sent ?? 0) + (counts.opened ?? 0);
  const flagged = a.by_quality.Questionable ?? 0;
  const hasData = a.total > 0;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Assessment progress and results across your organisation." />
      <section className="tiles">
        <Tile label="Invited" value={invited} sub={`${pending} not started yet`} href="/admin/employees" />
        <Tile label="In progress" value={counts.in_progress ?? 0} sub="Test started" href="/admin/employees" />
        <Tile label="Completed" value={counts.completed ?? 0} sub={`${a.total} reports in total`} href="/admin/reports" />
        <Tile label="Flagged responses" value={flagged} sub="Quality checks failed" href="/admin/reports" />
        <Tile label="AI reports" value={a.premium_reports}
          sub={analytics.engine.llm_available ? `${analytics.engine.llm.provider_label}` : 'No AI provider configured'}
          href="/admin/settings" />
        <Tile label="Expired / revoked" value={(counts.expired ?? 0) + (counts.revoked ?? 0)} sub="Links no longer active" />
      </section>

      {hasData ? (
        <div className="dash-grid">
          <section className="card">
            <h2>Sten score distribution</h2>
            <StenHistogram dist={analytics.sten_distribution} />
            <p className="hint">All dimension scores. With calibrated norms this is roughly bell-shaped around 5–6
              {analytics.norms === 'provisional' ? ' — norms are currently provisional.' : '.'}</p>
          </section>
          <section className="card">
            <h2>Dimensions</h2>
            <DimensionTable dims={analytics.dimensions} />
          </section>
        </div>
      ) : (
        <section className="card empty-state">
          <h2>No results yet</h2>
          <p className="muted">Invite employees to start collecting assessments. Results appear here as they finish.</p>
          <Link className="btn btn-primary" href="/admin/employees">Invite employees</Link>
        </section>
      )}

      <div className="dash-grid dash-grid-even">
        <CohortCard hasData={hasData} />
        <section className="card">
          <div className="card-head">
            <h2>Recent submissions</h2>
            <Link href="/admin/reports" className="btn btn-ghost btn-sm">All reports</Link>
          </div>
          {recent.length ? (
            <ul className="recent-list">
              {recent.map((r) => (
                <li key={r.assessment_id}>
                  <Link href={`/admin/reports/${r.assessment_id}`}>
                    <strong>{r.name}</strong>
                    <span className="cell-sub">{r.test_taker_id} · {formatDateTime(r.submitted_at)}</span>
                  </Link>
                  {r.response_quality !== 'Genuine' && <span className="badge badge-warn">Flagged</span>}
                </li>
              ))}
            </ul>
          ) : <p className="muted">Nothing submitted yet.</p>}
        </section>
      </div>
    </>
  );
}
