'use client';

import { Check, Pencil, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Guideline } from '@/types';

export interface GuidelineRowProps {
  id: string;
  index: number;
  guideline: Guideline;
  onSave: (patch: { title: string; description: string }) => void;
  onDelete: (index: number) => void;
}

export function GuidelineRow({ id, index, guideline, onSave, onDelete }: GuidelineRowProps) {
  const rowId = `${id}-${index}`;
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(guideline.title);
  const [description, setDescription] = useState(guideline.description);
  const titleRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing) titleRef.current?.focus();
  }, [editing]);

  const commit = () => {
    const t = title.trim();
    if (!t) return;
    onSave({ title: t, description: description.trim() });
    setEditing(false);
  };

  const cancel = () => {
    setTitle(guideline.title);
    setDescription(guideline.description);
    setEditing(false);
  };

  return (
    <div
      id={rowId}
      className="flex items-start gap-3 rounded-[12px] border border-border bg-surface px-3 py-3"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {editing ? (
          <div className="flex flex-col gap-2">
            <input
              id={`${rowId}-title-input`}
              ref={titleRef}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
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
            <span id={`${rowId}-title`} className="text-[14px] text-text-primary leading-snug">
              {guideline.title}
            </span>
            <span
              id={`${rowId}-description`}
              className="text-[12.5px] text-text-muted leading-relaxed"
            >
              {guideline.description}
            </span>
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
              onClick={() => onDelete(index)}
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
