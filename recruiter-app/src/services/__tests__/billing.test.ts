// billing.ts is a v2-only service: `getOverview` forwards to
// `v2Client.get('/api/v2/billing/overview')` and returns the response as the
// (flat) `BillingOverview` domain type. These tests mock `@/lib/v2-client`
// (same idiom as v2-wiring.test.ts) and assert the request + passthrough.
//
// `src/domain/billing.ts` is a flat credit budget: there are no plans or
// subscriptions, so the overview carries only the org's intake/interview
// totals and usage.
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import type { BillingOverview } from '@/domain';

beforeEach(() => {
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  delete process.env.NEXT_PUBLIC_API_URL;
});

type Call = { method: string; path: string };
const calls: Call[] = [];
let nextResponse: unknown = null;

function resetMock() {
  calls.length = 0;
  nextResponse = null;
}

mock.module('@/lib/v2-client', () => {
  // Spread the REAL module: mock.module is process-wide last-writer-wins, so a
  // partial replacement would strip resolveV2Token/runV2UnauthorizedHandler for
  // any concurrently-scheduled test file and break cross-file `instanceof
  // V2ApiError`. Only v2Client is stubbed; everything else stays real.
  const actual = require('@/lib/v2-client');
  function record<T>(method: string, path: string): Promise<T> {
    calls.push({ method, path });
    return Promise.resolve(nextResponse as T);
  }
  return {
    ...actual,
    v2Client: {
      get: (path: string) => record('GET', path),
      post: (path: string) => record('POST', path),
      put: (path: string) => record('PUT', path),
      delete: (path: string) => record('DELETE', path),
    },
    setV2TokenGetter: () => {},
  };
});

// Imported after the mock is registered so the service binds to the stub.
import * as billing from '../billing';

beforeEach(() => resetMock());
afterEach(() => resetMock());

describe('billing service', () => {
  test('getOverview GETs /api/v2/billing/overview and returns the credit budget', async () => {
    const overview: BillingOverview = {
      intake_total: 25,
      intake_used: 4,
      interview_total: 250,
      interview_used: 68,
    };
    nextResponse = overview;

    const o = await billing.getOverview();

    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('GET');
    expect(call.path).toBe('/api/v2/billing/overview');

    expect(o.interview_total).toBe(250);
    expect(o.interview_used).toBe(68);
    expect(o.intake_total).toBe(25);
    expect(o.intake_used).toBe(4);
  });

  test('passes the unlimited sentinel through untouched', async () => {
    nextResponse = {
      intake_total: -1,
      intake_used: 3,
      interview_total: -1,
      interview_used: 9,
    } satisfies BillingOverview;

    const o = await billing.getOverview();

    expect(o.intake_total).toBe(-1);
    expect(o.interview_total).toBe(-1);
  });
});
