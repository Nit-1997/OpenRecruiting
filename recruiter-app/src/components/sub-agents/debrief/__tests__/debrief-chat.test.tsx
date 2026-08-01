// Phase 1 Task 1.8 — FE chat wiring for the debrief conversation agent.
//
// Drives the REAL flow + REAL zustand session store against a scoped
// `globalThis.fetch` mock (restored by test-setup's backstop). v2 is flipped ON
// per test so the flow threads `selections.packetId` and the chat client builds
// against the pinned backend base.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen } from '@testing-library/react';
import { Composer } from '@/components/shell/composer';
import { openDebriefChat } from '@/lib/debrief/chat';
import { cancelRun } from '@/lib/sub-agent-runner';
import { useArtifactStore, useComposerStore, useSessionStore, useShellStore } from '@/stores';
import { submitDebriefMessage } from '../flow';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

function forceV2(): void {
  process.env.NEXT_PUBLIC_V2_API = 'true';
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
}

/** Build a `text/event-stream` Response whose body emits the given raw chunks
 *  (each chunk is enqueued as one read), so callers can split a single SSE
 *  frame across two chunks to exercise the buffering path. */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
}

/** One SSE frame: `data: <json>\n\n`. */
function frame(type: string, data: unknown): string {
  return `data: ${JSON.stringify({ type, data })}\n\n`;
}

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  useShellStore.getState().reset();
  // Reset via setState (not `.reset()`) — the composer-store action methods can
  // be a process-wide no-op stub installed by another test file (see the scope
  // note in the composer test below).
  useComposerStore.setState({ scope: { kind: 'home' }, value: '', uploading: null });
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

describe('openDebriefChat — SSE parsing', () => {
  test('dispatches token frames in order, then a proposed_action, then done', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Hello'),
        frame('token', ' world'),
        frame('proposed_action', { kind: 'add_round', input: { name: 'System design' } }),
        frame('done', { turn_idx: 1 }),
      ]),
    ) as unknown as typeof fetch;

    const tokens: string[] = [];
    const proposed: Array<{ kind: string; input: Record<string, unknown> }> = [];
    let errored: string | null = null;

    await openDebriefChat('pkt-1', 'why A?', {
      onToken: (t) => tokens.push(t),
      onProposed: (p) => proposed.push(p),
      onError: (m) => {
        errored = m;
      },
    });

    expect(tokens).toEqual(['Hello', ' world']);
    expect(proposed).toHaveLength(1);
    expect(proposed[0]?.kind).toBe('add_round');
    expect(proposed[0]?.input).toEqual({ name: 'System design' });
    expect(errored).toBeNull();
  });

  test('error frame routes to onError with the static message', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([frame('error', { message: 'The agent hit a snag.' })]),
    ) as unknown as typeof fetch;

    let errored: string | null = null;
    await openDebriefChat('pkt-1', 'boom', {
      onToken: () => {},
      onProposed: () => {},
      onError: (m) => {
        errored = m;
      },
    });

    expect(errored).toBe('The agent hit a snag.');
  });

  test('buffers a frame split across two stream chunks', async () => {
    forceV2();
    const full = frame('token', 'spanning');
    const mid = Math.floor(full.length / 2);
    globalThis.fetch = mock(async () =>
      sseResponse([full.slice(0, mid), full.slice(mid), frame('done', { turn_idx: 0 })]),
    ) as unknown as typeof fetch;

    const tokens: string[] = [];
    await openDebriefChat('pkt-1', 'msg', {
      onToken: (t) => tokens.push(t),
      onProposed: () => {},
    });

    expect(tokens).toEqual(['spanning']);
  });

  test('a network failure surfaces a static onError, never throws raw', async () => {
    forceV2();
    globalThis.fetch = mock(async () => {
      throw new Error('socket reset');
    }) as unknown as typeof fetch;

    let errored: string | null = null;
    await openDebriefChat('pkt-1', 'msg', {
      onToken: () => {},
      onProposed: () => {},
      onError: (m) => {
        errored = m;
      },
    });

    expect(errored).toBeTruthy();
    expect(errored).not.toContain('socket reset');
  });
});

