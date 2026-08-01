'use client';

import { useEffect } from 'react';
import { trackError } from '@/lib/track-error';

/**
 * Global error boundary (Next.js 16 `global-error.tsx` convention).
 *
 * This file REPLACES the root layout when a crash escapes the root
 * layout/template, so it MUST render its own `<html>` and `<body>` tags — the
 * design-token CSS variables and fonts from the root layout are NOT guaranteed
 * to be present, so we style with self-contained inline styles. Like all error
 * boundaries it must be a Client Component and receives `{ error, reset }`.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    trackError('app.global_error_boundary', error);
  }, [error]);

  return (
    <html id="global-error-html" lang="en">
      <body
        id="global-error-body"
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '20px',
          padding: '24px',
          textAlign: 'center',
          background: '#f7f6f3',
          color: '#1a1a1a',
          fontFamily: 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
        }}
      >
        <main id="global-error-root" role="alert" aria-live="assertive">
          <h1
            id="global-error-heading"
            style={{ fontSize: '24px', fontWeight: 600, margin: '0 0 8px' }}
          >
            Something went wrong
          </h1>
          <p
            id="global-error-message"
            style={{ fontSize: '14px', maxWidth: '28rem', margin: '0 auto 20px', opacity: 0.7 }}
          >
            OpenRecruiting hit an unexpected error and couldn&apos;t recover this page.
          </p>
          <button
            id="global-error-retry"
            type="button"
            onClick={() => reset()}
            style={{
              cursor: 'pointer',
              borderRadius: '9999px',
              border: 'none',
              background: '#1a1a1a',
              color: '#f7f6f3',
              padding: '10px 24px',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
