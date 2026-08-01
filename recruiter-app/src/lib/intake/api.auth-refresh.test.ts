import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { expectIntakeApiError, realIntakeApi, realV2Client } from './__tests__/restore-real-api';

// FE-F4: intake calls must share v2-client's 401-refresh-retry + base resolver.
// Exercise the GENUINE module (other files mock @/lib/intake/api process-wide).
// Use the REAL v2-client setters (5 files mock @/lib/v2-client with no-op
// setters); the genuine api.ts reads the real module-global hooks these set.
const { listIntakeSessions } = realIntakeApi();
const { setV2TokenGetter, setV2UnauthorizedHandler } = realV2Client();

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://localhost:8004';
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  // Reset the shared v2-client auth hooks so other files start clean.
  setV2TokenGetter(async () => null);
  setV2UnauthorizedHandler(null);
  // Don't leak NEXT_PUBLIC_API_V2_URL into concurrently-scheduled files.
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
});

describe('intake 401-refresh-retry (shared with v2-client)', () => {
  test('retries once after a successful token refresh, then succeeds', async () => {
    let token = 'stale-token';
    setV2TokenGetter(() => token);
    const refresh = mock(async () => {
      token = 'fresh-token';
      return true;
    });
    setV2UnauthorizedHandler(refresh);

    const authHeaders: Array<string | null> = [];
    const fetchMock = mock(async (_url: string, init: RequestInit) => {
      const headers = init.headers as Record<string, string>;
      authHeaders.push(headers.Authorization ?? null);
      if (authHeaders.length === 1) {
        return new Response(JSON.stringify({ detail: 'expired' }), { status: 401 });
      }
      return new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await listIntakeSessions();
    expect(out).toEqual({ sessions: [] });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.length).toBe(2);
    expect(authHeaders[0]).toBe('Bearer stale-token');
    expect(authHeaders[1]).toBe('Bearer fresh-token');
  });

  test('fails closed (surfaces the 401) when the refresh handler returns false', async () => {
    setV2TokenGetter(() => 'stale-token');
    const refresh = mock(async () => false);
    setV2UnauthorizedHandler(refresh);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await listIntakeSessions();
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 401 });
    expect(refresh).toHaveBeenCalledTimes(1);
    // Exactly one retry attempt total (no second replay after a failed refresh).
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  test('surfaces the 401 with no handler registered (legacy behavior preserved)', async () => {
    setV2TokenGetter(() => 'stale-token');
    setV2UnauthorizedHandler(null);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await listIntakeSessions();
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 401 });
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  test('base URL comes from getV2ApiBase() at call time, not a stale const', async () => {
    setV2TokenGetter(async () => null);
    setV2UnauthorizedHandler(null);
    process.env.NEXT_PUBLIC_API_V2_URL = 'https://call-time.example';

    const fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listIntakeSessions();
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      'https://call-time.example/api/v2/intake/sessions',
    );
  });
});
