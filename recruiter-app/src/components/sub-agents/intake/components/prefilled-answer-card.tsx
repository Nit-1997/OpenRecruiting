'use client';

import type { AnswerState, Confidence, QuestionSnapshot } from '@/types/intake';

interface Props {
  id: string;
  question: QuestionSnapshot;
  answer: AnswerState | undefined;
}

const CONF_CLASS: Record<Confidence, string> = {
  high: 'bg-emerald-50 text-emerald-700',
  medium: 'bg-blue-50 text-blue-700',
  low: 'bg-amber-50 text-amber-700',
  none: 'bg-[var(--surface-accent)] text-[var(--text-muted)]',
};

export function PrefilledAnswerCard({ id, question, answer }: Props) {
  const conf: Confidence = answer?.extraction_confidence ?? 'none';
  const text = answer?.text ?? null;
  return (
    <div id={id} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <div id={`${id}-header`} className="mb-2 flex items-center justify-between">
        <span
          id={`${id}-topic`}
          className="text-xs uppercase tracking-wide text-[var(--text-muted)]"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          Q{question.order} · {question.topic}
        </span>
        <span
          id={`${id}-confidence`}
          data-confidence={conf}
          className={`rounded px-2 py-0.5 text-xs ${CONF_CLASS[conf]}`}
        >
          {conf}
        </span>
      </div>
      <div id={`${id}-text`} className="text-sm text-[var(--text-primary)]">
        {text ?? (
          <span className="italic text-[var(--text-muted)]">
            empty — we'll cover this in conversation
          </span>
        )}
      </div>
      {answer?.sources && answer.sources.length > 0 && (
        <div id={`${id}-sources`} className="mt-2 text-xs text-[var(--text-muted)]">
          Sources: {answer.sources.join(', ')}
        </div>
      )}
    </div>
  );
}
