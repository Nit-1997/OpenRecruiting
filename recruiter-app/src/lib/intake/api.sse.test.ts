import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import {
  expectIntakeApiError,
  expectModalityConflictError,
  realIntakeApi,
  realV2Client,
} from './__tests__/restore-real-api';

// FE-F4: streamTextTurn + openTextConversation now share one consumeSseStream
// reader-loop. These tests cover the shared paths (chunks, 409 pre-flight,
// error body, empty body, abort) end-to-end through both callers.
const { streamTextTurn, openTextConversation } = realIntakeApi();
const { setV2TokenGetter, setV2UnauthorizedHandler } = realV2Client();

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;
let fetchMock: ReturnType<typeof mock>;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://localhost:8004';
  setV2TokenGetter(async () => null);
  setV2UnauthorizedHandler(null);
  fetchMock = mock(async () => new Response('{}', { status: 200 }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  setV2TokenGetter(async () => null);
  setV2UnauthorizedHandler(null);
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
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

// openTextConversation drives the SAME consumeSseStream as streamTextTurn, so
// these assertions also pin the shared loop for the opening greeting path.
describe('openTextConversation (shared consumeSseStream)', () => {
  test('yields text/done events split across chunk boundaries', async () => {
    fetchMock.mockResolvedValue({
      status: 200,
      ok: true,
      body: makeStream([
        'event: text\ndata: "Wel',
        'come"\n\n',
        'event: done\ndata: {"text":"Welcome","stop_reason":"end_turn","user_turn_idx":-1,"assistant_turn_idx":0}\n\n',
      ]),
    });

    const events: Array<{ type: string; chunk?: string; assistant_turn_idx?: number }> = [];
    for await (const ev of openTextConversation('sess-1')) events.push(ev);

    expect(events.filter((e) => e.type === 'text').map((e) => e.chunk)).toEqual(['Welcome']);
    expect(events.find((e) => e.type === 'done')?.assistant_turn_idx).toBe(0);
  });

  test('throws ModalityConflictError on 409 pre-flight', async () => {
    fetchMock.mockResolvedValue({
      status: 409,
      ok: false,
      json: async () => ({ detail: 'busy', held: 'voice', requested: 'text' }),
    });
    let err: unknown;
    try {
      for await (const _ of openTextConversation('sess-1')) {
        /* drain */
      }
    } catch (e) {
      err = e;
    }
    expectModalityConflictError(err, { held: 'voice', requested: 'text' });
  });

  test('throws IntakeApiError on non-409 failure', async () => {
    fetchMock.mockResolvedValue({
      status: 500,
      ok: false,
      json: async () => ({ detail: 'kaboom' }),
    });
    let err: unknown;
    try {
      for await (const _ of openTextConversation('sess-1')) {
        /* drain */
      }
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 500 });
  });

  test('throws IntakeApiError when the stream has no body', async () => {
    fetchMock.mockResolvedValue({ status: 200, ok: true, body: null });
    let err: unknown;
    try {
      for await (const _ of openTextConversation('sess-1')) {
        /* drain */
      }
    } catch (e) {
      err = e;
    }
    expectIntakeApiError(err, { status: 0 });
  });
});

describe('consumeSseStream — buffered tail frame (no trailing separator)', () => {
  test('parses a final frame that is not terminated by \\n\\n', async () => {
    fetchMock.mockResolvedValue({
      status: 200,
      ok: true,
      // No trailing "\n\n": the done frame must still be flushed from the buffer.
      body: makeStream([
        'event: done\ndata: {"text":"hi","stop_reason":null,"user_turn_idx":0,"assistant_turn_idx":1}',
      ]),
    });
    const events: Array<{ type: string }> = [];
    for await (const ev of streamTextTurn('sess-1', 'hi')) events.push(ev);
    expect(events.map((e) => e.type)).toEqual(['done']);
  });
});
