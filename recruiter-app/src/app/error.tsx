'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { trackError } from '@/lib/track-error';

/**
 * Root-level error boundary (Next.js 16 `error.tsx` convention).
 *
 * Error boundaries MUST be Client Components. Next forwards `{ error, reset }`
 * — `reset()` re-renders the boundary's children to attempt recovery. (Next
 * 16.2 also exposes `unstable_retry`, which additionally re-fetches; we use
 * the stable `reset` here.) This boundary does NOT wrap the root layout — a
 * crash in the root layout/template is handled by `global-error.tsx`.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    trackError('app.error_boundary', error);
  }, [error]);

  return (
    <main
      id="app-error-root"
      role="alert"
      aria-live="assertive"
      className="flex min-h-screen flex-col items-center justify-center gap-5 bg-canvas px-6 text-center"
    >
      <span
        id="app-error-mark"
        aria-hidden
        className="font-serif text-2xl italic text-[var(--color-accent-agent)]"
      >
        OpenRecruiting
      </span>
      <h1 id="app-error-heading" className="font-serif text-2xl text-text-primary">
        Something went wrong
      </h1>
      <p id="app-error-message" className="max-w-md text-sm text-text-secondary">
        An unexpected error interrupted this view. You can try again, and we&apos;ve recorded what
        happened.
      </p>
      {error.digest ? (
        <p id="app-error-digest" className="font-mono text-xs text-text-secondary/70">
          Reference: {error.digest}
        </p>
      ) : null}
      <Button id="app-error-retry" variant="primary" onClick={() => reset()}>
        Try again
      </Button>
    </main>
  );
}
