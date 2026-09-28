import { useEffect, useRef, useState, type Dispatch } from 'react';
import { candidate } from '../data/candidate';
import { questions, test } from '../data/test';
import type { SessionAction, SessionState } from '../hooks/useSession';
import { Check, Clock, FileText, Keyboard, Layers, Monitor } from '../components/Icons';

const VALIDATION_PHRASE = 'Hello World';

interface CheckResult {
  label: string;
  ok: boolean;
  /** Warnings are shown but don't block the candidate. */
  blocking: boolean;
}

function runSystemChecks(): CheckResult[] {
  let storage = false;
  try {
    localStorage.setItem('__probe', '1');
    localStorage.removeItem('__probe');
    storage = true;
  } catch {
    storage = false;
  }
  return [
    { label: 'Browser supports the test engine', ok: typeof Promise !== 'undefined' && 'fetch' in window, blocking: true },
    { label: 'Local storage available for auto-save', ok: storage, blocking: true },
    { label: 'Internet connection', ok: navigator.onLine, blocking: true },
    { label: 'Cookies enabled', ok: navigator.cookieEnabled, blocking: true },
    { label: 'Screen width ≥ 1024px recommended', ok: window.innerWidth >= 1024, blocking: false },
  ];
}

interface Props {
  state: SessionState;
  dispatch: Dispatch<SessionAction>;
}

export function VerificationPage({ state, dispatch }: Props) {
  const [checks, setChecks] = useState<CheckResult[] | null>(null);
  const [inputError, setInputError] = useState('');
  const [isEmpty, setIsEmpty] = useState(true);
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Short delay so the candidate sees the check happen.
    const id = window.setTimeout(() => {
      const results = runSystemChecks();
      setChecks(results);
      if (results.every((c) => c.ok || !c.blocking)) dispatch({ type: 'systemCheckPassed' });
    }, 900);
    return () => window.clearTimeout(id);
  }, [dispatch]);

  const format = (command: 'bold' | 'italic' | 'underline') => {
    editorRef.current?.focus();
    document.execCommand(command);
  };

  const submitInput = () => {
    const text = (editorRef.current?.innerText ?? '').replace(/\s+/g, ' ').trim();
    if (text === VALIDATION_PHRASE) {
      setInputError('');
      dispatch({ type: 'inputCheckPassed' });
    } else {
      setInputError(`Text doesn't match. Type exactly "${VALIDATION_PHRASE}" (case-sensitive).`);
    }
  };

  const systemState = state.systemCheckPassed ? 'done' : checks ? 'failed' : 'running';
  const canProceed = state.systemCheckPassed && state.inputCheckPassed;
  const resuming = state.startedAt !== null;

  return (
    <main className="page page-verification">
      <div className="verification-grid">
        <section className="card test-overview">
          <p className="eyebrow">Hi, {candidate.name}</p>
          <h1>{test.title}</h1>
          <p className="muted">
            {test.sections.map((s) => s.sectionTitle).join(' · ')} — respond to each statement based on how
            well it describes you. There are no right or wrong answers.
          </p>

          <div className="metric-grid">
            <div className="metric">
              <span className="metric-icon"><FileText size={20} /></span>
              <strong>{questions.length}</strong>
              <span>Questions</span>
            </div>
            <div className="metric">
              <span className="metric-icon"><Layers size={20} /></span>
              <strong>{test.sections.length}</strong>
              <span>{test.sections.length === 1 ? 'Section' : 'Sections'}</span>
            </div>
            <div className="metric">
              <span className="metric-icon"><Clock size={20} /></span>
              <strong>{test.durationMinutes}</strong>
              <span>Minutes</span>
            </div>
          </div>

          <div className="overview-notes">
            <h2>Before you begin</h2>
            <ul>
              <li>The timer starts when you click <strong>Proceed</strong> and cannot be paused.</li>
              <li>Answers save automatically; you can mark questions to revisit later.</li>
              <li>Keyboard: <kbd>1</kbd>–<kbd>6</kbd> to answer, <kbd>←</kbd> <kbd>→</kbd> to navigate.</li>
            </ul>
          </div>
        </section>

        <section className="card verify-steps">
          <h2 className="card-title">Verification</h2>

          <div className={`step step-${systemState}`}>
            <div className="step-marker">{systemState === 'done' ? <Check size={16} /> : <Monitor size={16} />}</div>
            <div className="step-body">
              <h3>1. System compatibility</h3>
              {systemState === 'running' && <p className="muted"><span className="spinner" /> Checking your system…</p>}
              {checks && (
                <ul className="check-list">
                  {checks.map((c) => (
                    <li key={c.label} className={c.ok ? 'ok' : c.blocking ? 'fail' : 'warn'}>
                      <span aria-hidden="true">{c.ok ? '✓' : c.blocking ? '✕' : '!'}</span> {c.label}
                    </li>
                  ))}
                </ul>
              )}
              {systemState === 'done' && !checks && <p className="muted">Your system is compatible.</p>}
              {systemState === 'failed' && (
                <p className="error-text">Fix the items marked ✕ and reload the page.</p>
              )}
            </div>
          </div>

          <div className={`step step-${state.inputCheckPassed ? 'done' : 'active'}`}>
            <div className="step-marker">{state.inputCheckPassed ? <Check size={16} /> : <Keyboard size={16} />}</div>
            <div className="step-body">
              <h3>2. Textbox input verification</h3>
              <p className="muted">
                Type <strong>"{VALIDATION_PHRASE}"</strong> in the box below and click Submit to confirm your keyboard
                works.
              </p>
              {state.inputCheckPassed ? (
                <p className="success-text">Input verified.</p>
              ) : (
                <>
                  <div className="rte">
                    <div className="rte-toolbar" role="toolbar" aria-label="Formatting">
                      <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => format('bold')} aria-label="Bold"><b>B</b></button>
                      <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => format('italic')} aria-label="Italic"><i>I</i></button>
                      <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => format('underline')} aria-label="Underline"><u>U</u></button>
                    </div>
                    <div
                      ref={editorRef}
                      className={`rte-editor${isEmpty ? ' is-empty' : ''}`}
                      contentEditable
                      role="textbox"
                      aria-multiline="true"
                      aria-label="Verification text"
                      data-placeholder="Type here…"
                      onInput={(e) => {
                        setIsEmpty(!e.currentTarget.innerText.trim());
                        setInputError('');
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          submitInput();
                        }
                      }}
                      suppressContentEditableWarning
                    />
                  </div>
                  {inputError && <p className="error-text">{inputError}</p>}
                  <button className="btn btn-secondary" onClick={submitInput} disabled={isEmpty}>
                    Submit
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="verify-actions">
            <button className="btn btn-ghost" onClick={() => dispatch({ type: 'goTo', stage: 'registration' })}>
              Back
            </button>
            <button className="btn btn-primary btn-lg" disabled={!canProceed} onClick={() => dispatch({ type: 'startTest' })}>
              {resuming ? 'Resume test' : 'Proceed'}
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
