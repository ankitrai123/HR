import { useCallback, useEffect, useState } from 'react';
import { Download, Sparkles } from '../../components/Icons';
import { Link } from '../../router';
import { adminJson, downloadFile } from '../api';
import type { Report } from '../types';
import { ErrorNote, PageHeader, errorMessage, formatDateTime } from '../ui';

function StenBar({ sten }: { sten: number }) {
  return (
    <span className="sten-bar" role="img" aria-label={`Sten ${sten} of 10`}>
      {Array.from({ length: 10 }, (_, i) => <i key={i} className={i < sten ? 'on' : ''} />)}
    </span>
  );
}

export function ReportPage({ assessmentId }: { assessmentId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState('');
  const [aiNotice, setAiNotice] = useState('');

  const load = useCallback(async () => {
    try {
      setReport(await adminJson<Report>(`/api/results/${encodeURIComponent(assessmentId)}`));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [assessmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAi = async () => {
    setAiBusy(true);
    setAiError('');
    setAiNotice('');
    try {
      const updated = await adminJson<Report>('/api/generate-premium-report', {
        method: 'POST', body: { test_id: assessmentId },
      });
      setReport((r) => (r ? { ...r, ...updated } : updated));
      if (updated.premium_features?.content_source === 'fallback') {
        setAiNotice('No AI provider is available, so pre-written text was used. Configure one in Settings.');
      }
    } catch (err) {
      setAiError(errorMessage(err));
    } finally {
      setAiBusy(false);
    }
  };

  if (error) return <><PageHeader title="Report" /><ErrorNote error={error} /></>;
  if (!report) return <div className="admin-loading"><span className="spinner spinner-lg" /></div>;

  const pf = report.premium_features;
  const hasAi = Boolean(pf?.executive_summary);
  const complete = report.status === 'Completed';
  const fileStem = `assessment_${report.test_id}`;

  return (
    <>
      <p className="breadcrumb"><Link href="/admin/reports">Reports</Link> / {report.name}</p>
      <PageHeader
        title={report.name}
        subtitle={`Employee ID ${report.test_id} · submitted ${formatDateTime(report.submitted_at)} · ${report.questions_answered} of 175 answered`}
        actions={
          <>
            <button className="btn btn-outline" onClick={() => void downloadFile(
              `/api/export/${encodeURIComponent(assessmentId)}?format=pdf`, `${fileStem}.pdf`)}>
              <Download size={16} /> PDF
            </button>
            {complete && (
              <button className="btn btn-primary" onClick={() => void runAi()} disabled={aiBusy}>
                <Sparkles size={16} /> {aiBusy ? 'Analysing…' : hasAi ? 'Re-run AI analysis' : 'Generate AI analysis'}
              </button>
            )}
          </>
        }
      />

      {(report.quality_flags.length > 0 || !complete) && (
        <div className="alert alert-warn" role="note">
          <strong>{complete ? 'Response quality flags' : 'Incomplete assessment'}</strong>
          <ul>{report.quality_flags.map((f) => <li key={f}>{f}</li>)}</ul>
          <span>Interpret this profile with caution and consider discussing it with the employee.</span>
        </div>
      )}

      <div className="report-grid">
        <section className="card">
          <h2>Summary</h2>
          <p>{report.profile_summary}</p>
          <div className="chip-groups">
            <div>
              <h3>Strengths</h3>
              {report.strengths.length ? report.strengths.map((s) => <span key={s} className="tag tag-high">{s}</span>)
                : <span className="cell-sub">None in the high range</span>}
            </div>
            <div>
              <h3>Development areas</h3>
              {report.areas_of_development.length
                ? report.areas_of_development.map((s) => <span key={s} className="tag tag-low">{s}</span>)
                : <span className="cell-sub">None in the low range</span>}
            </div>
          </div>
        </section>
        <section className="card meta-card">
          <h2>Assessment</h2>
          <dl className="kv-list">
            <div><dt>Status</dt><dd>{report.status}</dd></div>
            <div><dt>Response quality</dt><dd>{report.response_quality}</dd></div>
            <div><dt>Norms</dt><dd>{report.norms}</dd></div>
            <div><dt>Scoring key</dt><dd>{report.scoring_key}</dd></div>
          </dl>
          {(report.norms === 'provisional' || report.scoring_key === 'provisional') && (
            <p className="hint">Provisional norms / scoring key: use for development conversations, not selection decisions.</p>
          )}
        </section>
      </div>

      {complete && (
        <section className="card">
          <h2>Dimension scores</h2>
          <div className="table-wrap">
            <table className="data-table scores-table">
              <thead><tr><th>Dimension</th><th>Sten (1–10)</th><th>Level</th><th>Percentile</th><th>Interpretation</th></tr></thead>
              <tbody>
                {Object.entries(report.scores).map(([dim, s]) => (
                  <tr key={dim}>
                    <td><div className="cell-strong">{dim}</div><div className="cell-sub">{s.category}</div></td>
                    <td><div className="sten-cell"><StenBar sten={s.sten_score} /><b>{s.sten_score}</b></div></td>
                    <td><span className={`tag tag-${s.level.toLowerCase()}`}>{s.level}</span></td>
                    <td className="num">{Math.round(s.percentile)}</td>
                    <td className="interp">{pf?.dimension_insights?.[dim] ?? s.interpretation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card ai-card">
        <div className="card-head">
          <h2><Sparkles size={18} /> AI analysis</h2>
          {pf?.generated_by && (
            <span className="cell-sub">Generated by {pf.generated_by.provider_label} · {pf.generated_by.model}</span>
          )}
        </div>
        <ErrorNote error={aiError} />
        {aiNotice && (
          <p className="notice" role="status">
            {aiNotice} <Link href="/admin/settings">Open Settings</Link>
          </p>
        )}
        {hasAi && pf ? (
          <div className="ai-body">
            <h3>Executive summary</h3>
            <p>{pf.executive_summary}</p>
            <h3>Development plan</h3>
            {pf.development_plan?.map((p) => (
              <div key={p.dimension} className="plan-item">
                <strong>{p.dimension}</strong>
                <ul>{p.actions.map((a) => <li key={a}>{a}</li>)}</ul>
              </div>
            ))}
            <h3>Coaching insights</h3>
            <ul>{pf.coaching_insights?.map((c) => <li key={c}>{c}</li>)}</ul>
            {pf.content_source !== 'llm' && (
              <p className="hint">Some sections use pre-written text because the AI provider was unavailable.</p>
            )}
          </div>
        ) : (
          <p className="muted">
            {complete ? 'Generate an AI-written executive summary, development plan and coaching insights. Only '
              + 'anonymised scores are sent to the AI provider.' : 'AI analysis needs a completed assessment.'}
          </p>
        )}
      </section>
    </>
  );
}
