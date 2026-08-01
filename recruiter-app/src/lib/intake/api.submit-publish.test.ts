import { describe, it, expect, beforeEach, mock } from 'bun:test';
import { expectIntakeApiError, realIntakeApi } from './__tests__/restore-real-api';

// Exercise the GENUINE module — other test files mock `@/lib/intake/api`
// process-wide. See restore-real-api.ts. `IntakeApiError` identity is asserted
// via `expectIntakeApiError` because bun's module mocking decouples the class.
const { submitSession, publishSession } = realIntakeApi();

const ORIGINAL_FETCH = globalThis.fetch;

function mockFetchOnce(body: unknown, init: { status?: number } = {}) {
  globalThis.fetch = mock(async () =>
    new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { 'content-type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
}

describe('submitSession', () => {
  beforeEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it('POSTs to /intake/sessions/<id>/submit and returns SubmitResponse', async () => {
    mockFetchOnce({ session_id: 'sess-1', status: 'submitted' }, { status: 202 });
    const out = await submitSession('sess-1');
    expect(out).toEqual({ session_id: 'sess-1', status: 'submitted' });
  });

  it('throws IntakeApiError on 409 (already submitted)', async () => {
    mockFetchOnce({ detail: 'Session already submitted' }, { status: 409 });
    let err: unknown;
    try { await submitSession('sess-1'); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 409 });
  });

  it('throws IntakeApiError on 500 and surfaces detail', async () => {
    mockFetchOnce({ detail: 'Lambda invoke failed' }, { status: 500 });
    let err: unknown;
    try { await submitSession('sess-1'); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 500, detail: 'Lambda invoke failed' });
  });
});

describe('publishSession', () => {
  beforeEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it('POSTs with interview_plan=null when called without an edited plan', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    globalThis.fetch = mock(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({
        session_id: 'sess-1',
        requisition_id: 'req-1',
        redirect_url: '/view/roles/req-1',
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as unknown as typeof fetch;

    const out = await publishSession('sess-1');
    expect(out.requisition_id).toBe('req-1');
    expect(out.redirect_url).toBe('/view/roles/req-1');
    expect(JSON.parse(String(calls[0]!.init.body))).toEqual({ interview_plan: null });
  });

  it('POSTs the edited plan when provided', async () => {
    const edited = { rounds: [{ id: 'r1', name: 'Coding' }] };
    const captured: { body?: string } = {};
    globalThis.fetch = mock(async (_url: string, init: RequestInit) => {
      captured.body = String(init.body);
      return new Response(JSON.stringify({
        session_id: 'sess-1',
        requisition_id: 'req-1',
        redirect_url: '/view/roles/req-1',
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as unknown as typeof fetch;

    await publishSession('sess-1', edited as never);
    expect(JSON.parse(captured.body!)).toEqual({ interview_plan: edited });
  });

  it('throws IntakeApiError on 422 (validation)', async () => {
    mockFetchOnce({ detail: 'Round 1 missing name' }, { status: 422 });
    let err: unknown;
    try { await publishSession('sess-1'); } catch (e) { err = e; }
    expectIntakeApiError(err, { status: 422 });
  });
});
