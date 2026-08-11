/**
 * Browser-visible configuration, resolved at RUNTIME rather than build time.
 *
 * Next.js inlines `process.env.NEXT_PUBLIC_*` into the client bundle when
 * `next build` runs, so a changed `.env` needs an image rebuild rather than a
 * container restart, and nothing says so. `next.config.ts` sets
 * `output: 'standalone'`, so a Node server runs at request time and
 * `process.env` IS live there; the root layout reads it and emits
 * `window.__OR_CONFIG__` once, and client-bundled code reads that.
 *
 * SECURITY: this object is serialised into HTML any visitor can read. Only
 * public values may be added — no service keys, no tokens. This app is
 * staff-only, but "staff-only" is an authorisation boundary, not a reason to
 * ship a secret to a browser.
 */

export interface RuntimeConfig {
  supabaseUrl: string;
  supabaseAnonKey: string;
  apiUrl: string;
  apiV2Url: string;
  assessmentUiUrl: string;
}

/** Every env var this module reads. */
export const RUNTIME_CONFIG_KEYS = [
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_API_V2_URL',
  'NEXT_PUBLIC_ASSESSMENT_UI_URL',
] as const;

export const RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config';

const GLOBAL_KEY = '__OR_CONFIG__';

/** SERVER ONLY. Reads live process.env. */
export function serverRuntimeConfig(): RuntimeConfig {
  const env = (name: string): string => process.env[name] ?? '';
  return {
    supabaseUrl: env('NEXT_PUBLIC_SUPABASE_URL'),
    supabaseAnonKey: env('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY'),
    apiUrl: env('NEXT_PUBLIC_API_URL'),
    apiV2Url: env('NEXT_PUBLIC_API_V2_URL'),
    assessmentUiUrl: env('NEXT_PUBLIC_ASSESSMENT_UI_URL'),
  };
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
