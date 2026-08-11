// Runtime env access for the v2 backend.
//
// The mock-DB path is no longer the default — the FE talks to /api/v2/*
// out of the box. The test-only opt-out now lives in lib/test-flags.ts and is
// re-exported below so existing import sites keep working.

// Single base-URL resolver for the v2 backend. Read at CALL TIME from the
// RUNTIME CONFIG, not from process.env.
//
// It used to read the raw NEXT_PUBLIC_ environment entries here, and the
// comment claimed doing so "reflects the current env". That was false in the
// browser: Next.js substitutes those reads at BUILD time, so every client caller
// held whatever value was set when the image was built, and a restart could not
// change it.
// This is the base URL for every backend call the app makes, so it was the most
// consequential instance of that bug in the repo. See lib/runtime-config.ts.
//
// Variable precedence (FE-F4) is unchanged:
//  1. NEXT_PUBLIC_API_V2_URL — the documented prod var for recruiter-app.
//  2. NEXT_PUBLIC_API_URL    — legacy alias still set in .env-nextjs-v2.
//
// Dev fallback is a single value (`:8004`, the backend's actual port). In
// production, an UNSET base is a misconfiguration: we throw a clear error
// rather than silently pointing every request at localhost (which would 5xx in
// confusing ways or, worse, hit a developer's machine).
import { getRuntimeConfig } from '@/lib/runtime-config';

export { isV2ApiEnabled, USE_V2_API } from '@/lib/test-flags';

const DEV_FALLBACK_BASE = 'http://localhost:8004';

export function getV2ApiBase(): string {
  if (typeof process === 'undefined') return DEV_FALLBACK_BASE;
  const cfg = getRuntimeConfig();
  const base = cfg.apiV2Url || cfg.apiUrl;
  if (base && base.length > 0) return base;
  if (process.env.NODE_ENV === 'production') {
    throw new Error(
      'Missing backend base URL: set NEXT_PUBLIC_API_V2_URL (or NEXT_PUBLIC_API_URL). ' +
        'Refusing to fall back to localhost in production.',
    );
  }
  return DEV_FALLBACK_BASE;
}

// Legacy eager const (consumed by src/app/verify/page.tsx). Kept for back-compat
// but resolved defensively so a module-load-time eval can never crash the bundle
// when the base is unset — the throwing contract lives in getV2ApiBase().
export const V2_API_BASE: string = (() => {
  try {
    return getV2ApiBase();
  } catch {
    return DEV_FALLBACK_BASE;
  }
})();
