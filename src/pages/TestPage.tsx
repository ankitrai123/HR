import { useCallback, useEffect, useState, type Dispatch } from 'react';
import { FinishDialog } from '../components/FinishDialog';
import { Footer } from '../components/Footer';
import { Bookmark, ChevronLeft, ChevronRight, Eraser } from '../components/Icons';
import { QuestionGrid } from '../components/QuestionGrid';
import { QuestionNav } from '../components/QuestionNav';
import { TestHeader, type TextSize } from '../components/TestHeader';
import { questions, test } from '../data/test';
import { useNow, type SessionAction, type SessionState } from '../hooks/useSession';

interface Props {
  state: SessionState;
  dispatch: Dispatch<SessionAction>;
  lastSavedAt: number;
}

export function TestPage({ state, dispatch, lastSavedAt }: Props) {
  const now = useNow(1000);
  const [gridOpen, setGridOpen] = useState(false);
  const [finishOpen, setFinishOpen] = useState(false);
  const [textSize, setTextSize] = useState<TextSize>('normal');

  const deadline = (state.startedAt ?? now) + test.durationMinutes * 60_000;
  const remainingMs = deadline - now;
  const index = Math.min(state.currentIndex, questions.length - 1);
  const question = questions[index];
  const selected = state.answers[question.id];
  const isRevisit = state.revisit.includes(question.id);

  const goTo = useCallback(
    (i: number) => dispatch({ type: 'setIndex', index: Math.max(0, Math.min(questions.length - 1, i)) }),
    [dispatch],
  );

  // Auto-submit when time runs out.
  useEffect(() => {
    if (remainingMs <= 0) dispatch({ type: 'submit', reason: 'timeout' });
  }, [remainingMs, dispatch]);

  // Keyboard shortcuts: arrows to navigate, 1–N to answer.
  useEffect(() => {
    if (gridOpen || finishOpen) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      // Radios are excluded from the skip list so arrows on a focused option navigate questions
      // instead of triggering the browser's native "select next radio" behaviour.
      const isTextEntry = target.closest(
        'input:not([type="radio"]):not([type="checkbox"]), select, textarea, [contenteditable="true"]',
      );
      if (isTextEntry || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        goTo(index + (e.key === 'ArrowRight' ? 1 : -1));
      } else {
        const n = Number(e.key);
        if (Number.isInteger(n) && n >= 1 && n <= question.options.length) {
          dispatch({ type: 'answer', questionId: question.id, option: n - 1 });
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [gridOpen, finishOpen, index, question, goTo, dispatch]);

  const closeGrid = useCallback(() => setGridOpen(false), []);
  const closeFinish = useCallback(() => setFinishOpen(false), []);

  return (
    <div className={`test-shell text-${textSize}`}>
      <TestHeader
        remainingMs={remainingMs}
        savedSecondsAgo={Math.max(0, Math.floor((now - lastSavedAt) / 1000))}
        textSize={textSize}
        onTextSizeChange={setTextSize}
        onFinish={() => setFinishOpen(true)}
      />
      <QuestionNav
        currentIndex={index}
        answers={state.answers}
        revisit={state.revisit}
        onSelect={goTo}
        onOpenGrid={() => setGridOpen(true)}
      />

      <main className="test-main">
        <button className="edge-arrow edge-left" onClick={() => goTo(index - 1)} disabled={index === 0} aria-label="Previous question">
          <ChevronLeft size={28} />
        </button>

        <div className="test-columns">
          <section className="question-panel" aria-labelledby="question-heading">
            <div className="panel-head">
              <h2 id="question-heading">Question {question.number}</h2>
              <button
                className={`revisit-toggle${isRevisit ? ' active' : ''}`}
                aria-pressed={isRevisit}
                onClick={() => dispatch({ type: 'toggleRevisit', questionId: question.id })}
              >
                <Bookmark size={16} filled={isRevisit} /> Revisit Later
              </button>
            </div>
            <p className="question-text">{question.questionText}</p>
          </section>

          <section className="response-panel" aria-label="Response">
            <div className="panel-head">
              <span className="muted">Select one option</span>
              <button
                className="link-btn"
                disabled={selected === undefined}
                onClick={() => dispatch({ type: 'clearAnswer', questionId: question.id })}
              >
                <Eraser size={15} /> Clear Response
              </button>
            </div>
            <div className="options" role="radiogroup" aria-labelledby="question-heading">
              {question.options.map((option, i) => {
                const checked = selected === i;
                return (
                  <label key={option} className={`option-card${checked ? ' selected' : ''}`}>
                    <input
                      type="radio"
                      name={`q-${question.id}`}
                      checked={checked}
                      onChange={() => dispatch({ type: 'answer', questionId: question.id, option: i })}
                    />
                    <span className="option-radio" aria-hidden="true" />
                    <span className="option-label">{option}</span>
                    <kbd className="option-key" aria-hidden="true">{i + 1}</kbd>
                  </label>
                );
              })}
            </div>
            <div className="response-foot">
              {index < questions.length - 1 ? (
                <button className="btn btn-primary" onClick={() => goTo(index + 1)}>
                  {selected === undefined ? 'Skip' : 'Save & Next'} <ChevronRight size={16} />
                </button>
              ) : (
                <button className="btn btn-finish" onClick={() => setFinishOpen(true)}>Review & Finish</button>
              )}
            </div>
          </section>
        </div>

        <button className="edge-arrow edge-right" onClick={() => goTo(index + 1)} disabled={index === questions.length - 1} aria-label="Next question">
          <ChevronRight size={28} />
        </button>
      </main>

      <Footer />

      {gridOpen && (
        <QuestionGrid currentIndex={index} answers={state.answers} revisit={state.revisit} onSelect={goTo} onClose={closeGrid} />
      )}
      {finishOpen && (
        <FinishDialog
          answers={state.answers}
          revisit={state.revisit}
          onClose={closeFinish}
          onConfirm={() => dispatch({ type: 'submit', reason: 'manual' })}
        />
      )}
    </div>
  );
}
