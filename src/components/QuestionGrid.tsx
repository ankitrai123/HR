import { questions, test } from '../data/test';
import { Modal } from './Modal';
import { pillState } from './QuestionNav';

interface Props {
  currentIndex: number;
  answers: Record<number, number>;
  revisit: number[];
  onSelect: (index: number) => void;
  onClose: () => void;
}

export function QuestionGrid({ currentIndex, answers, revisit, onSelect, onClose }: Props) {
  return (
    <Modal title="All questions" onClose={onClose} wide>
      <div className="legend">
        <span><i className="q-pill answered" /> Answered</span>
        <span><i className="q-pill unanswered" /> Not answered</span>
        <span><i className="q-pill revisit" /> Revisit later</span>
        <span><i className="q-pill current" /> Current</span>
      </div>
      {test.sections.map((section, s) => (
        <div key={section.sectionId} className="grid-section">
          <h3>{s + 1}. {section.sectionTitle}</h3>
          <div className="q-grid">
            {questions
              .filter((q) => q.sectionIndex === s)
              .map((q) => (
                <button
                  key={q.id}
                  className={`q-pill ${pillState(q.id, answers, revisit)}${q.number - 1 === currentIndex ? ' current' : ''}`}
                  onClick={() => {
                    onSelect(q.number - 1);
                    onClose();
                  }}
                >
                  {q.number}
                </button>
              ))}
          </div>
        </div>
      ))}
    </Modal>
  );
}
