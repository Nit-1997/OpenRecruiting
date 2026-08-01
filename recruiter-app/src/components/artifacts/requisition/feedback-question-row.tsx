'use client';

import { Check, Pencil, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { FeedbackQuestion } from '@/types';

export interface FeedbackQuestionRowProps {
  id: string;
  question: FeedbackQuestion;
  onSave: (patch: { heading: string; description: string | null }) => void;
  onDelete: (questionId: string) => void;
}

export function FeedbackQuestionRow({ id, question, onSave, onDelete }: FeedbackQuestionRowProps) {
  const rowId = `${id}-${question.id}`;
  const [editing, setEditing] = useState(false);
  const [heading, setHeading] = useState(question.heading);
  const [description, setDescription] = useState(question.description ?? '');
  const headingRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing) headingRef.current?.focus();
  }, [editing]);

  const commit = () => {
    const trimmedHeading = heading.trim();
    if (!trimmedHeading) return;
    onSave({
      heading: trimmedHeading,
      description: description.trim() ? description.trim() : null,
    });
    setEditing(false);
  };

  const cancel = () => {
    setHeading(question.heading);
    setDescription(question.description ?? '');
    setEditing(false);
  };

  return (
    <div
      id={rowId}
      className="flex items-start gap-3 rounded-[12px] border border-border bg-surface px-3 py-3"
    >
      <span
        aria-hidden
        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border bg-bg font-mono text-[10.5px] text-text-muted"
      >
        {question.questionNumber}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {editing ? (
          <div className="flex flex-col gap-2">
            <input
              id={`${rowId}-heading-input`}
              ref={headingRef}
              type="text"
              value={heading}
              onChange={(e) => setHeading(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit();
                if (e.key === 'Escape') cancel();
              }}
              className="rounded-md border border-border bg-bg px-2 py-1 text-[14px] text-text-primary outline-none focus:border-cortex-500"
            />
            <textarea
              id={`${rowId}-description-input`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') cancel();
              }}
              rows={2}
              className="rounded-md border border-border bg-bg px-2 py-1 text-[13px] text-text-muted outline-none focus:border-cortex-500"
            />
          </div>
        ) : (
          <>
            <span id={`${rowId}-heading`} className="text-[14px] text-text-primary leading-snug">
              {question.heading}
            </span>
            {question.description && (
              <span
                id={`${rowId}-description`}
                className="text-[12.5px] text-text-muted leading-relaxed"
              >
                {question.description}
              </span>
            )}
          </>
        )}
      </div>
      <div className="flex shrink-0 items-start gap-1">
        {editing ? (
          <>
            <button
              id={`${rowId}-save`}
              type="button"
              onClick={commit}
              aria-label="Save"
              className="flex h-6 w-6 items-center justify-center rounded text-text-muted transition hover:text-cortex-500"
            >
              <Check strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
            <button
              id={`${rowId}-cancel`}
              type="button"
              onClick={cancel}
              aria-label="Cancel"
              className="flex h-6 w-6 items-center justify-center rounded text-text-muted transition hover:text-text-primary"
            >
              <X strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          </>
        ) : (
          <>
            <button
              id={`${rowId}-edit`}
              type="button"
              onClick={() => setEditing(true)}
              aria-label="Edit"
              className="flex h-6 w-6 items-center justify-center rounded text-text-muted transition hover:text-text-primary"
            >
              <Pencil strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
            <button
              id={`${rowId}-delete`}
              type="button"
              onClick={() => onDelete(question.id)}
              aria-label="Delete"
              className="flex h-6 w-6 items-center justify-center rounded text-text-muted transition hover:text-red-500"
            >
              <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
