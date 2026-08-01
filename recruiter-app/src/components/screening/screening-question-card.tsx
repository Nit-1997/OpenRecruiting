'use client';

import { Check, Pencil, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { ScreeningQuestion } from '@/services/screening';

export interface ScreeningQuestionCardProps {
  id: string;
  /** Zero-based position in the list; rendered 1-based + zero-padded (Q01). */
  index: number;
  question: ScreeningQuestion;
  onChange: (next: ScreeningQuestion) => void;
  onRemove?: () => void;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

export function ScreeningQuestionCard({
  id,
  index,
  question,
  onChange,
  onRemove,
}: ScreeningQuestionCardProps) {
  const [editing, setEditing] = useState(false);
  const label = `Q${pad2(index + 1)}`;

  const set = (patch: Partial<ScreeningQuestion>) => {
    onChange({ ...question, ...patch });
  };

  return (
    <article
      id={id}
      className="rounded-[12px] border border-cortex-500/25 bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="flex items-start justify-between gap-2">
        <span
          id={`${id}-label`}
          className="font-medium font-mono text-[11px] text-cortex-500 uppercase tracking-[0.16em]"
        >
          {label} · {question.title || 'Untitled'}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <button
            id={`${id}-edit`}
            type="button"
            aria-label={editing ? 'Done editing question' : 'Edit question'}
            aria-pressed={editing}
            onClick={() => setEditing((v) => !v)}
            className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted transition hover:bg-surface hover:text-text-primary"
          >
            {editing ? (
              <Check strokeWidth={2} className="h-3.5 w-3.5" />
            ) : (
              <Pencil strokeWidth={1.75} className="h-3.5 w-3.5" />
            )}
          </button>
          {onRemove && (
            <button
              id={`${id}-remove`}
              type="button"
              aria-label="Remove question"
              onClick={onRemove}
              className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted transition hover:bg-[#FEF2F2] hover:text-[#B91C1C]"
            >
              <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </header>

      {editing ? (
        <div className="mt-3 flex flex-col gap-2.5">
          <label className="flex flex-col gap-1" htmlFor={`${id}-edit-title`}>
            <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
              Title
            </span>
            <input
              id={`${id}-edit-title`}
              value={question.title}
              onChange={(e) => set({ title: e.target.value })}
              className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1" htmlFor={`${id}-edit-prompt`}>
            <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
              Prompt
            </span>
            <textarea
              id={`${id}-edit-prompt`}
              value={question.prompt}
              onChange={(e) => set({ prompt: e.target.value })}
              rows={2}
              className="resize-y rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1" htmlFor={`${id}-edit-probe`}>
            <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
              Probe
            </span>
            <input
              id={`${id}-edit-probe`}
              value={question.probe}
              onChange={(e) => set({ probe: e.target.value })}
              className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-muted focus:border-cortex-500 focus:outline-none"
            />
          </label>
          <div className="grid grid-cols-3 gap-2">
            <label className="flex flex-col gap-1" htmlFor={`${id}-edit-duration`}>
              <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
                Duration (min)
              </span>
              <input
                id={`${id}-edit-duration`}
                type="number"
                min={1}
                max={60}
                value={question.durationMinutes}
                onChange={(e) => set({ durationMinutes: Number(e.target.value) || 0 })}
                className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1" htmlFor={`${id}-edit-signal`}>
              <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
                Signal
              </span>
              <input
                id={`${id}-edit-signal`}
                value={question.signal}
                onChange={(e) => set({ signal: e.target.value })}
                className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1" htmlFor={`${id}-edit-dimension`}>
              <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
                Dimension
              </span>
              <input
                id={`${id}-edit-dimension`}
                value={question.dimension}
                onChange={(e) => set({ dimension: e.target.value })}
                className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
              />
            </label>
          </div>
        </div>
      ) : (
        <>
          <p
            id={`${id}-prompt`}
            className="mt-2 font-medium text-[13.5px] text-text-primary leading-snug"
          >
            {question.prompt}
          </p>
          {question.probe && (
            <p
              id={`${id}-probe`}
              className="mt-1.5 font-serif text-[12.5px] text-text-muted italic"
            >
              ↳ probe: {question.probe}
            </p>
          )}
          <div
            id={`${id}-footer`}
            className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-border border-t pt-2.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]"
          >
            <span>
              Duration <span className="text-text-primary">{question.durationMinutes} min</span>
            </span>
            {question.signal && (
              <span>
                Signal <span className="text-text-primary">{question.signal}</span>
              </span>
            )}
          </div>
        </>
      )}
    </article>
  );
}
