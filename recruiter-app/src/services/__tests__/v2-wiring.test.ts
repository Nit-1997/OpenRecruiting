// IMPORTANT: env vars must be set BEFORE any import that reads them. The
// env module reads process.env at every isV2ApiEnabled() call (function,
// not module-load constant), so beforeEach IS the right scope for this.
// We previously mutated at module top-level which raced against other
// test files under bun's concurrent file execution — see the test-setup
// note about NEXT_PUBLIC_V2_API.
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

beforeEach(() => {
  // Override test-setup.ts's `false` default — this entire file exercises
  // the v2-API code paths and must see `true` for every test it runs.
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterAll(() => {
  // Best-effort restore for any test that runs after this file's last
  // afterEach (test-setup's beforeEach also covers this).
  process.env.NEXT_PUBLIC_V2_API = 'false';
  delete process.env.NEXT_PUBLIC_API_URL;
});

// Capture every v2 call so each test can inspect path + body.
type Call = { method: string; path: string; body?: unknown; ifMatch?: string };
const calls: Call[] = [];
let nextResponse: unknown = null;
const responseQueue: unknown[] = [];

function popResponse(): unknown {
  if (responseQueue.length > 0) return responseQueue.shift();
  return nextResponse;
}

function resetMock() {
  calls.length = 0;
  nextResponse = null;
  responseQueue.length = 0;
}

mock.module('@/lib/v2-client', () => {
  // Spread the REAL module: mock.module is process-wide last-writer-wins, so a
  // partial replacement would strip resolveV2Token/runV2UnauthorizedHandler for
  // any concurrently-scheduled test file and break cross-file `instanceof
  // V2ApiError`. Only v2Client is stubbed; everything else stays real.
  const actual = require('@/lib/v2-client');
  function record<T>(
    method: string,
    path: string,
    body?: unknown,
    opts?: { ifMatch?: string },
  ): Promise<T> {
    const call: Call = { method, path };
    if (body !== undefined) call.body = body;
    if (opts?.ifMatch !== undefined) call.ifMatch = opts.ifMatch;
    calls.push(call);
    return Promise.resolve(popResponse() as T);
  }
  return {
    ...actual,
    v2Client: {
      get: (path: string, opts?: { ifMatch?: string }) =>
        record('GET', path, undefined, opts),
      post: (path: string, body?: unknown, opts?: { ifMatch?: string }) =>
        record('POST', path, body, opts),
      put: (path: string, body?: unknown, opts?: { ifMatch?: string }) =>
        record('PUT', path, body, opts),
      delete: (path: string, opts?: { ifMatch?: string }) =>
        record('DELETE', path, undefined, opts),
    },
    setV2TokenGetter: () => {},
  };
});

import * as candidates from '../candidates';
import * as feedback from '../feedback';
import * as interviews from '../interviews';
import { addRound, deleteRound, reorderRounds } from '../requisitions';

beforeEach(() => {
  resetMock();
});
afterEach(() => {
  resetMock();
});

describe('v2-API wiring', () => {
  test('isV2ApiEnabled flag is true under NEXT_PUBLIC_V2_API=true', async () => {
    const env = await import('@/lib/env');
    expect(env.isV2ApiEnabled()).toBe(true);
  });

  test('requisitions.addRound POSTs to /api/v2/roles/{id}/plan/rounds', async () => {
    nextResponse = {
      id: 'r1',
      requisition_id: 'req-1',
      round_number: 1,
      name: 'Coding',
      category: 'technical',
      duration_minutes: 60,
      skills: [],
      guidelines: [],
      feedback_questions: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    const out = await addRound('req-1', {
      name: 'Coding',
      category: 'technical',
      duration_minutes: 60,
    });
    expect(out.id).toBe('r1');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('POST');
    expect(call.path).toBe('/api/v2/roles/req-1/plan/rounds');
    expect(call.body).toEqual({
      name: 'Coding',
      category: 'technical',
      duration_minutes: 60,
    });
  });

  test('requisitions.deleteRound DELETEs to /api/v2/plan/rounds/{rid}', async () => {
    nextResponse = { deleted_round_id: 'r1' };
    await deleteRound('r1');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('DELETE');
    expect(call.path).toBe('/api/v2/plan/rounds/r1');
  });

  test('requisitions.reorderRounds sends If-Match and posts ordered items', async () => {
    nextResponse = { rounds: [], etag: '2026-01-02T00:00:00Z' };
    await reorderRounds('req-1', ['r2', 'r1'], '2026-01-01T00:00:00Z');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('POST');
    expect(call.path).toBe('/api/v2/roles/req-1/plan/rounds/reorder');
    expect(call.ifMatch).toBe('2026-01-01T00:00:00Z');
    expect(call.body).toEqual([
      { round_id: 'r2', round_number: 1 },
      { round_id: 'r1', round_number: 2 },
    ]);
  });

  test('candidates.create POSTs and unwraps {candidate, counts}', async () => {
    const candidate = {
      id: 'c1',
      requisition_id: 'req-1',
      name: 'Ada',
      email: 'ada@ex.com',
      phone: null,
      resume_url: null,
      avatar_initials: 'AD',
      avatar_color: '#fff',
      status: 'active' as const,
      final_verdict: null,
      current_round_id: null,
      tags: [],
      source: 'manual',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    nextResponse = { candidate, counts: { active: 1 } };
    const out = await candidates.create('req-1', { name: 'Ada', email: 'ada@ex.com' });
    expect(out.id).toBe('c1');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('POST');
    expect(call.path).toBe('/api/v2/roles/req-1/candidates');
  });

  test('candidates.listForReq unwraps {candidates: [...]}', async () => {
    nextResponse = {
      candidates: [
        {
          id: 'c1',
          requisition_id: 'req-1',
          name: 'Ada',
          email: 'ada@ex.com',
          phone: null,
          resume_url: null,
          avatar_initials: 'AD',
          avatar_color: '#fff',
          status: 'active',
          final_verdict: null,
          current_round_id: null,
          tags: [],
          source: 'manual',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    };
    const rows = await candidates.listForReq('req-1');
    expect(rows).toHaveLength(1);
    expect(rows[0]?.id).toBe('c1');
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('GET');
    expect(call.path).toBe('/api/v2/roles/req-1/candidates');
  });

  test('interviews.schedule resolves cr_id from packet, then POSTs to /schedule', async () => {
    // Queue: 1st GET (packet) → 2nd POST (schedule).
    responseQueue.push(
      {
        rounds: [
          {
            round: { id: 'round-1' },
            candidate_round: { id: 'cr-1', status: 'pending' },
          },
        ],
      },
      {
        candidate_round: {
          id: 'cr-1',
          candidate_id: 'c1',
          round_id: 'round-1',
          status: 'scheduled',
          scorecard_status: 'pending',
          rating: null,
          summary: '',
          question_summaries: {},
          feedback_approved_at: null,
          feedback_approved_by_email: null,
          scheduled_at: '2026-05-01T17:00:00Z',
          completed_at: null,
          interviewer_email: 'j@ex.com',
          interviewer_name: 'Jordan',
          meeting_url: null,
          scorecard: [],
        },
      },
    );
    const cr = await interviews.schedule('req-1', 'c1', 'round-1', {
      scheduled_at: '2026-05-01T17:00:00Z',
      interviewer_email: 'j@ex.com',
      interviewer_name: 'Jordan',
    });
    expect(cr.status).toBe('scheduled');
    expect(calls).toHaveLength(2);
    const c0 = calls[0];
    const c1 = calls[1];
    if (!c0 || !c1) throw new Error('expected two calls');
    expect(c0.path).toBe('/api/v2/roles/req-1/candidates/c1/packet');
    expect(c1.path).toBe('/api/v2/candidate-rounds/cr-1/schedule');
  });

  test('feedback.submitFeedback resolves cr_id, forwards only backend fields', async () => {
    responseQueue.push(
      {
        rounds: [
          {
            round: { id: 'round-1' },
            candidate_round: { id: 'cr-1', status: 'scheduled' },
          },
        ],
      },
      {
        candidate_round: { id: 'cr-1', status: 'completed' },
        entries: [
          {
            id: 'fb-1',
            candidate_round_id: 'cr-1',
            feedback_question_id: 'q-1',
            feedback_text: 'solid',
            evidence_status: 'verified',
            evidence: [],
            source: 'manual',
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
    );
    const entries = await feedback.submitFeedback('req-1', 'c1', 'round-1', {
      entries: [
        {
          feedback_question_id: 'q-1',
          rating: 'yes',
          evidence_status: 'verified',
          feedback_text: 'solid',
        },
      ],
      scorecard: [],
      overall_rating: 'yes',
      summary: 'good',
    });
    expect(entries).toHaveLength(1);
    expect(calls).toHaveLength(2);
    const submit = calls[1];
    if (!submit) throw new Error('expected submit call');
    expect(submit.method).toBe('POST');
    expect(submit.path).toBe('/api/v2/candidate-rounds/cr-1/feedback');
    // Per-entry `rating` and `scorecard` are UI-only — backend body must omit
    // them.
    const body = submit.body as {
      entries: Array<Record<string, unknown>>;
      rating: string;
      summary: string;
    };
    expect(body.entries[0]).toEqual({
      feedback_question_id: 'q-1',
      feedback_text: 'solid',
      evidence_status: 'verified',
    });
    expect(body.rating).toBe('yes');
    expect(body.summary).toBe('good');
  });
});
