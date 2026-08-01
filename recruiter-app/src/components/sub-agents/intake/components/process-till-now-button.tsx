'use client';

import { useProcessTillNow } from '@/hooks/intake/use-process-till-now';

export function ProcessTillNowButton() {
  const { runReprocess, isReprocessing } = useProcessTillNow();

  return (
    <button
      id="v2-intake-process-till-now-button"
      data-testid="v2-intake-process-till-now-button"
      type="button"
      onClick={() => void runReprocess()}
      disabled={isReprocessing}
      className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-wide transition disabled:opacity-50 disabled:cursor-not-allowed"
      style={{
        background: 'var(--app-secondary)',
        border: '1px solid var(--cortex-500)',
        color: 'var(--cortex-500)',
      }}
      title="Re-run the prefill with the conversation so far folded in"
    >
      {isReprocessing && (
        <span
          id="v2-intake-process-till-now-spinner"
          data-testid="v2-intake-process-till-now-spinner"
          className="inline-block h-3 w-3 rounded-full border-2 border-t-transparent animate-spin"
          aria-hidden="true"
          style={{ borderColor: 'var(--cortex-500)', borderTopColor: 'transparent' }}
        />
      )}
      {isReprocessing ? 'Processing...' : 'Process till now'}
    </button>
  );
}
