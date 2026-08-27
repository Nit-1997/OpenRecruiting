// Phase 3 Task 3.3 — the v2 generate+poll flow.
//
// Drives the REAL flow (real zustand stores + setState reset in beforeEach)
// against a scoped `globalThis.fetch` mock (restored by test-setup's backstop).
// We pin a deterministic backend base + flip v2 ON synchronously per test so no
// concurrent file's env reset interleaves before the flow's first call.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { useArtifactStore, useSessionStore } from '@/stores';
import { completeAnalyzing, confirmCandidatePick, pickDebriefRole, retryFromFailure } from './flow';
import { DEBRIEF_ARTIFACT_ID } from './mock-stream';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

const DEMO_ROLE = {
  id: 'pm-sfo',
  title: 'Staff PM',
  loc: '',
  pipeline: '',
  status: 'live' as const,
  dept: '',
  owner: '',
  created_at: '',
  ready_to_debrief: true,
  must_have: [],
  nice_to_have: [],
};

const POOL = [
  {
    id: 'c1',
    name: 'Sloane Natarajan',
    role: '',
    stage: 'Ready to debrief',
    rounds: 4,
    scoresIn: 4,
    avatar: 'PN',
    color: '#EADFD4',
    flag: '4/4 rounds',
    status: 'ready' as const,
  },
  {
    id: 'c2',
    name: 'Marcus Chen',
    role: '',
    stage: 'Ready to debrief',
    rounds: 4,
    scoresIn: 4,
    avatar: 'MC',
    color: '#D8EFE3',
    flag: '4/4 rounds',
    status: 'ready' as const,
  },
];

// The packet BODY id (stamped by the cortex skill) deliberately differs from
// the generate response's ROW id ('ROW-1' below) so the test proves the flow
// threads the ROW id into selections, NOT this body id.
const READY_PACKET = {
  id: 'BODY-9',
  requisition_id: 'pm-sfo',
  role_title: 'Staff PM',
  title: 'Staff PM debrief',
  subtitle: 'Comparison',
  generated_at: '2026-04-16T18:45:00Z',
  generated_by: 'OpenRecruiting debrief agent',
  status: 'fresh',
  confidence: 'high',
  verdict: 'strong_hire',
  headline_recommendation: 'Advance Sloane.',
  panel_members: [],
  candidates: [
    {
      candidate_id: 'c1',
      name: 'Sloane Natarajan',
      initials: 'PN',
      color: '#EADFD4',
      rank: 1,
      verdict: 'strong_hire',
      headline: 'Top of slate.',
      aggregate_score: 3.6,
      score_scale: 4,
      rounds_completed: 4,
      rounds_total: 4,
      top_strengths: [],
      top_concerns: [],
      recommendation: 'Offer.',
      panel_votes: [],
    },
  ],
  source_stats: { scorecards: 8, transcripts: 2 },
  themes: [],
  decision_matrix: [],
  risks: [],
  next_steps: [],
};

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function forceV2(): void {
  process.env.NEXT_PUBLIC_V2_API = 'true';
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
}

