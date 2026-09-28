import { useEffect, useRef } from 'react';
import { questions, sectionStarts, test } from '../data/test';
import { ChevronLeft, ChevronRight, Grid, Info } from './Icons';

interface Props {
  currentIndex: number;
  answers: Record<number, number>;
  revisit: number[];
  onSelect: (index: number) => void;
  onOpenGrid: () => void;
}

export function pillState(questionId: number, answers: Record<number, number>, revisit: number[]) {
  if (revisit.includes(questionId)) return 'revisit';
  return questionId in answers ? 'answered' : 'unanswered';
}

export function QuestionNav({ currentIndex, answers, revisit, onSelect, onOpenGrid }: Props) {
  const current = questions[currentIndex];
  const sectionQuestions = questions.filter((q) => q.sectionIndex === current.sectionIndex);
  const attempted = Object.keys(answers).length;
  const trackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = trackRef.current?.querySelector<HTMLElement>('[aria-current="true"]');
    el?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  }, [currentIndex]);

  const scrollBy = (dir: number) => trackRef.current?.scrollBy({ left: dir * 240, behavior: 'smooth' });

  return (
    <div className="question-nav">
      <div className="section-picker">
        <select
          value={current.sectionIndex}
          onChange={(e) => onSelect(sectionStarts[Number(e.target.value)])}
          aria-label="Section"
        >
          {test.sections.map((s, i) => (
            <option key={s.sectionId} value={i}>
              {i + 1}. {s.sectionTitle}
            </option>
          ))}
        </select>
        <span className="tooltip-anchor" tabIndex={0} aria-label="Section info">
          <Info size={18} />
          <span className="tooltip" role="tooltip">
            {sectionQuestions.length} statements. Choose the option that best describes you. Use “Revisit Later” to
            flag a question and come back to it before finishing.
          </span>
        </span>
      </div>

      <div className="pill-strip">
        <button className="icon-btn strip-arrow" onClick={() => scrollBy(-1)} aria-label="Scroll questions left">
          <ChevronLeft size={16} />
        </button>
        <div className="pill-track" ref={trackRef}>
          {sectionQuestions.map((q) => {
            const index = q.number - 1;
            return (
              <button
                key={q.id}
                className={`q-pill ${pillState(q.id, answers, revisit)}${index === currentIndex ? ' current' : ''}`}
                aria-current={index === currentIndex}
                aria-label={`Question ${q.number}`}
                onClick={() => onSelect(index)}
              >
                {q.number}
              </button>
            );
          })}
        </div>
        <button className="icon-btn strip-arrow" onClick={() => scrollBy(1)} aria-label="Scroll questions right">
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="nav-controls">
        <span className="attempted">
          Attempted: <strong>{attempted}/{questions.length}</strong>
        </span>
        <button className="btn btn-outline btn-sm" disabled={currentIndex === 0} onClick={() => onSelect(currentIndex - 1)}>
          <ChevronLeft size={16} /> Previous
        </button>
        <button className="btn btn-outline btn-sm" disabled={currentIndex === questions.length - 1} onClick={() => onSelect(currentIndex + 1)}>
          Next <ChevronRight size={16} />
        </button>
        <button className="icon-btn icon-btn-bordered" onClick={onOpenGrid} aria-label="Question grid" title="All questions">
          <Grid size={16} />
        </button>
      </div>
    </div>
  );
}
