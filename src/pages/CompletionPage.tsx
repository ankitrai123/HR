import { useCallback, useEffect, useRef, useState, type Dispatch } from 'react';
import { useCandidate } from '../candidate/CandidateContext';
import { submitInvite } from '../candidate/api';
import { Check } from '../components/Icons';
import { questions, test } from '../data/test';
import type { SessionAction, SessionState } from '../hooks/useSession';

type SyncStatus = 'sending' | 'sent' | 'failed';

interface Props {
  state: SessionState;
  dispatch: Dispatch<SessionAction>;
}

export function CompletionPage({ state, dispatch }: Props) {
  const { token, name, organization } = useCandidate();
  const attempted = Object.keys(state.answers).length;
  const [sync, setSync] = useState<SyncStatus>(state.serverReceived ? 'sent' : 'sending');
  const [error, setError] = useState('');
  const inFlight = useRef(false);

  const send = useCallback(async () => {
    if (state.serverReceived || inFlight.current) return;
    inFlight.current = true;
    setSync('sending');
    try {
      await submitInvite(token, state.answers);
      dispatch({ type: 'serverAccepted' });
      setSync('sent');
    } catch (err) {
      setError(err instanceof Error ? err.message : '');
      setSync('failed');
    } finally {
      inFlight.current = false;
    }
  }, [state.serverReceived, state.answers, token, dispatch]);

  useEffect(() => {
    void send();
    // Submit once on arrival; retries are manual.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="page page-complete">
      <section className="card complete-card">
        <span className={`complete-badge${sync === 'failed' ? ' is-warning' : ''}`}>
          {sync === 'sending' ? <span className="spinner spinner-lg" /> : <Check size={32} />}
        </span>
        <h1>{sync === 'sent' ? 'Assessment submitted' : sync === 'sending' ? 'Submitting…' : 'Not submitted yet'}</h1>
        <p className="muted">
          {state.submitReason === 'timeout'
            ? 'Time ran out, so your responses were submitted automatically.'
            : `Thank you, ${name}.`}
        </p>
        <dl className="kv-list complete-stats">
          <div><dt>Assessment</dt><dd>{test.title}</dd></div>
          <div><dt>Questions answered</dt><dd>{attempted} of {questions.length}</dd></div>
        </dl>
        {sync === 'sent' && (
          <p className="muted">
            Your responses have been received by {organization}. Results are reviewed by the HR team, who will
            contact you about next steps. You can close this page.
          </p>
        )}
        {sync === 'failed' && (
          <div className="sync-failed">
            <p className="error-text">
              We couldn’t reach the server{error ? ` (${error})` : ''}. Your answers are saved on this device — please
              keep this page open and try again.
            </p>
            <button className="btn btn-primary" onClick={() => void send()}>Try again</button>
          </div>
        )}
      </section>
    </main>
  );
}
