/**
 * Error reporting helper for App Router error boundaries.
 *
 * Mirrors the PostHog access pattern in `@/lib/intake/telemetry` (read the
 * client off `globalThis`, fail silently if it isn't initialized) and always
 * logs to the console so the error is observable in dev and in server logs.
 */
export function trackError(context: string, error: Error & { digest?: string }): void {
  // Always surface to the console — visible in the browser, in SSR logs, and
  // when PostHog is absent (tests, first paint before bootstrap).
  console.error(`[${context}]`, error);

  try {
    const ph = (
      globalThis as {
        posthog?: { capture: (event: string, props?: Record<string, unknown>) => void };
      }
    ).posthog;
    if (ph) {
      ph.capture('app.error_boundary', {
        context,
        message: error.message,
        digest: error.digest,
      });
    }
  } catch {
    // PostHog may not be initialized in test/SSR — fail silently.
  }
}
