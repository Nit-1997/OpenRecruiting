'use client';

// Browser-side Supabase client for recruiter-app.
//
// Uses @supabase/ssr with COOKIE storage under the SHARED `openrecruiting-auth` key +
// `NEXT_PUBLIC_COOKIE_DOMAIN`, identical to landing / recruiter-app v1 (see
// packages/shared-lib/src/supabase/client.ts). This is what makes SSO seamless:
// the session cookie set when a recruiter logs in on landing is on the
// same domain (.localhost:3000 in prod, `localhost` in dev — cookies are domain-
// scoped, NOT port-scoped) and is read directly here. No separate app-v2 login.
//
// The matching server client + middleware (src/middleware.ts) refresh the
// cookie and gate protected routes, redirecting unauthenticated users to the
// landing login.

import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { getRuntimeConfig } from '@/lib/runtime-config';

const COOKIE_NAME = 'openrecruiting-auth';

let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;
  // Read at CALL time from the runtime config, not at module load from
  // process.env. The old module-level reads were inlined into the client bundle
  // at build time, so a self-hoster who fixed their Supabase credentials and
  // restarted still got the stale ones and could not log in, with no error
  // saying why. The "anon public" → "publishable" rename is handled inside
  // serverRuntimeConfig(); both names still work.
  const { supabaseUrl: url, supabaseAnonKey: anonKey, cookieDomain } = getRuntimeConfig();
  if (!url || !anonKey) {
    throw new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'NEXT_PUBLIC_SUPABASE_ANON_KEY (or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY), ' +
        'then restart the recruiter-app container — these are read at runtime, ' +
        'so no image rebuild is needed.',
    );
  }
  _client = createBrowserClient(url, anonKey, {
    auth: {
      storageKey: COOKIE_NAME,
    },
    cookieOptions: {
      name: COOKIE_NAME,
      ...(cookieDomain ? { domain: cookieDomain } : {}),
    },
  });
  return _client;
}

// Convenience: returns null when env vars are missing instead of throwing.
export function getSupabaseClientOrNull(): SupabaseClient | null {
  try {
    return getSupabaseClient();
  } catch {
    return null;
  }
}
