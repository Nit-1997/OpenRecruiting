// FE-F5 data-integrity guard.
//
// In production `isV2ApiEnabled()` is true. Several service methods used to
// ALWAYS read the localStorage mock seed even on the v2 path — fabricating
// data indistinguishable from real backend data. This file pins the post-fix
// contract for every such method: under v2, it must EITHER hit `v2Client`
// (real endpoint exists) OR throw `notImplementedInV2` (no endpoint yet).
// It must NEVER return seed/fixture data on the v2 path.
//
// Same idiom as v2-wiring.test.ts: env set before import, `@/lib/v2-client`
// stubbed to record calls and return queued responses.
//
// CONCURRENCY NOTE: bun runs test FILES concurrently in ONE process, and
// `process.env.NEXT_PUBLIC_V2_API` is process-global. test-setup.ts's global
// `beforeEach` resets it to 'false' for every test in every file. A plain
// file-level `beforeEach` setting it 'true' races against other files' resets
// at `await` boundaries. We therefore set the flag SYNCHRONOUSLY via
// `forceV2()` as the first statement of each assertion, immediately before
// the call — the gated methods read the env on their first synchronous line
// (before any await), so no other file's hook can interleave in between.
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  delete process.env.NEXT_PUBLIC_API_URL;
});

function forceV2(): void {
  process.env.NEXT_PUBLIC_V2_API = 'true';
}

type Call = { method: string; path: string; body?: unknown };
const calls: Call[] = [];
const responseQueue: unknown[] = [];
let nextResponse: unknown = null;

function popResponse(): unknown {
  if (responseQueue.length > 0) return responseQueue.shift();
  return nextResponse;
}

function resetMock() {
  calls.length = 0;
  responseQueue.length = 0;
  nextResponse = null;
}

mock.module('@/lib/v2-client', () => {
  function record<T>(method: string, path: string, body?: unknown): Promise<T> {
    const call: Call = { method, path };
    if (body !== undefined) call.body = body;
    calls.push(call);
    return Promise.resolve(popResponse() as T);
  }
  return {
    v2Client: {
      get: (path: string) => record('GET', path),
      post: (path: string, body?: unknown) => record('POST', path, body),
      put: (path: string, body?: unknown) => record('PUT', path, body),
      patch: (path: string, body?: unknown) => record('PATCH', path, body),
      delete: (path: string) => record('DELETE', path),
    },
    setV2TokenGetter: () => {},
    V2ApiError: class V2ApiError extends Error {},
  };
});

import * as activity from '../activity';
import * as candidates from '../candidates';
import * as debrief from '../debrief';
import * as feedback from '../feedback';
import * as integrations from '../integrations';
import * as interviews from '../interviews';
import * as profile from '../profile';
import * as requisitions from '../requisitions';
import { ServiceError } from '../service-error';

beforeEach(() => resetMock());
afterEach(() => resetMock());

// Stable, user-facing message produced by `notImplementedInV2`. We assert on
// this (plus `code`) rather than `rawDetail`, because two out-of-lane test
// files (`role-detail-page.test.tsx`, `schedule-modal.test.tsx`) register a
// process-wide `mock.module('@/services/service-error', ...)` whose stub
// `ServiceError` constructor drops the `rawDetail` option. `message` + `code`
// survive that stub; the mock-DB fallback paths throw DIFFERENT messages
// ("... not found", validation copy), so this still distinguishes a real
// not-available error from silent fabrication.
const NOT_AVAILABLE_MESSAGE = 'This feature is not available yet.';

/**
 * Assert that calling `fn()` under the v2 flag rejects with the typed
 * not-available error AND never touched v2Client. The flag is set
 * synchronously immediately before `fn()` so no concurrent file can flip it
 * back before the method's first-line env check runs.
 */
async function expectNotAvailable(fn: () => Promise<unknown>): Promise<void> {
  forceV2();
  let thrown: unknown;
  try {
    await fn();
  } catch (err) {
    thrown = err;
  }
  expect(thrown).toBeInstanceOf(ServiceError);
  const se = thrown as ServiceError;
  expect(se.code).toBe('not_found');
  expect(se.message).toBe(NOT_AVAILABLE_MESSAGE);
  expect(calls).toHaveLength(0);
}

