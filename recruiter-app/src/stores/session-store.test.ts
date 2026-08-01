import { beforeEach, describe, expect, test } from 'bun:test';
import { makeMessage } from '@/lib/sub-agent-runner';
import { PERSIST_THROTTLE_MS, useSessionStore } from './session-store';

beforeEach(() => {
  useSessionStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('session-store', () => {
  test('initial sessions are null for all agents', () => {
    const s = useSessionStore.getState();
    expect(s.sessions.intake).toBeNull();
    expect(s.sessions.debrief).toBeNull();
  });

  test('startSession creates a fresh session', () => {
    useSessionStore.getState().startSession('intake', 'mode_choice');
    const s = useSessionStore.getState().sessions.intake;
    expect(s).not.toBeNull();
    expect(s?.stage).toBe('mode_choice');
    expect(s?.status).toBe('fresh');
    expect(s?.messages).toHaveLength(0);
  });

  test('appendMessage adds message and flips status to active', () => {
    useSessionStore.getState().startSession('intake', 'mode_choice');
    useSessionStore.getState().appendMessage('intake', {
      id: 'm1',
      role: 'user',
      text: 'Staff PM',
      ts: new Date().toISOString(),
      source: 'scripted',
    });
    const s = useSessionStore.getState().sessions.intake;
    expect(s?.messages).toHaveLength(1);
    expect(s?.status).toBe('active');
  });

  test('setStage updates current stage', () => {
    useSessionStore.getState().startSession('intake', 'mode_choice');
    useSessionStore.getState().setStage('intake', 'intake_chat');
    expect(useSessionStore.getState().sessions.intake?.stage).toBe('intake_chat');
  });

  test('endSession archives and clears current', () => {
    useSessionStore.getState().startSession('debrief', 'role_pick');
    useSessionStore.getState().appendMessage('debrief', {
      id: 'm1',
      role: 'user',
      text: 'hi',
      ts: new Date().toISOString(),
      source: 'scripted',
    });
    useSessionStore.getState().endSession('debrief');
    expect(useSessionStore.getState().sessions.debrief).toBeNull();
    expect(useSessionStore.getState().archived.debrief).toHaveLength(1);
  });

  test('rehydrate restores most recent archived session', () => {
    useSessionStore.getState().startSession('debrief', 'role_pick');
    useSessionStore.getState().appendMessage('debrief', {
      id: 'm1',
      role: 'user',
      text: 'previous',
      ts: new Date().toISOString(),
      source: 'scripted',
    });
    useSessionStore.getState().endSession('debrief');
    useSessionStore.getState().rehydrate('debrief');
    const s = useSessionStore.getState().sessions.debrief;
    expect(s).not.toBeNull();
    expect(s?.messages[0]?.text).toBe('previous');
  });

  test('archived list caps at MAX_ARCHIVED (5) — oldest drops first', () => {
    const mark = (label: string) => {
      useSessionStore.getState().startSession('debrief', 'role_pick');
      useSessionStore.getState().appendMessage('debrief', {
        id: `m-${label}`,
        role: 'user',
        text: label,
        ts: new Date().toISOString(),
        source: 'scripted',
      });
      useSessionStore.getState().endSession('debrief');
    };

    // Archive 6 sessions — oldest (first) should fall off.
    mark('s0');
    mark('s1');
    mark('s2');
    mark('s3');
    mark('s4');
    mark('s5');

    const list = useSessionStore.getState().archived.debrief;
    expect(list).toHaveLength(5);
    // Newest first — s5 should be at index 0, s0 should be gone.
    expect(list[0]?.messages[0]?.text).toBe('s5');
    const marks = list.map((s) => s.messages[0]?.text);
    expect(marks).toEqual(['s5', 's4', 's3', 's2', 's1']);
    expect(marks.includes('s0')).toBe(false);
  });
});

describe('persistence + restore', () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
    if (typeof localStorage !== 'undefined') localStorage.clear();
  });

  test('archiveAllLiveSessions moves live conversations to the archive and starts fresh', () => {
    const store = useSessionStore.getState();
    store.startSession('debrief', 'result');
    store.appendMessage('debrief', makeMessage('user', 'why is she a Maybe?', 'text', 'chat'));
    store.startSession('intake', 'mode_choice'); // live but empty — just cleared

    useSessionStore.getState().archiveAllLiveSessions();

    const s = useSessionStore.getState();
    expect(s.sessions.debrief).toBeNull();
    expect(s.sessions.intake).toBeNull();
    expect(s.archived.debrief).toHaveLength(1);
    expect(s.archived.intake).toHaveLength(0);
    expect(s.archived.debrief[0]?.status).toBe('paused');
  });

  test('archiveAllLiveSessions settles pending confirm cards to dismissed', () => {
    const store = useSessionStore.getState();
    store.startSession('debrief', 'result');
    const card = makeMessage('agent', '', 'text', 'chat');
    card.confirmAction = {
      kind: 'propose_record_decision',
      input: { candidate_ids: ['c1'], summary: 'Record hire', rationale: '' },
    };
    card.confirmStatus = 'pending';
    store.appendMessage('debrief', card);
    const done = makeMessage('agent', '', 'text', 'chat');
    done.confirmAction = {
      kind: 'propose_add_round',
      input: { candidate_ids: ['c1'], summary: 'Add round', rationale: '' },
    };
    done.confirmStatus = 'done';
    store.appendMessage('debrief', done);

    useSessionStore.getState().archiveAllLiveSessions();

    const archivedMsgs = useSessionStore.getState().archived.debrief[0]?.messages ?? [];
    expect(archivedMsgs[0]?.confirmStatus).toBe('dismissed');
    expect(archivedMsgs[1]?.confirmStatus).toBe('done');
  });

  test('loadEarlier restores the most recent archived session above the current one', () => {
    const store = useSessionStore.getState();
    store.startSession('debrief', 'role_pick');
    store.appendMessage('debrief', makeMessage('user', 'old question', 'text', 'chat'));
    store.endSession('debrief');

    store.startSession('debrief', 'role_pick');
    store.appendMessage('debrief', makeMessage('user', 'new question', 'text', 'chat'));

    useSessionStore.getState().loadEarlier('debrief');

    const s = useSessionStore.getState();
    const texts = s.sessions.debrief?.messages.map((m) => m.text);
    expect(texts).toEqual(['old question', 'new question']);
    expect(s.archived.debrief).toHaveLength(0);
  });

  test('loadEarlier walks the archive newest-first, one session per click', () => {
    const store = useSessionStore.getState();
    const archiveOne = (text: string) => {
      store.startSession('debrief', 'role_pick');
      store.appendMessage('debrief', makeMessage('user', text, 'text', 'chat'));
      store.endSession('debrief');
    };
    archiveOne('first');
    archiveOne('second');

    store.startSession('debrief', 'role_pick');
    useSessionStore.getState().loadEarlier('debrief');
    expect(useSessionStore.getState().sessions.debrief?.messages[0]?.text).toBe('second');

    useSessionStore.getState().loadEarlier('debrief');
    const texts = useSessionStore.getState().sessions.debrief?.messages.map((m) => m.text);
    expect(texts).toEqual(['first', 'second']);
    expect(useSessionStore.getState().archived.debrief).toHaveLength(0);
  });

  test('loadEarlier with no current session creates one from the archive', () => {
    const store = useSessionStore.getState();
    store.startSession('debrief', 'role_pick');
    store.appendMessage('debrief', makeMessage('user', 'restored', 'text', 'chat'));
    store.endSession('debrief');

    useSessionStore.getState().loadEarlier('debrief');
    expect(useSessionStore.getState().sessions.debrief?.messages[0]?.text).toBe('restored');
  });

  test('writes land in localStorage after the persist throttle window', async () => {
    // This file's environment has no DOM — inject a fake localStorage so the
    // throttled storage adapter has somewhere to flush. Access is lazy, so the
    // fake installed here is the one the flush hits.
    const backing = new Map<string, string>();
    const fake = {
      getItem: (k: string) => backing.get(k) ?? null,
      setItem: (k: string, v: string) => {
        backing.set(k, v);
      },
      removeItem: (k: string) => {
        backing.delete(k);
      },
    } as unknown as Storage;
    // happy-dom (when registered) exposes localStorage as a getter-only
    // accessor — plain assignment throws. Shadow via defineProperty and
    // restore the original descriptor (or delete the shadow) afterwards.
    const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    Object.defineProperty(globalThis, 'localStorage', {
      value: fake,
      configurable: true,
      writable: true,
    });
    try {
      const store = useSessionStore.getState();
      store.startSession('debrief', 'role_pick');
      store.appendMessage('debrief', makeMessage('user', 'persist me', 'text', 'chat'));

      await new Promise((resolve) => setTimeout(resolve, PERSIST_THROTTLE_MS + 200));
      expect(backing.get('openrecruiting.sessions.v1') ?? '').toContain('persist me');
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(globalThis, 'localStorage', originalDescriptor);
      } else {
        delete (globalThis as { localStorage?: Storage }).localStorage;
      }
    }
  });
});

describe('Message.source', () => {
  beforeEach(() => useSessionStore.getState().reset());

  test("makeMessage defaults source to 'scripted'", () => {
    const m = makeMessage('agent', 'hello');
    expect(m.source).toBe('scripted');
  });

  test('makeMessage accepts explicit chat source', () => {
    const m = makeMessage('user', 'hi', 'text', 'chat');
    expect(m.source).toBe('chat');
  });

  test('appendMessage preserves source', () => {
    const store = useSessionStore.getState();
    store.startSession('intake', 'mode_choice');
    store.appendMessage('intake', makeMessage('user', 'hi', 'text', 'chat'));
    const session = useSessionStore.getState().sessions.intake;
    expect(session?.messages[0]?.source).toBe('chat');
  });
});
