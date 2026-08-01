import { useArtifactStore, useSessionStore, useTypingStore } from '@/stores';
import type { ArtifactType, Message, StageId, SubAgentId } from '@/types';
import type { StreamEvent } from './mock-stream';

export type SubAgentMockStream = (
  stageId: StageId,
  userInput: string | null,
) => AsyncIterable<StreamEvent>;

export interface RunStreamHooks {
  onStageStart?: () => void;
  onProseToken?: (token: string) => void;
  onSubReveal?: (sub: string) => void;
  onUxReveal?: (component: string, props: Record<string, unknown>) => void;
  onArtifactStart?: (artifactId: string, artifactType: ArtifactType, title: string) => void;
  onArtifactPatch?: (artifactId: string, patch: Record<string, unknown>) => void;
  onArtifactComplete?: (artifactId: string) => void;
  onStageEnd?: (nextStage: StageId) => void;
}

export interface RunStreamOptions extends RunStreamHooks {
  stream: AsyncIterable<StreamEvent>;
}

function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function makeMessage(
  role: 'agent' | 'user',
  text: string,
  mode?: 'text' | 'voice',
  source: 'scripted' | 'chat' = 'scripted',
  chips?: Message['chips'],
  sub?: string,
): Message {
  const msg: Message = {
    id: uuid(),
    role,
    text,
    ts: new Date().toISOString(),
    source,
  };
  if (mode) msg.mode = mode;
  if (chips) msg.chips = chips;
  if (sub) msg.sub = sub;
  return msg;
}

/**
 * Widen a typed per-agent selections object to the store's `Record<string,
 * unknown>` shape WITHOUT an `as unknown as` double-cast. An interface with
 * optional fields is not structurally assignable to a `Record` index
 * signature in TS, so flows previously bridged via `as unknown as`. Rebuilding
 * the object through `Object.fromEntries(Object.entries(...))` is sound: the
 * result is genuinely `Record<string, unknown>`.
 */
export function widenSelections<T extends object>(value: T): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value));
}

/**
 * Drive a mock stream end-to-end. Callers pass hooks that map events onto their store layer
 * (typically sessionStore.appendMessage, artifactStore.openArtifact, etc).
 */
export async function runStream(options: RunStreamOptions): Promise<void> {
  for await (const ev of options.stream) {
    switch (ev.type) {
      case 'stage_start':
        options.onStageStart?.();
        break;
      case 'prose_token':
        options.onProseToken?.(ev.token);
        break;
      case 'sub_reveal':
        options.onSubReveal?.(ev.sub);
        break;
      case 'ux_reveal':
        options.onUxReveal?.(ev.component, ev.props);
        break;
      case 'artifact_start':
        options.onArtifactStart?.(ev.artifactId, ev.artifactType, ev.title);
        break;
      case 'artifact_patch':
        options.onArtifactPatch?.(ev.artifactId, ev.patch);
        break;
      case 'artifact_complete':
        options.onArtifactComplete?.(ev.artifactId);
        break;
      case 'stage_end':
        options.onStageEnd?.(ev.nextStage);
        break;
    }
  }
}

// ---------- Per-session run cancellation ----------
//
// Long-running sub-agent animations (sourcing channel scans, brain Cortex
// trails, debrief analysis) are driven by `await delay()` chains that patch
// the artifact/session store. When the user navigates away mid-flow the canvas
// unmounts, but the in-flight chain keeps firing store mutations against a
// torn-down session — racing Next's RSC fetch and logging errors.
//
// Each sub-agent (= tab/session) owns at most one live `AbortController`.
// Starting a new run for an agent aborts the prior one (so a fast remount or a
// second mounted instance can never share a token — the older run bails on its
// next `signal.aborted` check). The canvas unmount-cancel effect calls
// `cancelRun` to abort whatever is in flight.
const runControllers = new Map<SubAgentId, AbortController>();

export function beginRun(agentId: SubAgentId): AbortSignal {
  runControllers.get(agentId)?.abort();
  const controller = new AbortController();
  runControllers.set(agentId, controller);
  return controller.signal;
}

export function cancelRun(agentId: SubAgentId): void {
  const controller = runControllers.get(agentId);
  if (!controller) return;
  controller.abort();
  runControllers.delete(agentId);
}

/**
 * Sleep that resolves early (rejecting nothing, just returning) when the run is
 * aborted, so callers can `await abortableDelay(...)` then `if (signal.aborted)
 * return;` to bail before mutating any store.
 */
export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

// ---------- Shared stage-stream driver ----------
//
// The three scripted sub-agents (sourcing, brain, debrief) all consume a mock
// stream the same way: accumulate prose tokens, track the latest sub-reveal,
// open/patch/complete artifacts on the artifact store, and on stage_end append
// the composed agent bubble + advance the stage + stop the typing pill. This
// driver centralizes that loop so each flow only supplies the per-agent bits
// (chips, whether to emit the message) via small callbacks.

export interface DriveStageStreamOptions {
  /** Chips to attach to the composed agent bubble (per stage). */
  chipsFor?: (stageId: StageId) => Message['chips'] | undefined;
  /** Map a ux_reveal event onto the flow (debrief result chips, etc). */
  onUxReveal?: (component: string, props: Record<string, unknown>) => void;
  /**
   * When provided, the driver stops mutating the store the moment the signal
   * aborts (canvas unmounted / new run kicked) — no late artifact patches or
   * agent bubbles against a torn-down session.
   */
  signal?: AbortSignal;
}

export async function driveStageStream(
  agentId: SubAgentId,
  stageId: StageId,
  stream: AsyncIterable<StreamEvent>,
  options: DriveStageStreamOptions = {},
): Promise<void> {
  const { signal } = options;
  const artifacts = useArtifactStore.getState();
  useTypingStore.getState().start(agentId);

  let agentMsgText = '';
  let latestSub: string | null = null;

  try {
    await runStream({
      stream,
      onProseToken: (token) => {
        agentMsgText += token;
      },
      onSubReveal: (sub) => {
        latestSub = sub;
      },
      onUxReveal: (component, props) => {
        if (signal?.aborted) return;
        options.onUxReveal?.(component, props);
      },
      onArtifactStart: (id, type, title) => {
        if (signal?.aborted) return;
        artifacts.openArtifact({ id, type, title, initialData: {} });
        useSessionStore.getState().setArtifactId(agentId, id);
      },
      onArtifactPatch: (id, patch) => {
        if (signal?.aborted) return;
        useArtifactStore.getState().patchArtifact(id, patch);
      },
      onArtifactComplete: (id) => {
        if (signal?.aborted) return;
        useArtifactStore.getState().completeArtifact(id);
      },
      onStageEnd: (nextStage) => {
        if (signal?.aborted) {
          useTypingStore.getState().stop(agentId);
          return;
        }
        if (agentMsgText.trim()) {
          const chips = options.chipsFor?.(stageId);
          useSessionStore
            .getState()
            .appendMessage(
              agentId,
              makeMessage(
                'agent',
                agentMsgText.trim(),
                undefined,
                'scripted',
                chips,
                latestSub ?? undefined,
              ),
            );
          agentMsgText = '';
          latestSub = null;
        }
        if (nextStage !== stageId) {
          useSessionStore.getState().setStage(agentId, nextStage);
        }
        useTypingStore.getState().stop(agentId);
      },
    });
  } catch (err) {
    useTypingStore.getState().stop(agentId);
    throw err;
  }
}