async function seedToAnalyzing(): Promise<void> {
  forceV2();
  await pickDebriefRole(DEMO_ROLE);
  // The picker stage would normally stash the pool; seed it directly here.
  useSessionStore.getState().updateSelections('debrief', {
    selectedCandidates: ['c1', 'c2'],
    candidatePool: POOL,
  });
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

describe('debrief flow — v2 generate + poll', () => {
  test('happy path: generate → poll → open comparative artifact with the real packet', async () => {
    let polledUrl = '';
    const fetchMock = mock(async (url: string) => {
      if (String(url).endsWith('/api/v2/debrief/generate')) {
        // The ROW id `/save` + `/packets/{id}` key on — distinct from the
        // polled packet body's `.id` ('BODY-9').
        return jsonResponse({ packet_id: 'ROW-1', status: 'generating' });
      }
      // Packet ready on the first poll.
      polledUrl = String(url);
      return jsonResponse(READY_PACKET);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await seedToAnalyzing();
    await confirmCandidatePick({ speed: 0 });
    await completeAnalyzing({ speed: 0 });

    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('result');
    // BUG A: the ROW id from the generate response is threaded into selections
    // for the Save/print handoff — NOT the packet body's `.id` ('BODY-9').
    expect(s?.selections.packetId).toBe('ROW-1');
    // The poll keyed on the ROW id too.
    expect(polledUrl).toBe('http://backend.test/api/v2/debrief/packets/ROW-1');
    const art = useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID];
    expect(art?.type).toBe('comparative');
    const data = art?.data as { packet?: { id: string }; candidateIds?: string[] };
    // The artifact carries the real (polled) packet body, id and all.
    expect(data.packet?.id).toBe('BODY-9');
    expect(data.candidateIds).toEqual(['c1', 'c2']);
  });

  test('failure: a terminal backend error surfaces and routes to the failed stage', async () => {
    const fetchMock = mock(async (url: string) => {
      if (String(url).endsWith('/api/v2/debrief/generate')) {
        return jsonResponse({ packet_id: 'packet-1', status: 'generating' });
      }
      // Terminal (non-404) error on the first poll.
      return jsonResponse({ detail: 'boom' }, { status: 500 });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await seedToAnalyzing();
    await confirmCandidatePick({ speed: 0 });
    await completeAnalyzing({ speed: 0 });

    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('failed');
    expect(s?.selections.generationError).toBeTruthy();
    // No artifact opened on failure.
    expect(useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID]).toBeUndefined();
  });

  test('timeout: an aborted generate routes to the failed stage (FIX 3)', async () => {
    // Simulate the bounded-timeout AbortController firing: the generate fetch
    // rejects with the DOMException('AbortError') a real fetch raises on abort.
    // `request` maps that to a terminal DebriefApiError → completeAnalyzing
    // surfaces it and routes to `failed`.
    const fetchMock = mock(async (url: string) => {
      if (String(url).endsWith('/api/v2/debrief/generate')) {
        throw new DOMException('Aborted', 'AbortError');
      }
      return jsonResponse(READY_PACKET);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await seedToAnalyzing();
    await confirmCandidatePick({ speed: 0 });
    await completeAnalyzing({ speed: 0 });

    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('failed');
    expect(s?.selections.generationError).toBeTruthy();
    expect(useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID]).toBeUndefined();
  });

  test('retryFromFailure clears the error and returns to candidate_pick (selections kept)', async () => {
    const fetchMock = mock(async (url: string) => {
      if (String(url).endsWith('/api/v2/debrief/generate')) {
        return jsonResponse({ packet_id: 'packet-1', status: 'generating' });
      }
      return jsonResponse({ detail: 'boom' }, { status: 500 });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await seedToAnalyzing();
    await confirmCandidatePick({ speed: 0 });
    await completeAnalyzing({ speed: 0 });
    expect(useSessionStore.getState().sessions.debrief?.stage).toBe('failed');

    retryFromFailure();
    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('candidate_pick');
    expect(s?.selections.generationError).toBeNull();
    // Chosen candidates are preserved so the user can adjust + retry.
    expect(s?.selections.selectedCandidates).toEqual(['c1', 'c2']);
  });
});

describe('debrief flow — reopen + resume a packet', () => {
  const OLD_TURNS = [
    { role: 'user', text: 'why is she a Maybe?', idx: 0, ts: '2026-06-08T10:00:00Z' },
    {
      role: 'assistant',
      text: 'The rating contradicts the written summary.',
      idx: 1,
      ts: '2026-06-08T10:00:05Z',
    },
    {
      role: 'assistant',
      text: '',
      idx: 2,
      proposed_action: { kind: 'propose_add_round', input: {} },
    },
  ];

  function mockReopenFetch() {
    const fetchMock = mock(async (url: string) => {
      const u = String(url);
      if (u.endsWith('/packets/OLD-1/conversation')) {
        return jsonResponse({ packet_id: 'OLD-1', turns: OLD_TURNS });
      }
      if (u.endsWith('/packets/OLD-1')) {
        return jsonResponse(READY_PACKET);
      }
      throw new Error(`unexpected fetch: ${u}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    return fetchMock;
  }

  test('reopening an old packet refetches it, activates it, and hydrates its conversation', async () => {
    forceV2();
    mockReopenFetch();
    const { reopenDebriefPacket } = await import('./flow');

    await reopenDebriefPacket({ packetId: 'OLD-1', roleTitle: 'Staff PM' });

    const s = useSessionStore.getState().sessions.debrief;
    // The reopened packet becomes the ACTIVE chat target on the result stage.
    expect(s?.stage).toBe('result');
    expect(s?.selections.packetId).toBe('OLD-1');
    expect(s?.selections.packetArtifactId).toBe('debrief-packet-OLD-1');
    expect(s?.artifactId).toBe('debrief-packet-OLD-1');
    const art = useArtifactStore.getState().artifacts['debrief-packet-OLD-1'];
    expect(art?.type).toBe('comparative');
    // Both prose turns hydrate with stable conv ids + server timestamps; the
    // propose-only (empty text) turn is skipped; an announce line follows.
    const msgs = s?.messages ?? [];
    const conv = msgs.filter((m) => m.id.startsWith('conv-OLD-1-'));
    expect(conv.map((m) => m.text)).toEqual([
      'why is she a Maybe?',
      'The rating contradicts the written summary.',
    ]);
    expect(conv[0]?.ts).toBe('2026-06-08T10:00:00Z');
    expect(msgs.at(-1)?.text).toContain('restored 2 earlier messages');
  });

  test('reopening the same packet twice never re-hydrates the conversation', async () => {
    forceV2();
    const fetchMock = mockReopenFetch();
    const { reopenDebriefPacket } = await import('./flow');

    await reopenDebriefPacket({ packetId: 'OLD-1', roleTitle: 'Staff PM' });
    const countAfterFirst = useSessionStore.getState().sessions.debrief?.messages.length ?? 0;

    await reopenDebriefPacket({ packetId: 'OLD-1', roleTitle: 'Staff PM' });
    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.length).toBe(countAfterFirst);
    // Conversation fetched exactly once.
    const convCalls = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/conversation'));
    expect(convCalls.length).toBe(1);
  });

  test('hydration dedupes turns already on screen (e.g. restored via Show earlier)', async () => {
    forceV2();
    mockReopenFetch();
    const { reopenDebriefPacket } = await import('./flow');

    const store = useSessionStore.getState();
    store.startSession('debrief', 'role_pick');
    store.appendMessage('debrief', {
      id: 'local-1',
      role: 'user',
      text: 'why is she a Maybe?',
      ts: '2026-06-08T10:00:00Z',
      source: 'chat',
    });

    await reopenDebriefPacket({ packetId: 'OLD-1', roleTitle: 'Staff PM' });

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const sameText = msgs.filter((m) => m.text === 'why is she a Maybe?');
    expect(sameText.length).toBe(1); // the local copy only — no conv duplicate
    expect(msgs.at(-1)?.text).toContain('restored 1 earlier message');
  });
});
