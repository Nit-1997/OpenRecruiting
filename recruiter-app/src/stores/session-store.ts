import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { HISTORY_CHUNK, type HistorySeed, HOME_HISTORY } from '@/fixtures/home-history';
import { SUB_AGENT_HISTORY, SUB_AGENT_HISTORY_CHUNK } from '@/fixtures/sub-agent-history';
import type { ChatTabId, Message, Session, StageId, SubAgentId } from '@/types';
import { SUB_AGENT_IDS } from '@/types';

function historyForAgent(agentId: ChatTabId): { seeds: HistorySeed[]; chunk: number } {
  if (agentId === 'home') return { seeds: HOME_HISTORY, chunk: HISTORY_CHUNK };
  return {
    seeds: SUB_AGENT_HISTORY[agentId as SubAgentId] ?? [],
    chunk: SUB_AGENT_HISTORY_CHUNK,
  };
}

type Sessions = Record<ChatTabId, Session | null>;
type Archived = Record<ChatTabId, Session[]>;

const CHAT_TAB_IDS: readonly ChatTabId[] = [...SUB_AGENT_IDS, 'home'] as const;

const initialSessions = (): Sessions =>
  Object.fromEntries(CHAT_TAB_IDS.map((id) => [id, null])) as unknown as Sessions;

const initialArchived = (): Archived =>
  Object.fromEntries(CHAT_TAB_IDS.map((id) => [id, []])) as unknown as Archived;

interface SessionStoreState {
  sessions: Sessions;
  archived: Archived;
  archiveAllLiveSessions: () => void;
  startSession: (agentId: ChatTabId, initialStage: StageId) => void;
  appendMessage: (agentId: ChatTabId, message: Message) => void;
  updateMessage: (agentId: ChatTabId, messageId: string, patch: Partial<Message>) => void;
  setStage: (agentId: ChatTabId, stage: StageId) => void;
  setArtifactId: (agentId: ChatTabId, artifactId: string | null) => void;
  popArtifact: (agentId: ChatTabId) => void;
  updateSelections: (agentId: ChatTabId, selections: Record<string, unknown>) => void;
  endSession: (agentId: ChatTabId) => void;
  rehydrate: (agentId: ChatTabId) => void;
  loadEarlier: (agentId: ChatTabId) => void;
  reset: () => void;
}

const MAX_ARCHIVED = 5;

/** How long persisted writes coalesce. Streaming patches the tail message per
 *  token (each one a store set), so an unthrottled persist would stringify the
 *  whole session map dozens of times a second. */
export const PERSIST_THROTTLE_MS = 400;

/**
 * localStorage with trailing-throttled writes: the latest value lands at most
 * once per PERSIST_THROTTLE_MS, plus a flush on pagehide/beforeunload so a
 * navigation can't drop the trailing write. Reads serve the pending value so
 * the throttle is invisible to rehydration.
 */
function createThrottledStorage() {
  let pending = new Map<string, string>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    const writes = pending;
    pending = new Map();
    for (const [key, value] of writes) {
      try {
        localStorage.setItem(key, value);
      } catch {
        // Quota/SSR — chat persistence is best-effort.
      }
    }
  };

  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', flush);
    window.addEventListener('beforeunload', flush);
  }

  return {
    getItem: (name: string): string | null => {
      const queued = pending.get(name);
      if (queued !== undefined) return queued;
      try {
        return localStorage.getItem(name);
      } catch {
        return null;
      }
    },
    setItem: (name: string, value: string): void => {
      pending.set(name, value);
      if (!timer) timer = setTimeout(flush, PERSIST_THROTTLE_MS);
    },
    removeItem: (name: string): void => {
      pending.delete(name);
      try {
        localStorage.removeItem(name);
      } catch {
        // best-effort
      }
    },
  };
}

function touch(session: Session): Session {
  return { ...session, lastActiveAt: new Date().toISOString() };
}

