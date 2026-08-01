import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { realIntakeRealtime } from './__tests__/restore-real-api';

// Bun's mock.module must be set up before import to take effect.
let realtimePushCb: ((payload: unknown) => void) | null = null;
// Captured but not read in current tests — kept so future tests can drive
// channel status transitions (SUBSCRIBED / CHANNEL_ERROR / TIMED_OUT) without
// re-plumbing the mock module.
let subscribeCb: ((status: string) => void) | null = null;
void subscribeCb;
const removeChannelMock = mock(() => {});

mock.module('@/lib/supabase', () => ({
  getSupabaseClientOrNull: () => ({
    // Stubbed because fetchIntakeSession -> authHeader() -> sb.auth.getSession().
    // Without this, authHeader throws before fetch is called and the test asserts
    // fail with 0 fetch calls. Returning a null session matches the un-authed
    // dev path in api.ts (authHeader returns {} when there's no token).
    auth: {
      getSession: async () => ({ data: { session: null } }),
    },
    channel: () => ({
      on: (_a: unknown, _b: unknown, cb: (p: unknown) => void) => {
        realtimePushCb = cb;
        return {
          subscribe: (sb: (status: string) => void) => {
            subscribeCb = sb;
            return {};
          },
        };
      },
    }),
    removeChannel: removeChannelMock,
  }),
}));

const fetchMock = mock(async () =>
  new Response(JSON.stringify({ id: 'sess-1', status: 'created' }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  }),
);

const ORIGINAL_FETCH = globalThis.fetch;

beforeEach(() => {
  realtimePushCb = null;
  subscribeCb = null;
  removeChannelMock.mockClear();
  fetchMock.mockClear();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

describe('subscribeSession', () => {
  test('immediately fetches the session once on subscribe', async () => {
    const { subscribeIntakeSession } = realIntakeRealtime();
    const onChange = mock((_s: unknown) => {});
    const sub = subscribeIntakeSession({ sessionId: 'sess-1', onChange, pollMs: null });
    // allow microtask to run
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(onChange.mock.calls.length).toBeGreaterThanOrEqual(1);
    sub.unsubscribe();
  });

  test('re-fetches session on realtime UPDATE push', async () => {
    const { subscribeIntakeSession } = realIntakeRealtime();
    const onChange = mock((_s: unknown) => {});
    const sub = subscribeIntakeSession({ sessionId: 'sess-1', onChange, pollMs: null });
    await new Promise((r) => setTimeout(r, 10));
    const before = fetchMock.mock.calls.length;
    realtimePushCb?.({ new: { id: 'sess-1' } });
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock.mock.calls.length).toBe(before + 1);
    sub.unsubscribe();
  });

  test('unsubscribe removes the supabase channel', async () => {
    const { subscribeIntakeSession } = realIntakeRealtime();
    const sub = subscribeIntakeSession({
      sessionId: 'sess-1',
      onChange: () => {},
      pollMs: null,
    });
    sub.unsubscribe();
    expect(removeChannelMock.mock.calls.length).toBe(1);
  });
});
