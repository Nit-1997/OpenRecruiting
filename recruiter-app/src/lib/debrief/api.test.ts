// Phase 3 Task 3.1 — typed debrief REST layer.
//
// Drives the REAL v2 client (snapshot from src/test-setup.ts) against a scoped
// `globalThis.fetch` mock (restored in afterEach + the test-setup backstop).
// We assert the URLs/methods the backend contract defines, the backend→FE
// mappers, and the generate+poll loop (with an injected no-op sleep).

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import {
  candidateItemToFixture,
  DebriefApiError,
  DebriefGenerationError,
  generateDebrief,
  getPacket,
  listCandidates,
  listPackets,
  listRoles,
  pollPacket,
  roleItemToFixture,
  saveDebrief,
} from './api';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

type FetchMock = { mock: { calls: unknown[] } };
function urlAt(fetchMock: FetchMock, index: number): { url: string; method: string } {
  const args = fetchMock.mock.calls[index] as unknown as [string, RequestInit];
  return { url: String(args[0]), method: String(args[1]?.method ?? 'GET') };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
});

describe('debrief api — fetchers hit the right endpoints', () => {
  test('listRoles GETs /api/v2/debrief/roles', async () => {
    const fetchMock = mock(async () =>
      jsonResponse([{ requisition_id: 'r1', role_title: 'PM', eligible_candidate_count: 3 }]),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await listRoles();
    expect(out).toHaveLength(1);
    expect(out[0]?.requisition_id).toBe('r1');
    const { url, method } = urlAt(fetchMock as unknown as FetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/debrief/roles');
    expect(method).toBe('GET');
  });

  test('listCandidates GETs the per-role candidates endpoint', async () => {
    const fetchMock = mock(async () =>
      jsonResponse([
        {
          candidate_id: 'c1',
          name: 'Ada',
          eligibility: 'ready',
          rounds_completed: 4,
          rounds_total: 4,
          rated_round_count: 4,
        },
      ]),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await listCandidates('r1');
    expect(out[0]?.candidate_id).toBe('c1');
    const { url } = urlAt(fetchMock as unknown as FetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/debrief/roles/r1/candidates');
  });

  test('generateDebrief POSTs requisition_id + candidate_ids', async () => {
    let sentBody = '';
    const fetchMock = mock(async (_url: string, init: RequestInit) => {
      sentBody = String(init.body);
      return jsonResponse({ packet_id: 'p1', status: 'generating' });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await generateDebrief('r1', ['c1', 'c2']);
    expect(out.packet_id).toBe('p1');
    expect(out.status).toBe('generating');
    const { url, method } = urlAt(fetchMock as unknown as FetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/debrief/generate');
    expect(method).toBe('POST');
    expect(JSON.parse(sentBody)).toEqual({ requisition_id: 'r1', candidate_ids: ['c1', 'c2'] });
  });

  test('saveDebrief POSTs the per-packet save endpoint and returns the fresh status', async () => {
    const fetchMock = mock(async () => jsonResponse({ packet_id: 'p1', status: 'fresh' }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await saveDebrief('p1');
    expect(out.packet_id).toBe('p1');
    expect(out.status).toBe('fresh');
    const { url, method } = urlAt(fetchMock as unknown as FetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/debrief/packets/p1/save');
    expect(method).toBe('POST');
  });

  test('saveDebrief surfaces a non-2xx response as a DebriefApiError', async () => {
    const fetchMock = mock(async () => jsonResponse({ detail: 'conflict' }, { status: 409 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const err = await saveDebrief('p1').catch((e) => e);
    expect(err).toBeInstanceOf(DebriefApiError);
    expect((err as DebriefApiError).status).toBe(409);
  });

  test('listPackets GETs the per-role packets endpoint', async () => {
    const fetchMock = mock(async () =>
      jsonResponse([
        {
          packet_id: 'p1',
          status: 'fresh',
          candidate_ids: ['c1'],
          verdict: 'hire',
          confidence: 'high',
          generated_at: '2026-04-16T18:45:00Z',
          created_at: '2026-04-16T18:40:00Z',
        },
      ]),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const out = await listPackets('r1');
    expect(out[0]?.packet_id).toBe('p1');
    const { url } = urlAt(fetchMock as unknown as FetchMock, 0);
    expect(url).toBe('http://backend.test/api/v2/debrief/roles/r1/packets');
  });
});

describe('debrief api — backend→FE mappers', () => {
  test('roleItemToFixture maps a RolePickItem to a RoleFixture', () => {
    const fx = roleItemToFixture({
      requisition_id: 'r1',
      role_title: 'PM',
      eligible_candidate_count: 2,
    });
    expect(fx.id).toBe('r1');
    expect(fx.title).toBe('PM');
    expect(fx.pipeline).toBe('2 candidates ready to debrief');
    expect(fx.ready_to_debrief).toBe(true);
  });

  test('candidateItemToFixture maps eligibility → status + derives initials', () => {
    const fx = candidateItemToFixture(
      {
        candidate_id: 'c1',
        name: 'Ada Lovelace',
        eligibility: 'awaiting_signal',
        rounds_completed: 1,
        rounds_total: 4,
        rated_round_count: 1,
      },
      0,
    );
    expect(fx.id).toBe('c1');
    expect(fx.avatar).toBe('AL');
    expect(fx.status).toBe('waiting');
    expect(fx.flag).toBe('1/4 rounds');
    // The canonical backend tier + parity count are carried through for the gate.
    expect(fx.eligibility).toBe('awaiting_signal');
    expect(fx.ratedRounds).toBe(1);
  });

  test('candidateItemToFixture preserves the feedback signal counts', () => {
    const fx = candidateItemToFixture(
      {
        candidate_id: 'c2',
        name: 'Grace Hopper',
        eligibility: 'ready',
        rounds_completed: 4,
        rounds_total: 4,
        rated_round_count: 4,
        signal: { feedback_count: 3, evidence_backed_count: 2 },
      },
      1,
    );
    expect(fx.eligibility).toBe('ready');
    expect(fx.status).toBe('ready');
    expect(fx.signal).toEqual({ feedback_count: 3, evidence_backed_count: 2 });
  });

  test('candidateItemToFixture defaults the signal to zeros when omitted', () => {
    const fx = candidateItemToFixture(
      {
        candidate_id: 'c3',
        name: 'Early Bird',
        eligibility: 'early_stage',
        rounds_completed: 0,
        rounds_total: 4,
        rated_round_count: 0,
      },
      2,
    );
    expect(fx.eligibility).toBe('early_stage');
    expect(fx.signal).toEqual({ feedback_count: 0, evidence_backed_count: 0 });
  });
});

describe('debrief api — generate + poll', () => {
  const noSleep = async () => {};

  test('pollPacket returns the packet once it is ready', async () => {
    let attempts = 0;
    const fetchMock = mock(async () => {
      attempts++;
      if (attempts < 3) return jsonResponse({ detail: 'not ready' }, { status: 404 });
      return jsonResponse({ id: 'p1', status: 'fresh', candidates: [] });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const packet = await pollPacket('p1', { sleep: noSleep, maxAttempts: 10 });
    expect(packet.id).toBe('p1');
    expect(attempts).toBe(3);
  });

  test('pollPacket throws DebriefGenerationError on timeout (always 404)', async () => {
    const fetchMock = mock(async () =>
      jsonResponse({ detail: 'still generating' }, { status: 404 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await expect(pollPacket('p1', { sleep: noSleep, maxAttempts: 3 })).rejects.toBeInstanceOf(
      DebriefGenerationError,
    );
  });

  test('pollPacket throws on a terminal (non-404) error', async () => {
    const fetchMock = mock(async () => jsonResponse({ detail: 'boom' }, { status: 500 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await expect(pollPacket('p1', { sleep: noSleep, maxAttempts: 5 })).rejects.toBeInstanceOf(
      DebriefGenerationError,
    );
  });

  test('pollPacket throws when the body reports status=failed', async () => {
    const fetchMock = mock(async () => jsonResponse({ id: 'p1', status: 'failed' }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await expect(pollPacket('p1', { sleep: noSleep, maxAttempts: 5 })).rejects.toBeInstanceOf(
      DebriefGenerationError,
    );
  });
});

describe('debrief api — bounded generate/poll timeout (FIX 3)', () => {
  const noSleep = async () => {};

  // A fetch that hangs until its abort signal fires, then rejects with the
  // DOMException('AbortError') a real fetch raises on abort. With a tiny
  // timeout the AbortController fires almost immediately.
  function hangingFetchHonoringAbort() {
    return mock(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init.signal;
          if (!signal) return; // never resolves; the timeout path is what we test
          if (signal.aborted) {
            reject(new DOMException('Aborted', 'AbortError'));
            return;
          }
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        }),
    );
  }

  test('generateDebrief aborts after the timeout → terminal DebriefApiError', async () => {
    globalThis.fetch = hangingFetchHonoringAbort() as unknown as typeof fetch;
    // 5ms ceiling so the AbortController fires well before any test timeout.
    const err = await generateDebrief('r1', ['c1', 'c2'], 5).catch((e) => e);
    expect(err).toBeInstanceOf(DebriefApiError);
    expect((err as DebriefApiError).status).toBe(0);
    expect((err as DebriefApiError).message).toMatch(/timed out/i);
  });

  test('getPacket aborts after the timeout, and pollPacket surfaces it as a terminal failure', async () => {
    globalThis.fetch = hangingFetchHonoringAbort() as unknown as typeof fetch;
    // A timed-out getPacket throws DebriefApiError(0) — NOT a 404 — so the poll
    // loop treats it as terminal and routes to the failed path (per FIX 3).
    await expect(getPacket('p1', 5)).rejects.toBeInstanceOf(DebriefApiError);
    await expect(
      pollPacket('p1', { sleep: noSleep, maxAttempts: 3, getPacketTimeoutMs: 5 }),
    ).rejects.toBeInstanceOf(DebriefGenerationError);
  });
});