export const useSessionStore = create<SessionStoreState>()(
  persist(
    (set) => ({
      sessions: initialSessions(),
      archived: initialArchived(),

      // Runs after rehydration on every full page load: every tab starts a
      // fresh session, and any live conversation from the previous page load
      // moves to the archive so "Show earlier" can restore it. Pending confirm
      // cards are settled to 'dismissed' — their proposals targeted a packet
      // state that may have moved on, so they must never be re-executable from
      // restored history.
      archiveAllLiveSessions: () =>
        set((state) => {
          const sessions = { ...state.sessions };
          const archived = { ...state.archived };
          for (const id of CHAT_TAB_IDS) {
            const current = sessions[id];
            if (!current) continue;
            if (current.messages.length > 0) {
              const settled: Session = {
                ...current,
                status: 'paused',
                messages: current.messages.map((m) =>
                  m.confirmStatus === 'pending' ? { ...m, confirmStatus: 'dismissed' } : m,
                ),
              };
              archived[id] = [settled, ...archived[id]].slice(0, MAX_ARCHIVED);
            }
            sessions[id] = null;
          }
          return { sessions, archived };
        }),

      startSession: (agentId, initialStage) =>
        set((state) => ({
          sessions: {
            ...state.sessions,
            [agentId]: {
              id: crypto.randomUUID(),
              startedAt: new Date().toISOString(),
              lastActiveAt: new Date().toISOString(),
              stage: initialStage,
              messages: [],
              selections: {},
              artifactId: null,
              artifactHistory: [],
              status: 'fresh',
            },
          },
        })),

      appendMessage: (agentId, message) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          return {
            sessions: {
              ...state.sessions,
              [agentId]: touch({
                ...current,
                messages: [...current.messages, message],
                status: 'active',
              }),
            },
          };
        }),

      updateMessage: (agentId, messageId, patch) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          const idx = current.messages.findIndex((m) => m.id === messageId);
          if (idx === -1) return state;
          const messages = current.messages.slice();
          messages[idx] = { ...messages[idx], ...patch } as Message;
          return {
            sessions: { ...state.sessions, [agentId]: touch({ ...current, messages }) },
          };
        }),

      setStage: (agentId, stage) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          return {
            sessions: { ...state.sessions, [agentId]: touch({ ...current, stage }) },
          };
        }),

      setArtifactId: (agentId, artifactId) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          const prev = current.artifactId;
          const history = current.artifactHistory ?? [];
          const nextHistory =
            prev && artifactId && prev !== artifactId && history.at(-1) !== prev
              ? [...history, prev]
              : artifactId === null
                ? []
                : history;
          return {
            sessions: {
              ...state.sessions,
              [agentId]: touch({ ...current, artifactId, artifactHistory: nextHistory }),
            },
          };
        }),

      popArtifact: (agentId) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          const history = current.artifactHistory ?? [];
          if (history.length === 0) return state;
          const next = history.slice(0, -1);
          const restored = history.at(-1) ?? null;
          return {
            sessions: {
              ...state.sessions,
              [agentId]: touch({ ...current, artifactId: restored, artifactHistory: next }),
            },
          };
        }),

      updateSelections: (agentId, selections) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          return {
            sessions: {
              ...state.sessions,
              [agentId]: touch({
                ...current,
                selections: { ...current.selections, ...selections },
              }),
            },
          };
        }),

      endSession: (agentId) =>
        set((state) => {
          const current = state.sessions[agentId];
          if (!current) return state;
          const archivedList = [current, ...state.archived[agentId]].slice(0, MAX_ARCHIVED);
          return {
            sessions: { ...state.sessions, [agentId]: null },
            archived: { ...state.archived, [agentId]: archivedList },
          };
        }),

      rehydrate: (agentId) =>
        set((state) => {
          const [latest, ...rest] = state.archived[agentId];
          if (!latest) return state;
          return {
            sessions: { ...state.sessions, [agentId]: { ...latest, status: 'active' } },
            archived: { ...state.archived, [agentId]: rest },
          };
        }),

      loadEarlier: (agentId) =>
        set((state) => {
          const now = Date.now();
          const current =
            state.sessions[agentId] ??
            ({
              id: crypto.randomUUID(),
              startedAt: new Date(now).toISOString(),
              lastActiveAt: new Date(now).toISOString(),
              stage: 'active',
              messages: [],
              selections: {},
              artifactId: null,
              artifactHistory: [],
              status: 'active',
            } as Session);

          // Real history first: restore the most recent archived session by
          // prepending its messages (original timestamps intact) above the
          // current conversation. One archived session per click, newest first.
          const [previous, ...remaining] = state.archived[agentId];
          if (previous) {
            const presentIds = new Set(current.messages.map((m) => m.id));
            const restored = previous.messages.filter((m) => !presentIds.has(m.id));
            const cursor = Number(current.selections.earlierCursor ?? 0);
            const next: Session = {
              ...current,
              messages: [...restored, ...current.messages],
              // Bump the cursor so the chat column scrolls the restored
              // messages into view (it watches earlierCursor).
              selections: { ...current.selections, earlierCursor: cursor + restored.length },
              lastActiveAt: new Date(now).toISOString(),
              status: 'active',
            };
            return {
              sessions: { ...state.sessions, [agentId]: next },
              archived: { ...state.archived, [agentId]: remaining },
            };
          }

          // Demo fallback: fixture seeds (mock data path only — the pill never
          // offers this branch when the v2 API is enabled).
          const { seeds, chunk: chunkSize } = historyForAgent(agentId);
          if (seeds.length === 0) return state;

          const cursor = Number(current.selections.earlierCursor ?? 0);
          const total = seeds.length;
          if (cursor >= total) return state;

          const end = total - cursor;
          const start = Math.max(0, end - chunkSize);
          const chunk = seeds.slice(start, end).map((seed) => ({
            id: `${agentId}-hist-${seed.minutesAgo}`,
            role: seed.role,
            text: seed.text,
            ts: new Date(now - seed.minutesAgo * 60_000).toISOString(),
            source: 'chat' as const,
          }));

          const next: Session = {
            ...current,
            messages: [...chunk, ...current.messages],
            selections: { ...current.selections, earlierCursor: cursor + chunk.length },
            lastActiveAt: new Date(now).toISOString(),
            status: 'active',
          };
          return { sessions: { ...state.sessions, [agentId]: next } };
        }),

      reset: () => set({ sessions: initialSessions(), archived: initialArchived() }),
    }),
    {
      name: 'openrecruiting.sessions.v1',
      // v1 deliberately blanked sessions+archived on write (no persistence).
      // v2 persists both so conversations survive reloads; the rehydrate hook
      // below archives whatever was live so every page load starts fresh and
      // "Show earlier" restores the past.
      version: 2,
      storage: createJSONStorage(() => createThrottledStorage()),
      partialize: (state) => ({
        sessions: state.sessions,
        archived: state.archived,
      }),
      migrate: (persisted, version) => {
        if (version < 2) {
          // v1 payloads only ever contained blank maps — discard them.
          return { sessions: initialSessions(), archived: initialArchived() };
        }
        return persisted as Pick<SessionStoreState, 'sessions' | 'archived'>;
      },
      onRehydrateStorage: () => (state) => {
        state?.archiveAllLiveSessions();
      },
    },
  ),
);