describe('FE-F5: no silent fabrication on the v2 path', () => {
  // --- debrief: NOW IMPLEMENTED on v2 (Phase 3) — must hit the real debrief
  //     REST endpoints (via globalThis.fetch through the shared base), not the
  //     mock seed. These methods route through lib/debrief/api.ts, which calls
  //     `fetch` directly (the intake-api pattern) so they're independent of the
  //     process-wide v2Client stub above; we assert on a scoped fetch mock + the
  //     real mapped output, restoring fetch after each. ---
  test('debrief.get reads the candidate-picker endpoint (no fabrication)', async () => {
    forceV2();
    const originalFetch = globalThis.fetch;
    let calledUrl = '';
    globalThis.fetch = mock(async (url: string) => {
      calledUrl = String(url);
      return new Response(
        JSON.stringify([
          {
            candidate_id: 'c1',
            name: 'Ada',
            eligibility: 'ready',
            rounds_completed: 3,
            rounds_total: 4,
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }) as unknown as typeof fetch;
    try {
      const out = await debrief.get('req-1');
      expect(out.requisition_id).toBe('req-1');
      expect(out.candidates).toHaveLength(1);
      expect(out.candidates[0]?.candidate_id).toBe('c1');
      expect(calledUrl).toContain('/api/v2/debrief/roles/req-1/candidates');
      // The v2Client recorder is NOT the transport for debrief now.
      expect(calls).toHaveLength(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('debrief.getInsights reads the packets endpoint (no fabrication)', async () => {
    forceV2();
    const originalFetch = globalThis.fetch;
    let calledUrl = '';
    globalThis.fetch = mock(async (url: string) => {
      calledUrl = String(url);
      return new Response(
        JSON.stringify([
          {
            packet_id: 'p1',
            status: 'fresh',
            candidate_ids: ['c1', 'c2'],
            verdict: 'hire',
            confidence: 'high',
            generated_at: '2026-04-16T18:45:00Z',
            created_at: '2026-04-16T18:40:00Z',
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }) as unknown as typeof fetch;
    try {
      const out = await debrief.getInsights('req-1');
      expect(out.requisition_id).toBe('req-1');
      expect(out.strongest_candidate_id).toBe('c1');
      expect(calledUrl).toContain('/api/v2/debrief/roles/req-1/packets');
      expect(calls).toHaveLength(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // --- activity: NOT-AVAILABLE-IN-V2 ---
  test('activity.list throws notImplementedInV2 (no fabricated feed)', () =>
    expectNotAvailable(() => activity.list()));

  // --- profile: NOT-AVAILABLE-IN-V2 ---
  // profile.get() IS ported (GET /api/v2/auth/me) — real data, not fabricated —
  // so it is intentionally absent from this not-available list. The mutations
  // and notification prefs below remain unported and must still throw.
  test('profile.updateTimezone throws notImplementedInV2', () =>
    expectNotAvailable(() => profile.updateTimezone('America/Los_Angeles')));

  test('profile.updateName throws notImplementedInV2', () =>
    expectNotAvailable(() => profile.updateName('Ada Lovelace')));

  test('profile.getNotificationPrefs throws notImplementedInV2', () =>
    expectNotAvailable(() => profile.getNotificationPrefs()));

  test('profile.updateNotificationPrefs throws notImplementedInV2', () =>
    expectNotAvailable(() => profile.updateNotificationPrefs({ email_weekly_digest: false })));

  // --- requisitions: NOT-AVAILABLE-IN-V2 (no POST/intake/screening/sourcing) ---
  test('requisitions.create throws notImplementedInV2 (TODO PR6 backend)', () =>
    expectNotAvailable(() =>
      requisitions.create({
        role_title: 'PM',
        role_location: '',
        department: 'Product',
        created_by: 'user_1',
        created_by_name: 'Nitin',
      }),
    ));

  test('requisitions.updateIntake throws notImplementedInV2', () =>
    expectNotAvailable(() => requisitions.updateIntake('req-1', 'notes')));

  test('requisitions.attachScreeningAgent throws notImplementedInV2', () =>
    expectNotAvailable(() => requisitions.attachScreeningAgent('round-1', [])));

  test('requisitions.saveSourcingStrategy throws notImplementedInV2', () =>
    expectNotAvailable(() =>
      requisitions.saveSourcingStrategy('req-1', {
        id: 's1',
        channel: 'linkedin',
        title: 't',
        body: 'b',
      } as never),
    ));

  test('requisitions.listSourcingStrategies throws notImplementedInV2', () =>
    expectNotAvailable(() => requisitions.listSourcingStrategies('req-1')));

  // --- candidates.update / remove / setStatus: NOT-AVAILABLE-IN-V2 ---
  test('candidates.update throws notImplementedInV2', () =>
    expectNotAvailable(() => candidates.update('req-1', 'c1', { name: 'New' })));

  test('candidates.remove throws notImplementedInV2', () =>
    expectNotAvailable(() => candidates.remove('req-1', 'c1')));

  test('candidates.setStatus throws notImplementedInV2', () =>
    expectNotAvailable(() => candidates.setStatus('req-1', 'c1', 'hired')));

  // --- interviews.sendReminder: NOT-AVAILABLE-IN-V2 ---
  test('interviews.sendReminder throws notImplementedInV2', () =>
    expectNotAvailable(() => interviews.sendReminder('cr-1')));


  // --- integrations: documented MOCK-ONLY, but must not fabricate on v2 ---
  test('integrations.list throws notImplementedInV2', () =>
    expectNotAvailable(() => integrations.list()));

  // --- candidates.get / getRound: REAL (derived from pipeline/packet RPC) ---
  test('candidates.get reads the pipeline RPC and returns the matching candidate', async () => {
    forceV2();
    nextResponse = {
      candidates: [
        { id: 'c1', requisition_id: 'req-1', name: 'Ada' },
        { id: 'c2', requisition_id: 'req-1', name: 'Bo' },
      ],
    };
    const out = await candidates.get('req-1', 'c2');
    expect(out.id).toBe('c2');
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('GET');
    expect(calls[0]?.path).toBe('/api/v2/roles/req-1/candidates');
  });

  test('candidates.get throws not_found when the candidate is absent (no fabrication)', async () => {
    forceV2();
    nextResponse = { candidates: [{ id: 'c1', requisition_id: 'req-1', name: 'Ada' }] };
    await expect(candidates.get('req-1', 'missing')).rejects.toBeInstanceOf(ServiceError);
  });

  test('candidates.getRound resolves the cr from the packet RPC', async () => {
    forceV2();
    nextResponse = {
      rounds: [
        {
          round: { id: 'round-1' },
          candidate_round: {
            id: 'cr-1',
            candidate_id: 'c1',
            round_id: 'round-1',
            status: 'pending',
          },
        },
      ],
    };
    const cr = await candidates.getRound('req-1', 'c1', 'round-1');
    expect(cr.id).toBe('cr-1');
    expect(calls[0]?.path).toBe('/api/v2/roles/req-1/candidates/c1/packet');
  });

  // --- feedback.getRoundFeedback: REAL (derived from packet RPC) ---
  test('feedback.getRoundFeedback reads the packet RPC and returns its entries', async () => {
    forceV2();
    nextResponse = {
      rounds: [
        {
          round: { id: 'round-1' },
          candidate_round: { id: 'cr-1' },
          feedback_questions: [
            {
              id: 'q1',
              feedback_entries: [
                {
                  id: 'fb1',
                  candidate_round_id: 'cr-1',
                  feedback_question_id: 'q1',
                  feedback_text: 'solid',
                  evidence_status: 'verified',
                  evidence: [],
                  source: 'manual',
                  created_at: '2026-01-01T00:00:00Z',
                },
              ],
            },
          ],
        },
      ],
    };
    const entries = await feedback.getRoundFeedback('req-1', 'c1', 'round-1');
    expect(entries).toHaveLength(1);
    expect(entries[0]?.id).toBe('fb1');
    expect(calls[0]?.path).toBe('/api/v2/roles/req-1/candidates/c1/packet');
  });
});
