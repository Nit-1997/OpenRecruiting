import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { ReprocessAlreadyRunningError, VoiceDrainFailedError } from '@/types/intake';
import { realIntakeApi } from './__tests__/restore-real-api';

// Exercise the GENUINE module — other test files mock `@/lib/intake/api`
// process-wide, so a direct import here would resolve to their stubs.
// See restore-real-api.ts for the full explanation.
const api = realIntakeApi();
const { switchModality, reprocessSession, ModalityConflictError } = api;

const ORIGINAL_FETCH = globalThis.fetch;

function mockJsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('switchModality', () => {
  let fetchSpy: ReturnType<typeof mock>;
  beforeEach(() => { fetchSpy = mock(); globalThis.fetch = fetchSpy as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it('switch to text returns SwitchToTextResponse on 200', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(200, {
      active_modality: 'text', drained: { drained: true, duration_ms: 120 }, session: null,
    }));
    const res = await switchModality('abc', 'text');
    expect(res.active_modality).toBe('text');
    const call = fetchSpy.mock.calls[0];
    expect(String(call?.[0])).toContain('/api/v2/intake/sessions/abc/switch?to=text');
    expect((call?.[1] as RequestInit)?.method).toBe('POST');
  });

  it('switch to voice returns SwitchToVoiceResponse on 200', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(200, { active_modality: 'voice', next_step: 'voice_start' }));
    const res = await switchModality('abc', 'voice');
    expect(res.active_modality).toBe('voice');
  });

  it('409 → ModalityConflictError with held/requested', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(409, {
      detail: 'another mode is currently active', held: 'voice', requested: 'text',
    }));
    let err: unknown;
    try { await switchModality('abc', 'text'); } catch (e) { err = e; }
    expect(err).toBeInstanceOf(ModalityConflictError);
    expect((err as InstanceType<typeof ModalityConflictError>).held).toBe('voice');
    expect((err as InstanceType<typeof ModalityConflictError>).requested).toBe('text');
  });

  it('502 → VoiceDrainFailedError with inner error string', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(502, {
      detail: 'voice agent did not drain cleanly', error: 'timeout after 10.0s',
    }));
    let err: unknown;
    try { await switchModality('abc', 'text'); } catch (e) { err = e; }
    expect(err).toBeInstanceOf(VoiceDrainFailedError);
  });

  it('404 → generic Error', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(404, { detail: 'session not found' }));
    let err: unknown;
    try { await switchModality('abc', 'text'); } catch (e) { err = e; }
    expect((err as Error).message).toMatch(/session not found/i);
  });
});

describe('reprocessSession', () => {
  let fetchSpy: ReturnType<typeof mock>;
  beforeEach(() => { fetchSpy = mock(); globalThis.fetch = fetchSpy as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it('202 → ReprocessAcceptedResponse with process_run_id', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(202, {
      session_id: 'abc', process_run_id: '00000000-0000-0000-0000-000000000abc',
    }));
    const res = await reprocessSession('abc');
    expect(res.process_run_id).toBe('00000000-0000-0000-0000-000000000abc');
    const call = fetchSpy.mock.calls[0];
    expect(String(call?.[0])).toContain('/api/v2/intake/sessions/abc/reprocess');
  });

  it('409 → ReprocessAlreadyRunningError', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(409, { detail: 'Reprocess already running for this session.' }));
    let err: unknown;
    try { await reprocessSession('abc'); } catch (e) { err = e; }
    expect(err).toBeInstanceOf(ReprocessAlreadyRunningError);
  });

  it('500 → generic Error with body detail', async () => {
    fetchSpy.mockResolvedValueOnce(mockJsonResponse(500, { detail: 'Failed to invoke reprocess Lambda: boto3 down' }));
    let err: unknown;
    try { await reprocessSession('abc'); } catch (e) { err = e; }
    expect((err as Error).message).toMatch(/boto3 down/);
  });
});
