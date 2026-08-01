'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { trackError } from '@/lib/track-error';

/**
 * Shell-scoped error boundary (Next.js 16 `error.tsx` convention).
 *
 * Because `error.tsx` does NOT wrap the layout in its OWN segment, this
 * boundary renders INSIDE `(shell)/layout.tsx` — so a rail/registry crash
 * recovers within the shell chrome (top bar, rails) instead of blanking the
 * whole app. It is a contained panel, not a full-screen takeover. Must be a
 * Client Component; receives `{ error, reset }`.
 */
export default function ShellError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    trackError('app.shell_error_boundary', error);
  }, [error]);

  return (
    <section
      id="shell-error-root"
      role="alert"
      aria-live="assertive"
      className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center"
    >
      <h2 id="shell-error-heading" className="font-serif text-xl text-text-primary">
        This view ran into a problem
      </h2>
      <p id="shell-error-message" className="max-w-sm text-sm text-text-secondary">
        Something failed to load in this panel. The rest of your workspace is unaffected — try
        reloading this view.
      </p>
      {error.digest ? (
        <p id="shell-error-digest" className="font-mono text-xs text-text-secondary/70">
          Reference: {error.digest}
        </p>
      ) : null}
      <Button id="shell-error-retry" variant="secondary" onClick={() => reset()}>
        Try again
      </Button>
    </section>
  );
}
