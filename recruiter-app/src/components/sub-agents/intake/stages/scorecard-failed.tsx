'use client';

import { useState } from 'react';
import type { JSX } from 'react';
import type { IntakeSession } from '@/types/intake';
import { submitSession, IntakeApiError } from '@/lib/intake/api';

interface Props {
  session: IntakeSession;
  onRetried: () => void;
}

export function ScorecardFailed({ session, onRetried }: Props): JSX.Element {
  const [isRetrying, setIsRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function retry(): Promise<void> {
    setRetryError(null);
    setIsRetrying(true);
    try {
      await submitSession(session.id);
      onRetried();
    } catch (e) {
      setRetryError(e instanceof IntakeApiError ? e.detail : 'Retry failed. Try again later.');
    } finally {
      setIsRetrying(false);
    }
  }

  return (
    <div id="intake-stage-scorecard-failed" className="h-full flex flex-col items-center justify-center gap-4 text-slate-100 text-center px-6">
      <p className="font-dm-mono text-xs uppercase tracking-widest text-rose-400">Plan generation failed</p>
      <h2 className="font-instrument-serif text-2xl">We couldn't build the interview plan this time.</h2>
      <p className="text-sm text-slate-400 max-w-md">
        {session.process_error ?? 'An unknown error occurred.'}
      </p>
      <button
        id="intake-stage-scorecard-failed-retry"
        type="button"
        disabled={isRetrying}
        onClick={retry}
        className="px-4 py-2 rounded bg-cortex-600 text-slate-50 hover:bg-cortex-500 disabled:opacity-40"
      >
        {isRetrying ? 'Retrying...' : 'Retry'}
      </button>
      {retryError && (
        <p id="intake-stage-scorecard-failed-error" className="text-sm text-rose-400">{retryError}</p>
      )}
    </div>
  );
}
