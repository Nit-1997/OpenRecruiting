/**
 * Test-only switches. NOT runtime configuration.
 *
 * Split out of lib/env.ts so that file can be held to the "no client module
 * reads process.env.NEXT_PUBLIC_*" rule without an allowlist entry that would
 * also cover its real settings. The distinction matters: everything in
 * lib/runtime-config.ts is an operator-facing value that must be changeable by
 * restarting a container, whereas the flag below only ever moves in a test
 * process, where `process.env` is genuinely live because the code runs in Node
 * rather than in a browser bundle.
 *
 * In a production browser bundle NEXT_PUBLIC_V2_API is unset, so this compiles
 * to `undefined !== 'false'` — constant true. That is the intended behaviour:
 * the v2 API is the only path, and tests opt out to drive the in-memory
 * mock-db helpers without HTTP.
 */

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
