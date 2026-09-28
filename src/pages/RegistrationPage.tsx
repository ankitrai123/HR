import type { Dispatch } from 'react';
import {
  candidate,
  guidelines,
  offerOverview,
  registrationWindow,
  requiredDocuments,
} from '../data/candidate';
import type { SessionAction, SessionState } from '../hooks/useSession';
import { useNow } from '../hooks/useSession';
import { Calendar, Check, Clock, FileText } from '../components/Icons';

const dateFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });

function formatRemaining(ms: number) {
  const mins = Math.floor(ms / 60000);
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  return `${hours}h ${mins % 60}m`;
}

interface Props {
  state: SessionState;
  dispatch: Dispatch<SessionAction>;
}

export function RegistrationPage({ state, dispatch }: Props) {
  const now = useNow(30_000);
  const { opens, closes } = registrationWindow;
  const status = now < opens.getTime() ? 'upcoming' : now > closes.getTime() ? 'closed' : 'open';

  const mandatory = requiredDocuments.filter((d) => !d.optional);
  const allMandatoryConfirmed = mandatory.every((d) => state.docsConfirmed.includes(d.id));
  const canContinue = status === 'open' && allMandatoryConfirmed;

  return (
    <main className="page page-registration">
      <div className="page-title">
        <h1>Candidate Registration</h1>
        <p>
          Welcome, {candidate.name}. Review the guidelines and confirm your documents before starting the
          assessment for <strong>{candidate.role}</strong>.
        </p>
      </div>

      <div className="registration-grid">
        <div className="stack">
          <section className="card">
            <h2 className="card-title">Assessment guidelines</h2>
            <ol className="guideline-list">
              {guidelines.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ol>
          </section>

          <section className="card">
            <h2 className="card-title">Offer overview</h2>
            <dl className="kv-grid">
              {offerOverview.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="card">
            <h2 className="card-title">Document checklist</h2>
            <p className="muted">Confirm you have the following ready for verification.</p>
            <ul className="doc-list">
              {requiredDocuments.map((doc) => {
                const checked = state.docsConfirmed.includes(doc.id);
                return (
                  <li key={doc.id}>
                    <label className={`doc-item${checked ? ' is-checked' : ''}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => dispatch({ type: 'toggleDoc', id: doc.id })}
                      />
                      <span className="doc-box" aria-hidden="true">
                        {checked && <Check size={14} />}
                      </span>
                      <FileText size={18} className="doc-icon" />
                      <span className="doc-text">
                        <strong>
                          {doc.label}
                          {doc.optional && <em className="tag">Optional</em>}
                        </strong>
                        <span>{doc.detail}</span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>

        <aside className="stack sticky-col">
          <section className="card schedule-card">
            <div className="schedule-head">
              <h2 className="card-title">Registration schedule</h2>
              <span className={`status-pill status-${status}`}>
                {status === 'open' ? 'Open' : status === 'upcoming' ? 'Not yet open' : 'Closed'}
              </span>
            </div>
            <div className="schedule-row">
              <span className="schedule-icon"><Calendar size={18} /></span>
              <div>
                <span className="schedule-label">Opens</span>
                <strong>{dateFmt.format(opens)}</strong>
                <span className="muted">{timeFmt.format(opens)}</span>
              </div>
            </div>
            <div className="schedule-row">
              <span className="schedule-icon"><Clock size={18} /></span>
              <div>
                <span className="schedule-label">Closes</span>
                <strong>{dateFmt.format(closes)}</strong>
                <span className="muted">{timeFmt.format(closes)}</span>
              </div>
            </div>
            {status === 'open' && (
              <p className="schedule-remaining">
                Closes in <strong>{formatRemaining(closes.getTime() - now)}</strong>
              </p>
            )}
          </section>

          <section className="card candidate-card">
            <h2 className="card-title">Candidate details</h2>
            <dl className="kv-list">
              <div><dt>Name</dt><dd>{candidate.name}</dd></div>
              <div><dt>Candidate ID</dt><dd>{candidate.candidateId}</dd></div>
              <div><dt>Email</dt><dd>{candidate.email}</dd></div>
            </dl>
            <button
              className="btn btn-primary btn-block"
              disabled={!canContinue}
              onClick={() => dispatch({ type: 'goTo', stage: 'verification' })}
            >
              Continue to verification
            </button>
            {!canContinue && (
              <p className="hint">
                {status !== 'open'
                  ? 'Registration is not open right now.'
                  : 'Confirm all mandatory documents to continue.'}
              </p>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}
