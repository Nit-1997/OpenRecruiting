import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { expectIntakeApiError, realIntakeApi } from './restore-real-api';

// Exercise the GENUINE module — other test files mock `@/lib/intake/api`
// process-wide. See restore-real-api.ts. `IntakeApiError` identity is asserted
// via `expectIntakeApiError` because bun's module mocking decouples the class.
const { patchAnswers, startVoiceSession } = realIntakeApi();

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

describe('patchAnswers (Phase 2)', () => {
  test('returns applied[] on 200', async () => {
    fetchMock = mock(async (_url, init) => {
      const body = JSON.parse(String((init as RequestInit)?.body));
      expect(body.patch.q4_must_haves.text).toBe('Python');
      return new Response(JSON.stringify({ applied: ['q4_must_haves'] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await patchAnswers('sess-1', { q4_must_haves: { text: 'Python', status: 'validated' } });
    expect(res.applied).toEqual(['q4_must_haves']);
  });

  test('throws IntakeApiError with detail on 404', async () => {
    fetchMock = mock(async () => new Response(JSON.stringify({ detail: 'session not found' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: unknown;
    try { await patchAnswers('sess-1', { q1_role_overview: { text: 'x' } }); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 404, detail: 'session not found' });
  });

  test('throws IntakeApiError on 422', async () => {
    fetchMock = mock(async () => new Response(JSON.stringify({ detail: 'invalid qid' }), {
      status: 422,
      headers: { 'content-type': 'application/json' },
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: unknown;
    try { await patchAnswers('sess-1', { q1_role_overview: { text: 'x' } }); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 422 });
  });
});

describe('startVoiceSession (Phase 2)', () => {
  test('returns answer SDP on 200', async () => {
    fetchMock = mock(async () => new Response(JSON.stringify({ sdp: 'answer-sdp', type: 'answer' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const r = await startVoiceSession('sess-1', { sdp: 'offer-sdp', type: 'offer' });
    expect(r.sdp).toBe('answer-sdp');
  });

  test('throws with code=modality_conflict on 409', async () => {
    fetchMock = mock(async () => new Response(JSON.stringify({ detail: 'another mode is currently active' }), {
      status: 409,
      headers: { 'content-type': 'application/json' },
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: unknown;
    try { await startVoiceSession('sess-1', { sdp: 'x', type: 'offer' }); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 409, code: 'modality_conflict' });
  });

  test('throws with status 502 on voice unreachable', async () => {
    fetchMock = mock(async () => new Response(JSON.stringify({ detail: 'voice agent unreachable' }), {
      status: 502,
      headers: { 'content-type': 'application/json' },
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let err: unknown;
    try { await startVoiceSession('sess-1', { sdp: 'x', type: 'offer' }); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 502 });
  });
});
