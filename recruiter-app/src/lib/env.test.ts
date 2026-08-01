import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { getV2ApiBase } from './env';

// env.ts is the single base-URL resolver. These tests pin the var-precedence
// + fail-loud-in-prod contract (FE-F4).
//
// NODE_ENV is `test` under `bun test`, so the production fail-loud branch is
// exercised by temporarily forcing NODE_ENV='production' and restoring it.

const ORIGINAL = {
  v2: process.env.NEXT_PUBLIC_API_V2_URL,
  legacy: process.env.NEXT_PUBLIC_API_URL,
  nodeEnv: process.env.NODE_ENV,
};

function clearBaseVars(): void {
  delete process.env.NEXT_PUBLIC_API_V2_URL;
  delete process.env.NEXT_PUBLIC_API_URL;
}

beforeEach(() => {
  clearBaseVars();
});

afterEach(() => {
  if (ORIGINAL.v2 === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL.v2;
  if (ORIGINAL.legacy === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = ORIGINAL.legacy;
  if (ORIGINAL.nodeEnv === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = ORIGINAL.nodeEnv;
});

describe('getV2ApiBase — variable precedence', () => {
  test('prefers the documented NEXT_PUBLIC_API_V2_URL', () => {
    process.env.NEXT_PUBLIC_API_V2_URL = 'http://localhost:8004';
    process.env.NEXT_PUBLIC_API_URL = 'https://legacy.example';
    expect(getV2ApiBase()).toBe('http://localhost:8004');
  });

  test('falls back to NEXT_PUBLIC_API_URL when the v2 var is unset', () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8004';
    expect(getV2ApiBase()).toBe('http://localhost:8004');
  });

  test('reflects the env at call time (no stale module-load const)', () => {
    process.env.NEXT_PUBLIC_API_V2_URL = 'https://first.example';
    expect(getV2ApiBase()).toBe('https://first.example');
    process.env.NEXT_PUBLIC_API_V2_URL = 'https://second.example';
    expect(getV2ApiBase()).toBe('https://second.example');
  });
});

describe('getV2ApiBase — fallback + fail-loud', () => {
  test('falls back to localhost:8004 in non-production when unset', () => {
    process.env.NODE_ENV = 'development';
    expect(getV2ApiBase()).toBe('http://localhost:8004');
  });

  test('THROWS in production when the base is unset (no silent localhost)', () => {
    process.env.NODE_ENV = 'production';
    expect(() => getV2ApiBase()).toThrow(/NEXT_PUBLIC_API_V2_URL/);
  });

  test('does NOT throw in production when the base IS set', () => {
    process.env.NODE_ENV = 'production';
    process.env.NEXT_PUBLIC_API_V2_URL = 'http://localhost:8004';
    expect(getV2ApiBase()).toBe('http://localhost:8004');
  });
});