describe('submitDebriefMessage', () => {
  function seedResultSession(packetId: string | null): void {
    const sessions = useSessionStore.getState();
    sessions.startSession('debrief', 'result');
    sessions.updateSelections('debrief', packetId ? { packetId } : {});
  }

  test('appends a user message then streams tokens into a single agent message', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'A '),
        frame('token', 'edges '),
        frame('token', 'B.'),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    await submitDebriefMessage('why does A edge B?');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const user = msgs.find((m) => m.role === 'user');
    expect(user?.text).toBe('why does A edge B?');
    const agents = msgs.filter((m) => m.role === 'agent');
    // A SINGLE agent bubble, streamed in place — not one bubble per token.
    expect(agents).toHaveLength(1);
    expect(agents[0]?.text).toBe('A edges B.');
  });

  test('a proposed_action appends a confirm-card message (not a placeholder)', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Consider adding a round. '),
        frame('proposed_action', {
          kind: 'propose_add_round',
          input: {
            candidate_ids: ['c1'],
            summary: 'Add a System design round',
            rationale: 'The panel never probed architecture depth.',
            name: 'System design',
          },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    await submitDebriefMessage('should we add a round?');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    // No legacy placeholder text.
    expect(msgs.some((m) => m.text.includes('OpenRecruiting suggests'))).toBe(false);
    expect(msgs.some((m) => m.text.includes('confirm coming soon'))).toBe(false);
    // A confirm-card message carrying the proposed action, awaiting a decision.
    const card = msgs.find((m) => m.confirmAction);
    expect(card?.confirmAction?.kind).toBe('propose_add_round');
    expect(card?.confirmAction?.input.summary).toBe('Add a System design round');
    expect(card?.confirmStatus).toBe('pending');
  });

  test('a propose_log_insight appends a confirm-card carrying the insight payload', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Worth remembering. '),
        frame('proposed_action', {
          kind: 'propose_log_insight',
          input: {
            candidate_ids: [],
            summary: 'Remember we value async communication for staff roles',
            rationale: 'You called this out twice across the debrief.',
            insight_kind: 'recruiter_preference',
            text: 'We value async communication for staff engineering roles.',
          },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    await submitDebriefMessage('remember we like async comms');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const card = msgs.find((m) => m.confirmAction);
    expect(card?.confirmAction?.kind).toBe('propose_log_insight');
    expect(card?.confirmAction?.input.summary).toBe(
      'Remember we value async communication for staff roles',
    );
    expect(card?.confirmAction?.input.insight_kind).toBe('recruiter_preference');
    expect(card?.confirmStatus).toBe('pending');
  });

  test('propose_new_debrief same_role hands off to the candidate picker (no confirm card)', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Sure — let’s set up a new comparison. '),
        frame('proposed_action', { kind: 'propose_new_debrief', input: { scope: 'same_role' } }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', {
      roleId: 'role-1',
      roleTitle: 'AI Director',
      selectedCandidates: ['c1', 'c2'],
    });
    await submitDebriefMessage('cool can we debrief another round?');
    // The handoff is fired from the streamed event without being awaited —
    // give the microtask chain a tick to enter the stage machine.
    await new Promise((resolve) => setTimeout(resolve, 0));

    const session = useSessionStore.getState().sessions.debrief;
    // Workflow restart, not a write: NO confirm card, picker stage entered,
    // prior selection cleared, role retained for the same-role picker.
    expect(session?.messages.some((m) => m.confirmAction)).toBe(false);
    expect(session?.stage).toBe('candidate_pick');
    expect(session?.selections.selectedCandidates).toEqual([]);
    expect(session?.selections.roleId).toBe('role-1');
    cancelRun('debrief');
  });

  test('propose_open_scheduler queues the drawer and detaches the packet artifact', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Let’s pick the slot in the scheduler. '),
        frame('proposed_action', {
          kind: 'propose_open_scheduler',
          input: { candidate_ids: ['cand-ali'], round_ref: 'AI Domain Depth' },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', {
      roleId: 'role-1',
      roleTitle: 'AI Director',
    });
    useSessionStore.getState().setArtifactId('debrief', 'debrief-artifact-1');
    await submitDebriefMessage('schedule Ali this Friday 2 PM PST');

    const session = useSessionStore.getState().sessions.debrief;
    // A UI intent, not a write: no confirm card; the workspace artifact column
    // now hosts the scheduler (candidate_packet) IN PLACE of the packet — same
    // panel geometry, so the chat column never reflows.
    expect(session?.messages.some((m) => m.confirmAction)).toBe(false);
    expect(session?.selections.schedulerQueue).toEqual({
      candidateIds: ['cand-ali'],
      index: 0,
    });
    expect(session?.artifactId).toBe('debrief-scheduler');
    const schedulerArtifact = useArtifactStore.getState().artifacts['debrief-scheduler'];
    expect(schedulerArtifact?.type).toBe('candidate_packet');
    expect((schedulerArtifact?.data as { roleId?: string })?.roleId).toBe('role-1');
  });

  test('propose_open_scheduler with two candidates walks the queue via Next then Done', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('proposed_action', {
          kind: 'propose_open_scheduler',
          input: { candidate_ids: ['cand-zara', 'cand-ali'] },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', { roleId: 'role-1' });
    await submitDebriefMessage('schedule the rounds for both candidates');

    const queue = () =>
      useSessionStore.getState().sessions.debrief?.selections.schedulerQueue as {
        candidateIds: string[];
        index: number;
      } | null;
    expect(queue()).toEqual({ candidateIds: ['cand-zara', 'cand-ali'], index: 0 });

    const { advanceSchedulerQueue } = await import('../flow');
    advanceSchedulerQueue();
    expect(queue()).toEqual({ candidateIds: ['cand-zara', 'cand-ali'], index: 1 });

    // Advancing past the last candidate finishes the queue and leaves a
    // pointer back to the packet card.
    advanceSchedulerQueue();
    expect(queue()).toBeNull();
    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.at(-1)?.text).toContain('Scheduling done');
  });

  test('propose_quick_replies attaches tappable pills to the streamed bubble', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('token', 'Here’s what I can do for this debrief.'),
        frame('proposed_action', {
          kind: 'propose_quick_replies',
          input: {
            options: [
              'Pull Zara’s round-by-round detail',
              'Log this learning to Cortex',
              'Open the scheduler',
            ],
          },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    await submitDebriefMessage('what can you do?');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    // No confirm card — the pills ride on the agent's own bubble.
    expect(msgs.some((m) => m.confirmAction)).toBe(false);
    const bubble = msgs.find((m) => m.role === 'agent' && m.chips);
    expect(bubble?.text).toContain('what I can do');
    expect(bubble?.chips?.map((c) => c.label)).toEqual([
      'Pull Zara’s round-by-round detail',
      'Log this learning to Cortex',
      'Open the scheduler',
    ]);
  });

  test('quick replies without a preamble still land on a fallback bubble', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('proposed_action', {
          kind: 'propose_quick_replies',
          input: { options: ['Push back on a score'] },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    await submitDebriefMessage('hm');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const bubble = msgs.find((m) => m.role === 'agent' && m.chips);
    expect(bubble?.text).toBeTruthy();
    expect(bubble?.chips?.[0]?.label).toBe('Push back on a score');
  });

  test('a bare tool-call turn (no tokens) leaves no empty agent bubble', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        // No token frames at all — the model went straight to the tool.
        frame('proposed_action', {
          kind: 'propose_open_scheduler',
          input: { candidate_ids: ['cand-ali'] },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', { roleId: 'role-1' });
    await submitDebriefMessage('schedule ali');

    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.some((m) => m.role === 'agent' && m.text === '' && !m.confirmAction)).toBe(false);
  });

  test('propose_open_scheduler without a candidate degrades to a chat ask', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('proposed_action', { kind: 'propose_open_scheduler', input: { candidate_ids: [] } }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', { roleId: 'role-1' });
    await submitDebriefMessage('schedule the round');

    const session = useSessionStore.getState().sessions.debrief;
    expect(session?.selections.schedulerQueue).toBeUndefined();
    expect(session?.messages.at(-1)?.text).toContain('which candidate');
  });

  test('propose_new_debrief different_role returns to the role picker', async () => {
    forceV2();
    globalThis.fetch = mock(async () =>
      sseResponse([
        frame('proposed_action', {
          kind: 'propose_new_debrief',
          input: { scope: 'different_role' },
        }),
        frame('done', { turn_idx: 0 }),
      ]),
    ) as unknown as typeof fetch;

    seedResultSession('pkt-9');
    useSessionStore.getState().updateSelections('debrief', {
      roleId: 'role-1',
      roleTitle: 'AI Director',
    });
    await submitDebriefMessage('let’s debrief a different role');
    await new Promise((resolve) => setTimeout(resolve, 0));

    const session = useSessionStore.getState().sessions.debrief;
    expect(session?.messages.some((m) => m.confirmAction)).toBe(false);
    expect(session?.stage).toBe('role_pick');
    cancelRun('debrief');
  });

  test('missing packetId degrades gracefully and never calls fetch', async () => {
    forceV2();
    const fetchMock = mock(async () => sseResponse([frame('done', { turn_idx: 0 })]));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    seedResultSession(null);
    await submitDebriefMessage('why A?');

    expect(fetchMock).not.toHaveBeenCalled();
    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    const agent = msgs.find((m) => m.role === 'agent');
    expect(agent?.text).toContain('generated debrief packet');
  });
});

