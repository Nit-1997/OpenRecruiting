/**
 * Browser-visible configuration, resolved at RUNTIME rather than build time.
 *
 * Next.js inlines `process.env.NEXT_PUBLIC_*` into the client bundle when
 * `next build` runs, so a changed `.env` needs an image rebuild rather than a
 * container restart. `next.config.ts` sets `output: 'standalone'`, so a Node
 * server runs at request time and `process.env` IS live there; the root layout
 * reads it and emits `window.__OR_CONFIG__` once, and client code reads that.
 *
 * This app had it worse than the others: its Dockerfile declared NO build args
 * at all, so `NEXT_PUBLIC_API_URL` was simply `undefined` in the bundle and
 * every read fell through to its hardcoded default. See getStatusUrl in
 * src/app/[sessionToken]/page.tsx — the default was port 8000, while the
 * backend listens on 8004, so status polling never reached anything.
 *
 * SECURITY: this object is serialised into HTML any visitor can read, and this
 * page is loaded by the Recall meeting bot on a public URL. Only public values
 * may be added — no keys, no tokens.
 */

export interface RuntimeConfig {
  apiUrl: string;
}

/** Every env var this module reads. */
export const RUNTIME_CONFIG_KEYS = ['NEXT_PUBLIC_API_URL'] as const;

export const RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config';

const GLOBAL_KEY = '__OR_CONFIG__';

/** SERVER ONLY. Reads live process.env. */
export function serverRuntimeConfig(): RuntimeConfig {
  return { apiUrl: process.env.NEXT_PUBLIC_API_URL ?? '' };
}

/** Isomorphic. Prefers the injected object so server and client passes agree. */
export function getRuntimeConfig(): RuntimeConfig {
  const injected = (globalThis as Record<string, unknown>)[GLOBAL_KEY] as
    | Partial<RuntimeConfig>
    | undefined;
  if (injected) return { ...serverRuntimeConfig(), ...injected };
  return serverRuntimeConfig();
}

/** The exact string the layout injects. */
export function runtimeConfigScript(config: RuntimeConfig): string {
  // JSON.stringify does NOT escape `<`, so a value containing "</script>" would
  // terminate the tag early and inject arbitrary markup.
  const json = JSON.stringify(config).replace(/</g, '\\u003c');
  return `window.${GLOBAL_KEY}=${json};`;
}
