/**
 * Browser-visible configuration, resolved at RUNTIME rather than build time.
 *
 * Why this exists. Next.js inlines `process.env.NEXT_PUBLIC_*` into the client
 * bundle when `next build` runs, so changing one of those values and restarting
 * the container does nothing — the old value is already compiled into the
 * JavaScript served to the browser. Nine such variables exist across this repo
 * and two of them are the Supabase URL and anon key, which means a self-hoster
 * could paste correct credentials, watch the backend start working, and still
 * be unable to log in, with nothing anywhere explaining why.
 *
 * `next.config.ts` sets `output: 'standalone'`, so a Node server runs at request
 * time and `process.env` IS live server-side. The root layout reads these values
 * there and emits them once as `window.__OR_CONFIG__`; client code reads that.
 * A restart is then enough.
 *
 * The variables keep their `NEXT_PUBLIC_` names in `.env` on purpose — this
 * change is about WHERE they are read, not what they are called, and renaming
 * them would churn every deploy environment for no benefit.
 *
 * SECURITY: everything here is serialised into HTML that any visitor can read.
 * Only public values may be added. `runtime-config.test.ts` fails the build if a
 * key name suggests a secret.
 */

export interface RuntimeConfig {
  supabaseUrl: string;
  supabaseAnonKey: string;
  cookieDomain: string;
  apiUrl: string;
  apiV2Url: string;
  appUrl: string;
  landingUrl: string;
  assessmentUiUrl: string;
  intakeVoiceOfferUrl: string;
  feedbackVoiceOfferUrl: string;
  screeningVoiceOfferUrl: string;
  /** Public URL of the Cortex MCP server, shown on the integrations page for
   *  pasting into Claude. Must be the tunnel host, not a compose-internal or
   *  localhost address — the client resolving it is Claude, not this browser.
   *  Blank renders a "not configured" state rather than a fake endpoint. */
  cortexMcpUrl: string;
}

/** Every env var this module reads. The tests assert every entry is
 *  NEXT_PUBLIC_-prefixed and none looks like a secret. */
export const RUNTIME_CONFIG_KEYS = [
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_ANON_KEY',
  'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
  'NEXT_PUBLIC_COOKIE_DOMAIN',
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_API_V2_URL',
  'NEXT_PUBLIC_APP_URL',
  'NEXT_PUBLIC_LANDING_URL',
  'NEXT_PUBLIC_ASSESSMENT_UI_URL',
  'NEXT_PUBLIC_INTAKE_VOICE_OFFER_URL',
  'NEXT_PUBLIC_FEEDBACK_VOICE_OFFER_URL',
  'NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL',
  'NEXT_PUBLIC_CORTEX_MCP_URL',
] as const;

export const RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config';

/** The global the layout writes and the client reads. */
const GLOBAL_KEY = '__OR_CONFIG__';

/** SERVER ONLY. Reads live process.env. Safe in server components, route
 *  handlers and middleware; returns blanks if called in the browser. */
export function serverRuntimeConfig(): RuntimeConfig {
  const env = (name: string): string => process.env[name] ?? '';
  return {
    supabaseUrl: env('NEXT_PUBLIC_SUPABASE_URL'),
    // supabase rebranded "anon public" -> "publishable"; same key, two names.
    supabaseAnonKey:
      env('NEXT_PUBLIC_SUPABASE_ANON_KEY') || env('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY'),
    cookieDomain: env('NEXT_PUBLIC_COOKIE_DOMAIN'),
    apiUrl: env('NEXT_PUBLIC_API_URL'),
    apiV2Url: env('NEXT_PUBLIC_API_V2_URL'),
    appUrl: env('NEXT_PUBLIC_APP_URL'),
    landingUrl: env('NEXT_PUBLIC_LANDING_URL'),
    assessmentUiUrl: env('NEXT_PUBLIC_ASSESSMENT_UI_URL'),
    intakeVoiceOfferUrl: env('NEXT_PUBLIC_INTAKE_VOICE_OFFER_URL'),
    feedbackVoiceOfferUrl: env('NEXT_PUBLIC_FEEDBACK_VOICE_OFFER_URL'),
    screeningVoiceOfferUrl: env('NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL'),
    cortexMcpUrl: env('NEXT_PUBLIC_CORTEX_MCP_URL'),
  };
}

/** Isomorphic. Use this everywhere except the layout that does the injecting.
 *  Prefers the injected object so a server pass and a client pass agree. */
export function getRuntimeConfig(): RuntimeConfig {
  const injected = (globalThis as Record<string, unknown>)[GLOBAL_KEY] as
    | Partial<RuntimeConfig>
    | undefined;
  if (injected) {
    return { ...serverRuntimeConfig(), ...injected };
  }
  return serverRuntimeConfig();
}

/** The exact string the layout injects. Exported so a test can assert the
 *  payload without rendering React. */
export function runtimeConfigScript(config: RuntimeConfig): string {
  // JSON.stringify does NOT escape `<`, so a value containing "</script>" would
  // terminate the tag early and inject arbitrary markup. Escaping every `<` as
  // < is the standard fix and is still valid JS inside the string literal.
  const json = JSON.stringify(config).replace(/</g, '\\u003c');
  return `window.${GLOBAL_KEY}=${json};`;
}
