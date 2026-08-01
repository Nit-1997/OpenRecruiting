// Phase 2 Task 2.5 — the confirm-then-execute action layer.
//
// Drives the REAL flow + REAL zustand stores (setState/reset in beforeEach)
// against a scoped `globalThis.fetch` mock (restored by test-setup's backstop).
// v2 is pinned ON per test so executeDebriefAction builds against a deterministic
// backend base.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { DebriefApiError } from '@/lib/debrief/api';
import { executeDebriefAction } from '@/lib/debrief/chat';
import { makeMessage } from '@/lib/sub-agent-runner';
import { useArtifactStore, useSessionStore } from '@/stores';
import type { ProposedAction } from '@/types/sub-agent';
import { confirmDebriefAction, dismissDebriefAction } from '../flow';
import { DEBRIEF_ARTIFACT_ID } from '../mock-stream';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

function forceV2(): void {
  process.env.NEXT_PUBLIC_V2_API = 'true';
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
}

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

const ADD_ROUND: ProposedAction = {
  kind: 'propose_add_round',
  input: {
    candidate_ids: ['c1'],
    summary: 'Add a System design round',
    rationale: 'Architecture depth was never probed.',
    name: 'System design',
  },
};

const REQUEST_FEEDBACK: ProposedAction = {
  kind: 'propose_request_feedback',
  input: {
    candidate_ids: ['c1'],
    summary: 'Request feedback from David',
    rationale: 'His scorecard is outstanding.',
    interviewer_email: 'david@acme.test',
  },
};

const LOG_INSIGHT: ProposedAction = {
  kind: 'propose_log_insight',
  input: {
    candidate_ids: [],
    summary: 'Remember we value async communication for staff roles',
    rationale: 'You called this out twice across the debrief.',
    insight_kind: 'recruiter_preference',
    text: 'We value async communication for staff engineering roles.',
    triplet: { subject: 'org', predicate: 'values', object: 'async communication' },
  },
};

const REFETCHED_PACKET = { id: 'BODY-NEW', status: 'fresh', candidates: [] };

/** Seed a result-stage debrief session with a threaded packetId and append a
 *  pending confirm-card message; returns its id. */
function seedPendingCard(action: ProposedAction, packetId: string | null): string {
  const sessions = useSessionStore.getState();
  sessions.startSession('debrief', 'result');
  if (packetId) sessions.updateSelections('debrief', { packetId });
  const card = makeMessage('agent', '', 'text', 'chat');
  card.confirmAction = action;
  card.confirmStatus = 'pending';
  sessions.appendMessage('debrief', card);
  return card.id;
}

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
});

