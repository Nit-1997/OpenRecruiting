/**
 * Base URL for SERVER-side calls to the backend (route handlers, server
 * components) — never for anything that reaches the browser.
 *
 * Why this is not NEXT_PUBLIC_API_V2_URL. That is a browser value: in this stack
 * it is http://localhost:8004, which from inside the landing container resolves
 * to the container itself, so a server-side fetch to it fails outright. The
 * upstream project this was forked from used one variable for both audiences and
 * got away with it because its value was a public API hostname — reachable from
 * the browser AND from inside a container. This stack path-routes a single
 * tunnel hostname and keeps the apps on localhost, so the two audiences
 * genuinely need different values.
 *
 * Deliberately no NEXT_PUBLIC_ fallback: Next inlines those into the client
 * bundle at build time (see lib/__tests__/no-build-time-config.test.ts), and
 * falling back to the browser value would silently restore the bug this exists
 * to prevent. Compose-internal default matches the other service-to-service
 * URLs in .env (cortex-backend, the workers).
 *
 * Read at CALL time — a module-level const captures whatever was set at first
 * import, which is the bug the consent submit route already documents.
 */
export function serverBackendUrl(): string {
  return process.env.BACKEND_INTERNAL_URL || 'http://backend:8004';
}
