import { questions } from '../data/test';
import { Modal } from './Modal';

interface Props {
  answers: Record<number, number>;
  revisit: number[];
  onConfirm: () => void;
  onClose: () => void;
}

export function FinishDialog({ answers, revisit, onConfirm, onClose }: Props) {
  const attempted = Object.keys(answers).length;
  const unanswered = questions.length - attempted;

  return (
    <Modal
      title="Finish test?"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Continue test</button>
          <button className="btn btn-finish" onClick={onConfirm}>Submit test</button>
        </>
      }
    >
      <div className="summary-grid">
        <div className="summary answered"><strong>{attempted}</strong><span>Answered</span></div>
        <div className="summary unanswered"><strong>{unanswered}</strong><span>Not answered</span></div>
        <div className="summary revisit"><strong>{revisit.length}</strong><span>Marked to revisit</span></div>
      </div>
      <p className="muted">
        {unanswered > 0
          ? `You have ${unanswered} unanswered question${unanswered === 1 ? '' : 's'}. `
          : 'You have answered every question. '}
        Once submitted, you can’t change your responses.
      </p>
    </Modal>
  );
}
