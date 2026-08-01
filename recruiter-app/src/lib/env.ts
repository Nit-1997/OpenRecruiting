// Runtime env access for the v2 backend.
//
// The mock-DB path is no longer the default — the FE talks to /api/v2/*
// out of the box. The only remaining purpose of `isV2ApiEnabled` is to
// let unit tests opt OUT (set `NEXT_PUBLIC_V2_API=false`) so they can
// drive code against the in-memory mock-db helpers without hitting HTTP.

// Single base-URL resolver for the v2 backend. Read at CALL TIME (never cached
// at module load) so it reflects the current env.
//
// Variable precedence (FE-F4):
//  1. NEXT_PUBLIC_API_V2_URL — the documented prod var for recruiter-app.
//  2. NEXT_PUBLIC_API_URL    — legacy alias still set in .env-nextjs-v2.
//
// Dev fallback is a single value (`:8004`, the backend's actual port). In
// production, an UNSET base is a misconfiguration: we throw a clear error
// rather than silently pointing every request at localhost (which would 5xx in
// confusing ways or, worse, hit a developer's machine).
const DEV_FALLBACK_BASE = 'http://localhost:8004';

export function getV2ApiBase(): string {
  if (typeof process === 'undefined') return DEV_FALLBACK_BASE;
  const base = process.env.NEXT_PUBLIC_API_V2_URL || process.env.NEXT_PUBLIC_API_URL;
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

/**
 * Returns `true` unless the env var is explicitly set to `"false"`. The
 * default flipped — previously this was opt-IN to v2; now v2 is the
 * default and tests opt OUT.
 *
 * Long-term, every call site of this should be removed and the dead
 * mock-path branches deleted. Until then the helper stays as a single
 * choke point.
 */
export function isV2ApiEnabled(): boolean {
  if (typeof process === 'undefined') return true;
  return process.env.NEXT_PUBLIC_V2_API !== 'false';
}

export const USE_V2_API: boolean = isV2ApiEnabled();
