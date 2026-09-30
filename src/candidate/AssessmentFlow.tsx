import { useCallback, useEffect } from 'react';
import { AppHeader } from '../components/AppHeader';
import { Footer } from '../components/Footer';
import { NotificationBanner } from '../components/NotificationBanner';
import { useSession } from '../hooks/useSession';
import { CompletionPage } from '../pages/CompletionPage';
import { RegistrationPage } from '../pages/RegistrationPage';
import { TestPage } from '../pages/TestPage';
import { VerificationPage } from '../pages/VerificationPage';
import { startInvite } from './api';
import { useCandidate } from './CandidateContext';

const steps = [
  { stage: 'registration', label: 'Registration' },
  { stage: 'verification', label: 'Verification' },
  { stage: 'test', label: 'Assessment' },
] as const;

/** Registration -> verification -> test -> completion for one personal link. */
export function AssessmentFlow() {
  const candidate = useCandidate();
  const { state, dispatch, lastSavedAt } = useSession(candidate.token);

  // The server's start time wins, so the timer is the same on every device.
  useEffect(() => {
    if (candidate.serverStartedAt && state.startedAt !== candidate.serverStartedAt) {
      dispatch({ type: 'syncStartedAt', startedAt: candidate.serverStartedAt });
    }
  }, [candidate.serverStartedAt, state.startedAt, dispatch]);

  const proceed = useCallback(async () => {
    const startedAt = await startInvite(candidate.token);
    dispatch({ type: 'startTest', startedAt });
  }, [candidate.token, dispatch]);

  if (state.stage === 'test') {
    return <TestPage state={state} dispatch={dispatch} lastSavedAt={lastSavedAt} />;
  }

  const activeStep = steps.findIndex((s) => s.stage === state.stage);

  return (
    <div className="app-shell">
      <NotificationBanner />
      <AppHeader />
      {state.stage !== 'completed' && (
        <nav className="stepper" aria-label="Progress">
          {steps.map((s, i) => (
            <span key={s.stage} className={`stepper-item${i === activeStep ? ' active' : i < activeStep ? ' done' : ''}`}>
              <span className="stepper-num">{i + 1}</span>
              {s.label}
            </span>
          ))}
        </nav>
      )}
      {state.stage === 'registration' && <RegistrationPage state={state} dispatch={dispatch} />}
      {state.stage === 'verification' && <VerificationPage state={state} dispatch={dispatch} onProceed={proceed} />}
      {state.stage === 'completed' && <CompletionPage state={state} dispatch={dispatch} />}
      <Footer organization={candidate.organization} support={candidate.support} />
    </div>
  );
}