describe('executeDebriefAction', () => {
  test('POSTs the right URL + body and returns the parsed body on 200', async () => {
    forceV2();
    let calledUrl = '';
    let calledBody: unknown;
    const fetchMock = mock(async (url: string, init: RequestInit) => {
      calledUrl = String(url);
      calledBody = JSON.parse(String(init.body));
      return jsonResponse({ ok: true, result: { round_id: 'r9' } });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out = await executeDebriefAction('pkt-7', ADD_ROUND);

    expect(calledUrl).toBe('http://backend.test/api/v2/debrief/packets/pkt-7/actions');
    expect(calledBody).toEqual({ kind: 'propose_add_round', input: ADD_ROUND.input });
    expect(out.ok).toBe(true);
    expect(out.result).toEqual({ round_id: 'r9' });
  });

  test('throws a typed DebriefApiError carrying the status on 400/404/409', async () => {
    forceV2();
    for (const status of [400, 404, 409]) {
      globalThis.fetch = mock(async () =>
        jsonResponse({ detail: 'leak me not' }, { status }),
      ) as unknown as typeof fetch;

      let caught: unknown;
      try {
        await executeDebriefAction('pkt-7', ADD_ROUND);
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(DebriefApiError);
      expect((caught as DebriefApiError).status).toBe(status);
      // Raw server text never leaks into the error message.
      expect((caught as DebriefApiError).message).not.toContain('leak me not');
    }
  });
});

describe('confirmDebriefAction', () => {
  test('packet-changing kind: executes, marks done, appends result, refetches + patches artifact', async () => {
    forceV2();
    let actionsBody: unknown;
    let getCalled = false;
    const fetchMock = mock(async (url: string, init: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/actions')) {
        actionsBody = JSON.parse(String(init.body));
        return jsonResponse({ ok: true });
      }
      // The packet refetch (GET /packets/{id}).
      getCalled = true;
      return jsonResponse(REFETCHED_PACKET);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    // Seed an open comparative artifact so the patch has a target.
    useArtifactStore.getState().openArtifact({
      id: DEBRIEF_ARTIFACT_ID,
      type: 'comparative',
      title: 'Debrief',
      initialData: { packet: { id: 'BODY-OLD' } },
    });

    const cardId = seedPendingCard(ADD_ROUND, 'pkt-7');
    await confirmDebriefAction(cardId);

    // Same { kind, input } it received went to the execute endpoint.
    expect(actionsBody).toEqual({ kind: 'propose_add_round', input: ADD_ROUND.input });

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const card = msgs.find((m) => m.id === cardId);
    expect(card?.confirmStatus).toBe('done');
    expect(msgs.some((m) => m.role === 'agent' && m.text.toLowerCase().includes('done'))).toBe(
      true,
    );

    // Packet-changing → getPacket called + artifact patched with the new packet.
    expect(getCalled).toBe(true);
    const art = useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID];
    expect((art?.data as { packet?: { id: string } }).packet?.id).toBe('BODY-NEW');
  });

  test('request_feedback (non-packet-changing): executes, marks done, NO refetch', async () => {
    forceV2();
    let getCalled = false;
    const fetchMock = mock(async (url: string) => {
      if (String(url).endsWith('/actions')) return jsonResponse({ ok: true });
      getCalled = true;
      return jsonResponse(REFETCHED_PACKET);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cardId = seedPendingCard(REQUEST_FEEDBACK, 'pkt-7');
    await confirmDebriefAction(cardId);

    const card = useSessionStore.getState().sessions.debrief?.messages.find((m) => m.id === cardId);
    expect(card?.confirmStatus).toBe('done');
    expect(getCalled).toBe(false);
  });

  test('log_insight (non-packet-changing): executes ONCE with the same payload, NO refetch', async () => {
    forceV2();
    let actionsBody: unknown;
    let actionsCalls = 0;
    let getCalled = false;
    const fetchMock = mock(async (url: string, init: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/actions')) {
        actionsCalls += 1;
        actionsBody = JSON.parse(String(init.body));
        return jsonResponse({ ok: true });
      }
      // A packet GET would mean a wrongful refetch — fail the no-refetch assert.
      getCalled = true;
      return jsonResponse(REFETCHED_PACKET);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cardId = seedPendingCard(LOG_INSIGHT, 'pkt-7');
    await confirmDebriefAction(cardId);

    // Executed exactly once with the SAME { kind, input } the card carried.
    expect(actionsCalls).toBe(1);
    expect(actionsBody).toEqual({ kind: 'propose_log_insight', input: LOG_INSIGHT.input });

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const card = msgs.find((m) => m.id === cardId);
    expect(card?.confirmStatus).toBe('done');
    expect(msgs.some((m) => m.role === 'agent' && m.text.toLowerCase().includes('done'))).toBe(
      true,
    );
    // A brain signal is NOT a packet mutation → the packet is never refetched.
    expect(getCalled).toBe(false);
  });

  test('dismissing a log_insight card appends "Dismissed." and never calls fetch', async () => {
    forceV2();
    const fetchMock = mock(async () => jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cardId = seedPendingCard(LOG_INSIGHT, 'pkt-7');
    dismissDebriefAction(cardId);

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.find((m) => m.id === cardId)?.confirmStatus).toBe('dismissed');
    expect(msgs.some((m) => m.role === 'agent' && m.text === 'Dismissed.')).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('a 409 from execute marks the card failed and appends a friendly error', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      jsonResponse({ detail: 'conflict' }, { status: 409 }),
    ) as unknown as typeof fetch;

    const cardId = seedPendingCard(ADD_ROUND, 'pkt-7');
    await confirmDebriefAction(cardId);

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const card = msgs.find((m) => m.id === cardId);
    expect(card?.confirmStatus).toBe('failed');
    const err = msgs.find((m) => m.role === 'agent' && m.text.toLowerCase().includes('refresh'));
    expect(err).toBeDefined();
    expect(err?.text).not.toContain('conflict');
  });

  test('a settled card is never re-executed (idempotent at the card level)', async () => {
    forceV2();
    const fetchMock = mock(async () => jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cardId = seedPendingCard(ADD_ROUND, 'pkt-7');
    useSessionStore.getState().updateMessage('debrief', cardId, { confirmStatus: 'done' });
    await confirmDebriefAction(cardId);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('dismissDebriefAction', () => {
  test('marks the card dismissed, appends "Dismissed.", and never calls fetch', async () => {
    forceV2();
    const fetchMock = mock(async () => jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const cardId = seedPendingCard(ADD_ROUND, 'pkt-7');
    dismissDebriefAction(cardId);

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.find((m) => m.id === cardId)?.confirmStatus).toBe('dismissed');
    expect(msgs.some((m) => m.role === 'agent' && m.text === 'Dismissed.')).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
