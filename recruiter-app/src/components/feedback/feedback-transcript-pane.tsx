'use client';

import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import { cleanBotText, type TranscriptTurn } from './feedback-transcript';

interface FeedbackTranscriptPaneProps {
  id?: string;
  open: boolean;
  turns: TranscriptTurn[];
  interim: string;
  onClose: () => void;
}

export function FeedbackTranscriptPane({
  id = 'feedback-transcript-pane',
  open,
  turns,
  interim,
  onClose,
}: FeedbackTranscriptPaneProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: turns/interim are intentional re-scroll triggers, not values read in the body
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, interim]);

  if (!open) return null;

  const isEmpty = turns.length === 0 && !interim;

  return (
    <aside
      id={id}
      aria-label="Call transcript"
      className="fixed top-0 right-0 z-50 flex h-dvh w-80 flex-col border-border border-l bg-bg/95 backdrop-blur-sm"
    >
      <div
        id={`${id}-header`}
        className="flex items-center justify-between border-border border-b px-4 py-3"
      >
        <span className="font-medium text-[13px] text-text-primary">Transcript</span>
        <button
          id={`${id}-close`}
          type="button"
          aria-label="Close transcript"
          onClick={onClose}
          className="flex h-6 w-6 items-center justify-center rounded text-text-muted transition-colors hover:text-text-primary"
        >
          <X strokeWidth={1.75} className="h-4 w-4" />
        </button>
      </div>

      <div
        id={`${id}-scroll`}
        ref={scrollRef}
        role="log"
        aria-live="polite"
        className="flex flex-1 flex-col gap-2 overflow-y-auto px-4 py-3"
      >
        {isEmpty ? (
          <p id={`${id}-empty`} className="text-[12.5px] text-text-muted">
            Transcript will appear here…
          </p>
        ) : (
          <>
            {turns.map((turn, i) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: append-only transcript turns are stable in order
                key={i}
                id={`${id}-turn-${i}`}
                className={cn(
                  'text-[13px] leading-[1.5]',
                  turn.role === 'user'
                    ? 'text-text-secondary'
                    : 'rounded-lg bg-surface px-3 py-2 text-text-primary',
                )}
              >
                <span className="mr-1 font-medium text-[11px] text-text-faint uppercase tracking-[0.08em]">
                  {turn.role === 'user' ? 'You' : 'OpenRecruiting'}
                </span>
                {turn.text}
              </div>
            ))}
            {interim && (
              <div
                id={`${id}-interim`}
                className="text-[13px] text-text-primary leading-[1.5] opacity-60"
              >
                <span className="mr-1 font-medium text-[11px] text-text-faint uppercase tracking-[0.08em]">
                  OpenRecruiting
                </span>
                {cleanBotText(interim)}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
