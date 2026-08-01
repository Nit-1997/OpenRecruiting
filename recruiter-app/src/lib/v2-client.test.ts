// FE-T1: coverage for the production HTTP backbone (src/lib/v2-client.ts).
//
// Two bun realities drive the import strategy here:
//
// 1. `@/lib/v2-client` is mocked PROCESS-WIDE by 5 service/store test files
//    (billing/team/v2-wiring/v2-no-fabrication/auth-store). `mock.module` is
//    last-writer-wins and bun loads every file's top-level mocks before any
//    test runs, so a plain `import { v2Client } from './v2-client'` here would
//    resolve to a leaker's stub (a `record()` recorder, not the real fetch
//    wrapper). We therefore read the GENUINE module from the `__REAL_V2_CLIENT__`
//    snapshot captured in src/test-setup.ts at preload — same trick the FE-F4
//    intake auth-refresh test uses.
//
// 2. `globalThis.fetch` is process-global. We install a scoped mock per test and
//    restore the captured pristine fetch in afterEach (test-setup.ts also has a
//    backstop afterEach). No `mockResolvedValueOnce` leakage across files.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { realV2Client } from './intake/__tests__/restore-real-api';

const { v2Client, setV2TokenGetter, setV2UnauthorizedHandler, V2ApiError } = realV2Client();

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;
const ORIGINAL_API_URL = process.env.NEXT_PUBLIC_API_URL;

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

// bun's Mock typing reports `.mock.calls[0]` as `[] | undefined`, which trips
// `noUncheckedIndexedAccess` + strict tuple casts. Centralize the single
// `as unknown` hop here so each test reads the (url, init, headers) it expects
// without peppering casts everywhere.
type FetchMock = { mock: { calls: unknown[] } };

function callAt(
  fetchMock: FetchMock,
  index: number,
): { url: string; init: RequestInit; headers: Record<string, string> } {
  const args = fetchMock.mock.calls[index] as unknown as [string, RequestInit];
  const init = args[1] ?? ({} as RequestInit);
  return {
    url: String(args[0]),
    init,
    headers: (init.headers ?? {}) as Record<string, string>,
  };
}

beforeEach(() => {
  // getV2ApiBase() reads this at call time; pin a deterministic base so URL
  // assertions are stable and we never fall through to a localhost default.
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
  // Start every test with a clean token source + no 401 handler so nothing
  // leaks from a prior test (or a prior file's no-op stub).
  setV2TokenGetter(async () => null);
  setV2UnauthorizedHandler(null);
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  setV2TokenGetter(async () => null);
  setV2UnauthorizedHandler(null);
});

