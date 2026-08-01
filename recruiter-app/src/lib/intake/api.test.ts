import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { expectIntakeApiError, realIntakeApi } from './__tests__/restore-real-api';

// Exercise the GENUINE module — other test files mock `@/lib/intake/api`
// process-wide. See restore-real-api.ts. `IntakeApiError` identity is asserted
// via `expectIntakeApiError` because bun's module mocking decouples the class.
const { createIntakeSession, fetchIntakeSession, listIntakeSessions } = realIntakeApi();

const ORIGINAL_FETCH = globalThis.fetch;
let fetchMock: ReturnType<typeof mock>;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8004';
  fetchMock = mock(async () => new Response('{}', { status: 200 }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

describe('createIntakeSession', () => {
  test('POSTs JSON to /api/v2/intake/sessions and returns ids', async () => {
    fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ session_id: 's1', requisition_id: 'r1' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await createIntakeSession({
      form_data: {
        role_name: 'BE',
        experience_min: 1,
        experience_max: 5,
        location: 'NYC',
        jd_text: null,
      },
      entry_point: 'intake_tab',
    });

    expect(out).toEqual({ session_id: 's1', requisition_id: 'r1' });
    const call = fetchMock.mock.calls[0];
    expect(String(call?.[0])).toContain('/api/v2/intake/sessions');
    const init = call?.[1] as RequestInit | undefined;
    expect(init?.method).toBe('POST');
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' });
  });
});

describe('listIntakeSessions', () => {
  test('GETs /api/v2/intake/sessions and returns sessions array', async () => {
    fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await listIntakeSessions();
    expect(out).toEqual({ sessions: [] });
    expect(fetchMock.mock.calls[0]?.[1]?.method ?? 'GET').toBe('GET');
  });
});

describe('fetchIntakeSession', () => {
  test('GETs /api/v2/intake/sessions/<id>', async () => {
    fetchMock = mock(
      async (url) =>
        new Response(JSON.stringify({ id: String(url).split('/').pop() }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await fetchIntakeSession('abc-123');
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v2/intake/sessions/abc-123');
    expect((out as { id: string }).id).toBe('abc-123');
  });
});

describe('error normalization', () => {
  test('non-2xx throws IntakeApiError with detail', async () => {
    fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ detail: 'session not found' }), {
          status: 404,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await fetchIntakeSession('missing');
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 404, detail: 'session not found' });
  });

  test('403 with feature_disabled code is tagged', async () => {
    fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ detail: 'v2 intake is not enabled for your organization' }), {
          status: 403,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await listIntakeSessions();
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 403, code: 'feature_disabled' });
  });

  test('network failure throws IntakeApiError with status=0', async () => {
    fetchMock = mock(async () => {
      throw new TypeError('Failed to fetch');
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await listIntakeSessions();
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 0 });
  });

  test('object detail (db_error envelope) is NOT leaked raw to the user', async () => {
    // Backend returns the safe-but-internal envelope {error, code}. The UI must
    // never render this verbatim (e.g. {"error":"db_error","code":"23514"}).
    fetchMock = mock(
      async () =>
        new Response(JSON.stringify({ detail: { error: 'db_error', code: '23514' } }), {
          status: 400,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let err: unknown;
    try {
      await createIntakeSession({
        form_data: {
          role_name: 'BE',
          experience_min: 7,
          experience_max: null,
          location: 'NYC',
          jd_text: null,
        },
        entry_point: 'create_role_btn',
      });
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 400 });
    const detail = (err as { detail: string }).detail;
    expect(detail).not.toContain('db_error');
    expect(detail).not.toContain('23514');
  });
});
