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
 * "Client-bundled" is broader than "has 'use client'": a module without the
 * directive still ships to the browser if a client component imports it.
 * `lib/auth/gate.ts` and `lib/supabase/client.ts` are both in that category.
 * Genuinely server-only modules (middleware, route handlers, sitemap,
 * lib/supabase/server.ts) keep reading process.env — they see live values
 * already, and changing them would be churn.
 *
 * SECURITY: this object is serialised into HTML any visitor can read. Only
 * public values may be added. The PostHog key here is a publishable project
 * key, which is designed to be shipped to browsers.
 */

export interface RuntimeConfig {
  supabaseUrl: string;
  supabaseAnonKey: string;
  cookieDomain: string;
  apiUrl: string;
  apiV2Url: string;
  appUrl: string;
  posthogHost: string;
  posthogKey: string;
}

/** Every env var this module reads. */
export const RUNTIME_CONFIG_KEYS = [
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_ANON_KEY',
  'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
  'NEXT_PUBLIC_COOKIE_DOMAIN',
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_API_V2_URL',
  'NEXT_PUBLIC_APP_URL',
  'NEXT_PUBLIC_POSTHOG_HOST',
  'NEXT_PUBLIC_POSTHOG_KEY',
] as const;

export const RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config';

const GLOBAL_KEY = '__OR_CONFIG__';

/** SERVER ONLY. Reads live process.env. */
export function serverRuntimeConfig(): RuntimeConfig {
  const env = (name: string): string => process.env[name] ?? '';
  return {
    supabaseUrl: env('NEXT_PUBLIC_SUPABASE_URL'),
    // supabase rebranded "anon public" -> "publishable"; same key, two names.
    supabaseAnonKey:
      env('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY') || env('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
    cookieDomain: env('NEXT_PUBLIC_COOKIE_DOMAIN'),
    apiUrl: env('NEXT_PUBLIC_API_URL'),
    apiV2Url: env('NEXT_PUBLIC_API_V2_URL'),
    appUrl: env('NEXT_PUBLIC_APP_URL'),
    posthogHost: env('NEXT_PUBLIC_POSTHOG_HOST'),
    posthogKey: env('NEXT_PUBLIC_POSTHOG_KEY'),
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