describe('composer — debrief result branch', () => {
  test('routes a result-stage submission to submitDebriefMessage, not the canned fallback', async () => {
    forceV2();
    // A guard fetch that would FAIL the test if the composer ever reached the
    // network — the branch is exercised via the synchronous no-packet path
    // below (deterministic; immune to the cross-file SSE/act timing flakes the
    // pre-existing "Composer home submit" tests exhibit under the full suite).
    const fetchMock = mock(async () => sseResponse([frame('done', { turn_idx: 0 })]));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    // Mount first, then seed all state and submit in ONE synchronous tick so a
    // concurrently-scheduled file's store reset can't slip between setup and
    // submit (the cross-file flake the pre-existing "Composer home submit"
    // tests exhibit). result stage WITHOUT a threaded packetId →
    // submitDebriefMessage appends its graceful "need a generated packet" agent
    // message synchronously and never calls the API; the canned fallback would
    // instead echo the STAGE_FALLBACK.debrief copy — so the paths are distinct.
    render(<Composer id="c" />);
    useShellStore.getState().setActiveTab('debrief');
    useSessionStore.getState().startSession('debrief', 'result');
    // Set scope + value via the REAL store's setState — NOT the action methods.
    // Another file (intake/page.test.tsx) installs a process-wide
    // `mock.module('@/stores/composer-store')` whose `setAgenticScope` is a
    // no-op; when that mock wins the registry, calling the action leaves scope
    // on the `home` default. setState writes the real state directly.
    useComposerStore.setState({
      scope: { kind: 'agentic', tabId: 'debrief' },
      value: 'push back on the comms score',
    });
    fireEvent.submit(screen.getByRole('form'));

    // The no-packet branch is fully synchronous (no await before its appends),
    // so the store is settled the instant fireEvent.submit returns — assert
    // directly rather than via waitFor (no cross-file async-timing window).
    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    // Routed to the chat flow: user message + the graceful no-packet reply.
    expect(msgs.some((m) => m.role === 'user' && m.text === 'push back on the comms score')).toBe(
      true,
    );
    expect(
      msgs.some((m) => m.role === 'agent' && m.text.includes('generated debrief packet')),
    ).toBe(true);
    // The canned fallback text MUST NOT appear — the branch routed to chat.
    expect(
      msgs.some(
        (m) => m.text === 'Pick the candidates you want to compare and I will build the debrief.',
      ),
    ).toBe(false);
    // The no-packet path never touches the network.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
