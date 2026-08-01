'use client';

import { Check, MoveRight, X } from 'lucide-react';
import { ProgressRing, StatusMark } from '@/components/sub-agents/intake/primitives';
import type { AnswerStatus, IntakeSession, QuestionId } from '@/types/intake';

interface Props {
  id: string;
  session: IntakeSession;
  submitting: boolean;
  errorMessage?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

// Mirrors the design's SubmitConfirm: a "captured vs not-yet" split with the
// reassurance that the remaining goals are optional. Confirms → submit.
export function SubmitConfirmModal({
  id,
  session,
  submitting,
  errorMessage,
  onConfirm,
  onClose,
}: Props) {
  const answers = session.current_answers ?? {};
  const questions = session.questions_snapshot ?? [];
  const statusOf = (qid: QuestionId): AnswerStatus => answers[qid]?.status ?? 'untouched';
  const isCaptured = (qid: QuestionId) => {
    const s = statusOf(qid);
    return s === 'validated' || s === 'discussed';
  };

  const captured = questions.filter((q) => isCaptured(q.id as QuestionId));
  const remaining = questions.filter((q) => !isCaptured(q.id as QuestionId));

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop is a progressive enhancement, not the primary control
    <div
      id={`${id}-scrim`}
      className="mz-modal-scrim"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: onClick only stops backdrop dismissal when clicking inside the dialog; not an interactive control */}
      <div
        id={id}
        className="mz-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Submit intake"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mz-modal-head">
          <ProgressRing value={captured.length} total={questions.length} size={56} stroke={5} />
          <div>
            <div className="mz-eyebrow">Submit intake</div>
            <h3 id={`${id}-title`} className="mz-modal-title">
              {captured.length} of {questions.length} goals captured
            </h3>
            <p className="mz-modal-sub">
              The remaining {remaining.length} are optional. OpenRecruiting will build the interview plan
              from what&rsquo;s covered — you can fill the rest anytime.
            </p>
          </div>
          <button
            id={`${id}-close`}
            type="button"
            className="mz-modal-x"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mz-modal-grid">
          <div className="mz-modal-col">
            <div className="mz-modal-coltitle">
              <Check size={13} color="var(--status-success-fg)" strokeWidth={3} />
              Captured · {captured.length}
            </div>
            <ul className="mz-modal-list">
              {captured.map((q) => (
                <li key={q.id}>
                  <StatusMark status={statusOf(q.id as QuestionId)} size={15} />
                  <span>{q.topic}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="mz-modal-col">
            <div className="mz-modal-coltitle mz-modal-coltitle-muted">
              Not yet · {remaining.length}
            </div>
            <ul className="mz-modal-list mz-modal-list-muted">
              {remaining.map((q) => (
                <li key={q.id}>
                  <StatusMark status={statusOf(q.id as QuestionId)} size={15} />
                  <span>{q.topic}</span>
                  {statusOf(q.id as QuestionId) === 'needs_probe' && (
                    <em className="mz-modal-flag">in progress</em>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {errorMessage && (
          <p id={`${id}-error`} role="alert" className="mb-3 text-sm text-[var(--danger-fg)]">
            {errorMessage}
          </p>
        )}

        <div className="mz-modal-foot">
          <button id={`${id}-cancel`} type="button" className="mz-btn-ghost" onClick={onClose}>
            Keep gathering
          </button>
          <button
            id={`${id}-confirm`}
            type="button"
            className="mz-btn-dark"
            onClick={onConfirm}
            disabled={submitting}
          >
            {submitting ? 'Submitting…' : 'Submit & build plan'}
            <MoveRight size={16} color="currentColor" />
          </button>
        </div>
      </div>
    </div>
  );
}
