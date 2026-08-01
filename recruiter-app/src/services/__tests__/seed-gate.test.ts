// FE-F5 seed gate.
//
// The seed factory (`globalThis.__SEED`) is the lazy-seed hook the
// localStorage mock uses. In production (`isV2ApiEnabled()` true) it MUST NOT
// be registered — otherwise any service method still reading `getDb()` would
// fabricate data indistinguishable from real backend data.
//
// `registerSeedFactory()` (src/services/seed.ts) is the single gated entry
// point; AppShell calls it once on mount. These tests pin its env-gated
// behavior directly (no React render needed).
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';

import { afterAll, afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { registerSeedFactory } from '../seed';

type SeedGlobal = { __SEED?: unknown };

function clearSeedGlobal() {
  delete (globalThis as SeedGlobal).__SEED;
}

beforeEach(clearSeedGlobal);
afterEach(clearSeedGlobal);

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  delete process.env.NEXT_PUBLIC_API_URL;
});

describe('FE-F5 seed gate', () => {
  test('does NOT register the seed factory when v2 is enabled (production)', () => {
    process.env.NEXT_PUBLIC_V2_API = 'true';
    const registered = registerSeedFactory();
    expect(registered).toBe(false);
    expect((globalThis as SeedGlobal).__SEED).toBeUndefined();
  });

  test('registers the seed factory when v2 is disabled (mock/test path)', () => {
    process.env.NEXT_PUBLIC_V2_API = 'false';
    const registered = registerSeedFactory();
    expect(registered).toBe(true);
    expect(typeof (globalThis as SeedGlobal).__SEED).toBe('function');
  });
});