afterAll(() => {
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
  if (ORIGINAL_API_URL === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = ORIGINAL_API_URL;
});

describe('v2-client - request basics', () => {
  test('GET builds the URL from getV2ApiBase(), sets Accept + X-Request-ID, no body', async () => {
    const fetchMock = mock(async () => jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await v2Client.get<{ ok: boolean }>('/api/v2/roles');

    expect(out).toEqual({ ok: true });
    const { url, init, headers } = callAt(fetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/roles');
    expect(init.method).toBe('GET');
    expect(init.cache).toBe('no-store');
    expect(init.credentials).toBe('include');
    expect(headers.Accept).toBe('application/json');
    expect(typeof headers['X-Request-ID']).toBe('string');
    expect((headers['X-Request-ID'] ?? '').length).toBeGreaterThan(0);
    // GET has no body, so no Content-Type.
    expect(headers['Content-Type']).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  test('relative path is normalized to a leading slash', async () => {
    const fetchMock = mock(async () => jsonResponse({}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await v2Client.get('api/v2/team');

    expect(callAt(fetchMock, 0).url).toBe('http://backend.test/api/v2/team');
  });

  test('POST serializes the body and sets Content-Type', async () => {
    const fetchMock = mock(async () => jsonResponse({ id: 'r1' }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await v2Client.post<{ id: string }>('/api/v2/roles', { title: 'PM' });

    expect(out).toEqual({ id: 'r1' });
    const { init, headers } = callAt(fetchMock, 0);
    expect(init.method).toBe('POST');
    expect(headers['Content-Type']).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ title: 'PM' }));
  });

  test('Bearer token from the registered getter lands in the Authorization header', async () => {
    setV2TokenGetter(async () => 'tok-123');
    const fetchMock = mock(async () => jsonResponse({}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await v2Client.get('/api/v2/roles');

    expect(callAt(fetchMock, 0).headers.Authorization).toBe('Bearer tok-123');
  });

  test('per-call token override wins over the getter and is sent', async () => {
    setV2TokenGetter(async () => 'getter-token');
    const fetchMock = mock(async () => jsonResponse({}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await v2Client.get('/api/v2/roles', { token: 'override-token' });

    expect(callAt(fetchMock, 0).headers.Authorization).toBe('Bearer override-token');
  });

  test('ifMatch + correlationId become If-Match + X-Correlation-ID headers', async () => {
    const fetchMock = mock(async () => jsonResponse({}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await v2Client.put(
      '/api/v2/plan/reorder',
      { order: [] },
      {
        ifMatch: 'etag-99',
        correlationId: 'corr-7',
      },
    );

    const { headers } = callAt(fetchMock, 0);
    expect(headers['If-Match']).toBe('etag-99');
    expect(headers['X-Correlation-ID']).toBe('corr-7');
  });

  test('204 No Content resolves to undefined', async () => {
    const fetchMock = mock(async () => new Response(null, { status: 204 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await v2Client.delete('/api/v2/roles/r1');
    expect(out).toBeUndefined();
  });

  test('200 with an empty body resolves to undefined (DELETE-style)', async () => {
    const fetchMock = mock(async () => new Response('', { status: 200 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await v2Client.delete('/api/v2/roles/r1');
    expect(out).toBeUndefined();
  });

  test('a thrown fetch is mapped to a network ServiceError', async () => {
    const fetchMock = mock(async () => {
      throw new Error('socket hang up');
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string; message?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as { code?: string; message?: string };
    }
    expect(err?.code).toBe('network');
    expect(err?.message).toBe('socket hang up');
  });
});

describe('v2-client - 401 refresh-retry', () => {
  test('401 → refresh returns true → retries once with the fresh token → success', async () => {
    let token = 'stale';
    setV2TokenGetter(() => token);
    const refresh = mock(async () => {
      token = 'fresh';
      return true;
    });
    setV2UnauthorizedHandler(refresh);

    const authHeaders: Array<string | null> = [];
    const requestIds: Array<string | undefined> = [];
    const fetchMock = mock(async (_url: string, init: RequestInit) => {
      const headers = init.headers as Record<string, string>;
      authHeaders.push(headers.Authorization ?? null);
      requestIds.push(headers['X-Request-ID']);
      if (authHeaders.length === 1) {
        return new Response(JSON.stringify({ detail: 'expired' }), { status: 401 });
      }
      return jsonResponse({ ok: true });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await v2Client.get<{ ok: boolean }>('/api/v2/roles');

    expect(out).toEqual({ ok: true });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.length).toBe(2);
    expect(authHeaders[0]).toBe('Bearer stale');
    expect(authHeaders[1]).toBe('Bearer fresh');
    // The replay reuses the SAME X-Request-ID so the backend sees one logical attempt.
    expect(requestIds[0]).toBe(requestIds[1]);
  });

  test('401 → refresh returns false → fails closed as a forbidden ServiceError, no replay', async () => {
    setV2TokenGetter(() => 'stale');
    const refresh = mock(async () => false);
    setV2UnauthorizedHandler(refresh);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string; httpStatus?: number } | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as { code?: string; httpStatus?: number };
    }
    expect(err?.code).toBe('forbidden');
    expect(err?.httpStatus).toBe(401);
    expect(refresh).toHaveBeenCalledTimes(1);
    // Single attempt only — no second replay after a declined refresh.
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  test('401 → handler throws → treated as declined, surfaces forbidden, no replay', async () => {
    setV2TokenGetter(() => 'stale');
    const refresh = mock(async () => {
      throw new Error('refresh blew up');
    });
    setV2UnauthorizedHandler(refresh);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('forbidden');
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  test('401 with no handler registered surfaces forbidden (legacy behavior)', async () => {
    setV2TokenGetter(() => 'stale');
    setV2UnauthorizedHandler(null);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('forbidden');
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  test('a pinned token override skips the 401-refresh path entirely', async () => {
    const refresh = mock(async () => true);
    setV2UnauthorizedHandler(refresh);

    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles', { token: 'pinned' });
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('forbidden');
    expect(refresh).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.length).toBe(1);
  });
});

describe('v2-client - error status mapping', () => {
  test('X-Request-ID from the response is carried onto the thrown ServiceError', async () => {
    const fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ detail: 'bad input' }), {
          status: 422,
          headers: { 'X-Request-ID': 'req-abc' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string; requestId?: string; message?: string } | undefined;
    try {
      await v2Client.post('/api/v2/roles', {});
    } catch (e) {
      err = e as { code?: string; requestId?: string; message?: string };
    }
    expect(err?.code).toBe('validation');
    expect(err?.requestId).toBe('req-abc');
    // 4xx detail is user-facing copy and surfaces as-is.
    expect(err?.message).toBe('bad input');
  });

  test('400 and 422 map to validation', async () => {
    for (const status of [400, 422]) {
      const fetchMock = mock(async () => new Response(JSON.stringify({ detail: 'x' }), { status }));
      globalThis.fetch = fetchMock as unknown as typeof fetch;
      let err: { code?: string } | undefined;
      try {
        await v2Client.post('/api/v2/roles', {});
      } catch (e) {
        err = e as { code?: string };
      }
      expect(err?.code).toBe('validation');
    }
  });

  test('404 maps to not_found', async () => {
    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'gone' }), { status: 404 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: { code?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles/missing');
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('not_found');
  });

  test('409 maps to conflict', async () => {
    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'dup' }), { status: 409 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: { code?: string } | undefined;
    try {
      await v2Client.post('/api/v2/candidates', {});
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('conflict');
  });

  test('412 (stale If-Match) maps to a conflict with the retry-prompt copy', async () => {
    const fetchMock = mock(
      async () => new Response(JSON.stringify({ detail: 'precondition failed' }), { status: 412 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: { code?: string; message?: string } | undefined;
    try {
      await v2Client.put('/api/v2/plan/reorder', { order: [] }, { ifMatch: 'old-etag' });
    } catch (e) {
      err = e as { code?: string; message?: string };
    }
    expect(err?.code).toBe('conflict');
    expect(err?.message).toBe('Plan was modified by another user — please retry.');
  });

  test('428 also maps to the conflict retry-prompt', async () => {
    const fetchMock = mock(async () => new Response(JSON.stringify({}), { status: 428 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: { code?: string; message?: string } | undefined;
    try {
      await v2Client.put('/api/v2/plan/reorder', { order: [] });
    } catch (e) {
      err = e as { code?: string; message?: string };
    }
    expect(err?.code).toBe('conflict');
    expect(err?.message).toBe('Plan was modified by another user — please retry.');
  });

  test('5xx detail is REDACTED: generic message to the user, raw detail stashed for triage', async () => {
    const warnings: string[] = [];
    const consoleObj = globalThis.console as { warn: (...a: unknown[]) => void };
    const originalWarn = consoleObj.warn;
    consoleObj.warn = (...a: unknown[]) => {
      warnings.push(a.map(String).join(' '));
    };

    const fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ detail: 'RPC error: 42704 constraint xyz' }), {
          status: 500,
          headers: { 'X-Request-ID': 'req-500' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err:
      | { code?: string; message?: string; rawDetail?: string; requestId?: string }
      | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as typeof err;
    } finally {
      consoleObj.warn = originalWarn;
    }

    expect(err?.code).toBe('internal');
    // The user NEVER sees the raw SQL noise.
    expect(err?.message).toBe('Something went wrong. Please try again.');
    expect(err?.message).not.toContain('RPC error');
    // ...but it IS preserved for devs, and logged for triage with the request id.
    expect(err?.rawDetail).toBe('RPC error: 42704 constraint xyz');
    expect(err?.requestId).toBe('req-500');
    expect(warnings.some((w) => w.includes('RPC error') && w.includes('req-500'))).toBe(true);
  });

  test('non-JSON error body still yields a ServiceError with a default message', async () => {
    const fetchMock = mock(
      async () => new Response('<html>502 Bad Gateway</html>', { status: 502 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: { code?: string; message?: string } | undefined;
    try {
      await v2Client.get('/api/v2/roles');
    } catch (e) {
      err = e as { code?: string; message?: string };
    }
    expect(err?.code).toBe('internal');
    expect(err?.message).toBe('Something went wrong. Please try again.');
  });
});

describe('v2-client - V2ApiError shape', () => {
  test('constructs with status/code/detail/requestId and a default message', () => {
    const e = new V2ApiError({ status: 503 });
    expect(e.name).toBe('V2ApiError');
    expect(e.status).toBe(503);
    expect(e.message).toBe('v2 API error (503)');

    const withDetail = new V2ApiError({
      status: 422,
      code: 'bad_field',
      detail: 'email invalid',
      requestId: 'req-1',
    });
    expect(withDetail.message).toBe('email invalid');
    expect(withDetail.code).toBe('bad_field');
    expect(withDetail.requestId).toBe('req-1');
  });
});
