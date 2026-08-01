import { describe, it, expect, mock, beforeEach, afterEach } from 'bun:test';
import { expectIntakeApiError, expectModalityConflictError, realIntakeApi } from './restore-real-api';

// Exercise the GENUINE module — other test files mock `@/lib/intake/api`
// process-wide (use-text-stream.test.tsx replaces `streamTextTurn` with a bare
// `mock()`, which would make these `for await` loops hang). See restore-real-api.ts.
const { streamTextTurn, endConversation } = realIntakeApi();

const originalFetch = globalThis.fetch;
let fetchMock: ReturnType<typeof mock>;

beforeEach(() => {
  fetchMock = mock(async () => new Response('{}', { status: 200 }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close();
        return;
      }
      const chunk = chunks[i++];
      if (chunk !== undefined) controller.enqueue(encoder.encode(chunk));
    },
  });
}

describe('streamTextTurn', () => {
  it('yields text/done events split across chunk boundaries', async () => {
    fetchMock.mockResolvedValue({
      status: 200,
      ok: true,
      body: makeStream([
        'event: text\ndata: "Hel',
        'lo "\n\nevent: text\ndata: "world"\n\n',
        'event: done\ndata: {"text":"Hello world","stop_reason":"end_turn","user_turn_idx":0,"assistant_turn_idx":1}\n\n',
      ]),
    });

    const events: any[] = [];
    for await (const ev of streamTextTurn('sess-1', 'hi')) events.push(ev);

    expect(events.filter(e => e.type === 'text').map(e => e.chunk)).toEqual(['Hello ', 'world']);
    const done = events.find(e => e.type === 'done');
    expect(done.assistant_turn_idx).toBe(1);
  });

  it('throws ModalityConflictError on 409 pre-flight before opening stream', async () => {
    fetchMock.mockResolvedValue({
      status: 409,
      ok: false,
      json: async () => ({
        detail: 'another mode is currently active — end the existing session first.',
        held: 'voice',
        requested: 'text',
      }),
    });
    let err: unknown;
    try {
      for await (const _ of streamTextTurn('sess-1', 'hi')) { /* */ }
    } catch (e) { err = e; }
    expectModalityConflictError(err, { held: 'voice', requested: 'text' });
  });

  it('throws IntakeApiError on non-409 failure', async () => {
    fetchMock.mockResolvedValue({
      status: 500,
      ok: false,
      json: async () => ({ detail: 'oops' }),
    });
    let err: unknown;
    try {
      for await (const _ of streamTextTurn('sess-1', 'hi')) { /* */ }
    } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 500 });
  });

  it('surfaces server error event mid-stream', async () => {
    fetchMock.mockResolvedValue({
      status: 200,
      ok: true,
      body: makeStream([
        'event: error\ndata: {"message":"boom","code":"internal_error"}\n\n',
      ]),
    });
    const events: any[] = [];
    for await (const ev of streamTextTurn('sess-1', 'hi')) events.push(ev);
    expect(events).toEqual([{ type: 'error', message: 'boom', code: 'internal_error' }]);
  });

  it('cancels via AbortSignal cleanly (no unhandled rejection)', async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation((_url: any, opts: any) => {
      return new Promise((_resolve, reject) => {
        // streamTextTurn suspends on `await authHeader()` before calling fetch,
        // so the caller's `controller.abort()` runs FIRST and the signal is
        // already aborted by the time we get here. Real fetch rejects
        // synchronously for an already-aborted signal; mirror that, otherwise
        // an addEventListener('abort') registered post-abort never fires and
        // this test hangs to its 5s timeout (which also leaks a never-settling
        // globalThis.fetch into concurrently-scheduled files).
        const signal: AbortSignal | undefined = opts?.signal;
        if (signal?.aborted) {
          reject(new DOMException('aborted', 'AbortError'));
          return;
        }
        signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      });
    });
    const p = (async () => {
      try {
        for await (const _ of streamTextTurn('sess-1', 'hi', controller.signal)) { /* */ }
        return 'no-error';
      } catch (e) {
        return (e as Error).name;
      }
    })();
    controller.abort();
    expect(await p).toBe('AbortError');
  });
});

describe('endConversation', () => {
  it('POSTs switch?to=none and returns session payload', async () => {
    fetchMock.mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ active_modality: null, session: { id: 'sess-1' } }),
    });
    const out = await endConversation('sess-1');
    expect(out.active_modality).toBeNull();
    const call = fetchMock.mock.calls[0];
    expect(String(call?.[0])).toContain('/api/v2/intake/sessions/sess-1/switch?to=none');
    expect((call?.[1] as RequestInit)?.method).toBe('POST');
  });

  it('throws IntakeApiError on non-2xx', async () => {
    fetchMock.mockResolvedValue({
      status: 502,
      ok: false,
      json: async () => ({ detail: 'voice agent did not drain cleanly' }),
    });
    let err: unknown;
    try { await endConversation('sess-1'); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 502 });
  });
});
