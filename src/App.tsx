import { AppHeader } from './components/AppHeader';
import { Footer } from './components/Footer';
import { NotificationBanner } from './components/NotificationBanner';
import { useSession } from './hooks/useSession';
import { CompletionPage } from './pages/CompletionPage';
import { RegistrationPage } from './pages/RegistrationPage';
import { TestPage } from './pages/TestPage';
import { VerificationPage } from './pages/VerificationPage';

const steps = [
  { stage: 'registration', label: 'Registration' },
  { stage: 'verification', label: 'Verification' },
  { stage: 'test', label: 'Assessment' },
] as const;

export default function App() {
  const { state, dispatch, lastSavedAt } = useSession();

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
      {state.stage === 'verification' && <VerificationPage state={state} dispatch={dispatch} />}
      {state.stage === 'completed' && <CompletionPage state={state} dispatch={dispatch} />}
      <Footer />
    </div>
  );
}
