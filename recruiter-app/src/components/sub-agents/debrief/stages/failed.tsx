'use client';

import { AlertTriangle } from 'lucide-react';
import { useSessionStore } from '@/stores';
import { retryFromFailure } from '../flow';

interface FailedStageProps {
  id: string;
}

/**
 * Terminal failure view for the debrief generation. Surfaces the real error
 * (timeout / backend failure) instead of silently swallowing it, and offers a
 * retry that returns to the candidate picker (selections are preserved).
 */
export function FailedStage({ id }: FailedStageProps) {
  const session = useSessionStore((s) => s.sessions.debrief);
  if (!session) return null;
  const error =
    (session.selections.generationError as string | undefined) ??
    'The debrief could not be generated.';

  return (
    <div id={id} className="flex max-w-[560px] flex-col gap-4 pt-8">
      <div id={`${id}-head`} className="flex items-center gap-2.5">
        <span
          id={`${id}-icon`}
          aria-hidden
          className="flex h-8 w-8 items-center justify-center rounded-full bg-[#FEF2F2] text-[#B91C1C]"
        >
          <AlertTriangle strokeWidth={1.75} className="h-4 w-4" />
        </span>
        <h3 id={`${id}-title`} className="font-display text-[20px] text-text-primary">
          Debrief generation failed
        </h3>
      </div>
      <p id={`${id}-message`} className="text-[13.5px] text-text-secondary leading-[1.5]">
        {error}
      </p>
      <div id={`${id}-actions`} className="flex items-center gap-2">
        <button
          id={`${id}-retry`}
          type="button"
          onClick={() => retryFromFailure()}
          className="inline-flex items-center rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium font-sans text-[13px] text-white transition-colors hover:bg-[#222]"
        >
          Back to candidate selection
        </button>
      </div>
    </div>
  );
}
