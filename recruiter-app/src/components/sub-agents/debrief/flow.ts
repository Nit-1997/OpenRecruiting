import type { AgentChip } from '@/components/shell/primitives/agent-msg';
import type { CandidateFixture } from '@/fixtures/candidates';
import { getCandidatesByIds } from '@/fixtures/candidates';
import type { DebriefPacket } from '@/fixtures/debrief-packets';
import type { RoleFixture } from '@/fixtures/roles';
import {
  DebriefApiError,
  DebriefGenerationError,
  generateDebrief,
  getConversation,
  getPacket,
  pollPacket,
} from '@/lib/debrief/api';
import { executeDebriefAction, openDebriefChat } from '@/lib/debrief/chat';
import { isV2ApiEnabled } from '@/lib/env';
import { beginRun, driveStageStream, makeMessage } from '@/lib/sub-agent-runner';
import { useArtifactStore, useSessionStore } from '@/stores';
import type { Message, ProposedAction } from '@/types/sub-agent';
import {
  DEBRIEF_ARTIFACT_ID,
  type DebriefContext,
  type DebriefStageId,
  debriefMockStream,
} from './mock-stream';

// In-flight generate+poll promise, keyed nowhere (single active debrief
// session at a time). `completeAnalyzing` awaits this so the artifact opens
// with the REAL packet the moment generation finishes — overlapping the
// analyzing animation rather than blocking it. Cleared on reset/cancel.
//
// Resolves to BOTH the ROW id from the `/generate` response (`packetId`) AND the
// polled packet body. The ROW id is what `/save` and `/packets/{id}` key on — it
// is NOT the same as the packet body's `.id` (stamped by the cortex skill), so
// we MUST thread the row id explicitly into selections rather than reading
// `packet.id`.
interface DebriefGeneration {
  packetId: string;
  packet: DebriefPacket;
}
let generationInFlight: Promise<DebriefGeneration> | null = null;

/**
 * Resolve display metadata (name/avatar/color) for the selected candidate ids.
 * Under v2 the picker stashed the fetched + mapped candidates in
 * selections.candidatePool; fall back to the fixture for the mock path.
 */
export function resolveCandidateMeta(
  roleId: string,
  selected: string[],
  pool: CandidateFixture[] | undefined,
): CandidateFixture[] {
  if (pool && pool.length > 0) {
    const byId = new Map(pool.map((c) => [c.id, c] as const));
    return selected.map((id) => byId.get(id)).filter((c): c is CandidateFixture => !!c);
  }
  return getCandidatesByIds(roleId, selected);
}

function ensureSession(initialStage: DebriefStageId = 'role_pick'): void {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.debrief) sessions.startSession('debrief', initialStage);
}

export async function runDebriefStage(
  stageId: DebriefStageId,
  ctx: DebriefContext = {},
  options: { speed?: number } = {},
): Promise<void> {
  ensureSession(stageId);
  useSessionStore.getState().setStage('debrief', stageId);

  // Per-session abort handle: if the canvas unmounts mid-run (navigate away),
  // the driver stops mutating the torn-down session.
  const signal = beginRun('debrief');

  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  const stream = debriefMockStream(stageId, JSON.stringify(ctx), streamOptions);

  // The result stage's mock stream emits a `ux_reveal` (`debrief_result_chips`)
  // BEFORE its `stage_end`. Capture those chips here and feed them back through
  // `chipsFor` so the composed agent bubble carries them live — previously the
  // call dropped `onUxReveal`/`chipsFor`, silently discarding the result chips
  // ("Push back on a score" / "Re-weigh a dimension").
  let revealedChips: AgentChip[] | undefined;

  // The driver flips the "thinking" pill on (so the canvas hides the stage UX
  // until the agent bubble lands), drains the stream onto the store, then on
  // stage_end appends the composed bubble, advances the stage, and clears the
  // pill in the same commit (no flash between bubble and picker).
  await driveStageStream('debrief', stageId, stream, {
    signal,
    onUxReveal: (component, props) => {
      if (component === 'debrief_result_chips' && Array.isArray(props.chips)) {
        revealedChips = props.chips as AgentChip[];
      }
    },
    chipsFor: () => revealedChips,
  });
}

/**
 * Handle a recruiter-initiated chat turn over the generated packet (spec §7).
 *
 * Appends the user message, then opens the SSE chat (`openDebriefChat`) and
 * streams the agent reply into a single live agent `Message` (patched per
 * token via the store's `updateMessage`). A terminal `proposed_action` lands as
 * a confirm-card `Message` (Confirm / Dismiss, executed via the `/actions`
 * endpoint). An `error` event lands as a static agent message. If the packet id
 * hasn't been threaded yet (no real backend packet), we degrade gracefully
 * without calling the API.
 */
export async function submitDebriefMessage(message: string): Promise<void> {
  const trimmed = message.trim();
  if (!trimmed) return;

  const sessions = useSessionStore.getState();
  ensureSession('role_pick');
  sessions.appendMessage('debrief', makeMessage('user', trimmed, 'text', 'chat'));

  const packetId = sessions.sessions.debrief?.selections.packetId as string | undefined;
  if (!packetId) {
    useSessionStore
      .getState()
      .appendMessage(
        'debrief',
        makeMessage(
          'agent',
          'I need a generated debrief packet before we can talk it through — finish the comparison first.',
          'text',
          'chat',
        ),
      );
    return;
  }

  const signal = beginRun('debrief');

  // The agent bubble is created LAZILY on the first token — a turn that ends
  // in a bare tool call (a proposal with no prose) must not leave an empty
  // bubble in the transcript.
  let agentMsg: Message | null = null;
  let agentText = '';

  await openDebriefChat(packetId, trimmed, {
    signal,
    onToken: (token) => {
      if (signal.aborted) return;
      agentText += token;
      if (!agentMsg) {
        agentMsg = makeMessage('agent', agentText, 'text', 'chat');
        useSessionStore.getState().appendMessage('debrief', agentMsg);
        return;
      }
      useSessionStore.getState().updateMessage('debrief', agentMsg.id, { text: agentText });
    },
    onProposed: (proposed) => {
      if (signal.aborted) return;
      // `propose_new_debrief` is a workflow handoff, not a write — no confirm
      // card. The picker IS the confirmation surface (and the old packet stays
      // reachable via its transcript card), so route straight back into it.
      if (proposed.kind === 'propose_new_debrief') {
        const scope = proposed.input?.scope === 'same_role' ? 'same_role' : 'different_role';
        void startNewDebrief(scope);
        return;
      }
      // Scheduling is also a UI intent: queue every named candidate's pipeline
      // packet (the role section's drawer, ScheduleModal included) — dates,
      // times and timezones are picked there, never negotiated in chat.
      if (proposed.kind === 'propose_open_scheduler') {
        openSchedulerForCandidates(proposed.input);
        return;
      }
      // Quick replies: option enumerations render as tappable pills on the
      // agent's bubble (tapping one sends it as the next user message via the
      // transcript's onChip), never as a prose list.
      if (proposed.kind === 'propose_quick_replies') {
        const raw = Array.isArray(proposed.input?.options)
          ? (proposed.input.options as unknown[])
          : [];
        const chips = raw
          .filter((o): o is string => typeof o === 'string' && o.trim().length > 0)
          .slice(0, 6)
          .map((label) => ({ label, value: label }));
        if (chips.length === 0) return;
        if (agentMsg) {
          useSessionStore.getState().updateMessage('debrief', agentMsg.id, { chips });
        } else {
          // Defensive: the model skipped its one-sentence preamble — give the
          // pills a bubble to live on.
          agentMsg = makeMessage('agent', 'Here’s what I can help with:', 'text', 'chat', chips);
          useSessionStore.getState().appendMessage('debrief', agentMsg);
        }
        return;
      }
      const card = makeMessage('agent', '', 'text', 'chat');
      card.confirmAction = normalizeProposed(proposed);
      card.confirmStatus = 'pending';
      useSessionStore.getState().appendMessage('debrief', card);
    },
    onError: (errText) => {
      if (signal.aborted) return;
      useSessionStore
        .getState()
        .appendMessage('debrief', makeMessage('agent', errText, 'text', 'chat'));
    },
  });
}

/**
 * Hand the recruiter back to the debrief picker workflow (the chat agent's
 * `propose_new_debrief` UI intent — "debrief another round/role"). Non-
 * destructive: the transcript and the current packet's reference card stay;
 * only the candidate selection resets and the stage machine re-enters the
 * picker. `same_role` jumps straight to the candidate picker for the packet's
 * role; anything else returns to the role picker.
 */
export async function startNewDebrief(
  scope: 'same_role' | 'different_role',
  options: { speed?: number } = {},
): Promise<void> {
  ensureSession('role_pick');
  const sessions = useSessionStore.getState();
  const current = sessions.sessions.debrief;
  const roleId = current?.selections.roleId as string | undefined;
  const roleTitle = (current?.selections.roleTitle as string | undefined) ?? 'this role';
  sessions.updateSelections('debrief', { selectedCandidates: [] });

  if (scope === 'same_role' && roleId) {
    await runDebriefStage('candidate_pick', { roleTitle }, options);
    return;
  }
  await runDebriefStage('role_pick', {}, options);
}

/** The scheduling work-queue stored on `selections.schedulerQueue`: the
 *  candidates to schedule, in order, and which one the drawer currently shows. */
export interface SchedulerQueueState {
  candidateIds: string[];
  index: number;
}

/** The workspace artifact hosting the scheduling queue. A fixed id — one
 *  scheduler at a time, replaced wholesale on every new ask. */
export const SCHEDULER_ARTIFACT_ID = 'debrief-scheduler';

/**
 * Open the debrief scheduling queue (the chat agent's `propose_open_scheduler`
 * UI intent). Each candidate gets the role section's PacketDrawer — schedule
 * modal, add-round, request-feedback and all — rendered as the workspace
 * `candidate_packet` artifact, so it occupies the EXACT panel the debrief
 * packet does (the chat column never reflows) and replaces the packet there
 * while scheduling; finishing or closing restores the packet. A "Next" control
 * advances through multi-candidate asks one drawer at a time. The drawer
 * self-fetches by (roleId, candidateId), so this only stores the queue.
 */
export function openSchedulerForCandidates(input: Record<string, unknown>): void {
  ensureSession('role_pick');
  const raw = Array.isArray(input.candidate_ids) ? (input.candidate_ids as string[]) : [];
  const candidateIds = [...new Set(raw.filter((id) => typeof id === 'string' && id))];
  const selections = useSessionStore.getState().sessions.debrief?.selections ?? {};
  const roleId = selections.roleId as string | undefined;
  const roleTitle = (selections.roleTitle as string | undefined) ?? 'this role';
  if (candidateIds.length === 0 || !roleId) {
    useSessionStore
      .getState()
      .appendMessage(
        'debrief',
        makeMessage(
          'agent',
          'I couldn’t open the scheduler — tell me which candidate to schedule for.',
          'text',
          'chat',
        ),
      );
    return;
  }
  useSessionStore.getState().updateSelections('debrief', {
    schedulerQueue: { candidateIds, index: 0 } satisfies SchedulerQueueState,
  });
  useArtifactStore.getState().openArtifact({
    id: SCHEDULER_ARTIFACT_ID,
    type: 'candidate_packet',
    title: `Schedule · ${roleTitle}`,
    initialData: { roleId },
  });
  useArtifactStore.getState().completeArtifact(SCHEDULER_ARTIFACT_ID);
  useSessionStore.getState().setArtifactId('debrief', SCHEDULER_ARTIFACT_ID);
}

/** Tear down the scheduler artifact and point the workspace back at the
 *  debrief packet (when it's still in the store — else the column just empties
 *  and the packet's transcript card remains the way back). */
function teardownSchedulerArtifact(): void {
  const packetArtifactId = useSessionStore.getState().sessions.debrief?.selections
    .packetArtifactId as string | undefined;
  const restored =
    packetArtifactId && useArtifactStore.getState().artifacts[packetArtifactId]
      ? packetArtifactId
      : null;
  useSessionStore.getState().setArtifactId('debrief', restored);
  useArtifactStore.getState().removeArtifact(SCHEDULER_ARTIFACT_ID);
}

/** Advance the scheduling queue to the next candidate; finishing on the last. */
export function advanceSchedulerQueue(): void {
  const queue = useSessionStore.getState().sessions.debrief?.selections.schedulerQueue as
    | SchedulerQueueState
    | null
    | undefined;
  if (!queue) return;
  if (queue.index + 1 >= queue.candidateIds.length) {
    finishSchedulerQueue();
    return;
  }
  useSessionStore.getState().updateSelections('debrief', {
    schedulerQueue: { ...queue, index: queue.index + 1 },
  });
}

/** Complete the scheduling queue: tear the scheduler down, bring the debrief
 *  packet back into the workspace, and say so in chat. */
export function finishSchedulerQueue(): void {
  useSessionStore.getState().updateSelections('debrief', { schedulerQueue: null });
  teardownSchedulerArtifact();
  useSessionStore
    .getState()
    .appendMessage(
      'debrief',
      makeMessage(
        'agent',
        'Scheduling done — the debrief packet is back on the right.',
        'text',
        'chat',
      ),
    );
}

/** Close the scheduler outright (the drawer's own X), abandoning any remaining
 *  candidates in the queue and restoring the packet. */
export function closeScheduler(): void {
  useSessionStore.getState().updateSelections('debrief', { schedulerQueue: null });
  teardownSchedulerArtifact();
}

/** Normalize the SSE `proposed_action` payload into the strict `ProposedAction`
 *  shape the confirm card reads. The `input` always carries
 *  `candidate_ids`/`summary`/`rationale`; default them defensively so a thin
 *  payload still renders a card rather than crashing. */
function normalizeProposed(proposed: {
  kind: string;
  input: Record<string, unknown>;
}): ProposedAction {
  const input = proposed.input ?? {};
  return {
    kind: proposed.kind,
    input: {
      candidate_ids: Array.isArray(input.candidate_ids) ? (input.candidate_ids as string[]) : [],
      summary: typeof input.summary === 'string' ? input.summary : 'Suggested action',
      rationale: typeof input.rationale === 'string' ? input.rationale : '',
      ...input,
    },
  };
}

// Propose tool name → bare action kind (e.g. `propose_add_round` → `add_round`).
const PROPOSE_PREFIX = 'propose_';

/** Bare action kinds whose execution mutates the packet body → refetch after.
 *  (schedule_round is retired — scheduling opens the packet drawer instead.) */
const PACKET_CHANGING_KINDS = new Set(['add_round', 'record_decision', 'advance_reject']);

function bareKind(kind: string): string {
  return kind.startsWith(PROPOSE_PREFIX) ? kind.slice(PROPOSE_PREFIX.length) : kind;
}

/** Friendly, status-keyed copy for a failed execute — never the raw server text. */
function executeErrorText(err: unknown): string {
  if (err instanceof DebriefApiError) {
    if (err.status === 409)
      return 'The packet changed since I suggested that — refresh and try again.';
    if (err.status === 404) return 'I couldn’t find that packet anymore.';
    if (err.status === 400)
      return 'I couldn’t apply that — the suggestion no longer fits the packet.';
  }
  return 'I couldn’t apply that just now. Please try again.';
}

function debriefMessage(messageId: string): Message | undefined {
  return useSessionStore.getState().sessions.debrief?.messages.find((m) => m.id === messageId);
}

/**
 * Confirm a proposed action (spec §5/§7). Marks the card `executing`, POSTs the
 * SAME `{ kind, input }` via `executeDebriefAction`, then on success marks the
 * card `done`, appends a result turn, and — for packet-changing kinds — refetches
 * the packet and patches the comparative artifact so the view updates. On failure
 * marks the card `failed` and appends a friendly, status-specific error turn.
 * Idempotent at the card level: a settled card is never re-executed.
 */
export async function confirmDebriefAction(messageId: string): Promise<void> {
  const sessions = useSessionStore.getState();
  const msg = debriefMessage(messageId);
  const action = msg?.confirmAction;
  if (!action || msg?.confirmStatus !== 'pending') return;

  const packetId = sessions.sessions.debrief?.selections.packetId as string | undefined;
  if (!packetId) {
    useSessionStore.getState().updateMessage('debrief', messageId, { confirmStatus: 'failed' });
    useSessionStore
      .getState()
      .appendMessage(
        'debrief',
        makeMessage('agent', 'I couldn’t apply that — no active debrief packet.', 'text', 'chat'),
      );
    return;
  }

  useSessionStore.getState().updateMessage('debrief', messageId, { confirmStatus: 'executing' });

  try {
    await executeDebriefAction(packetId, action);
  } catch (err) {
    useSessionStore.getState().updateMessage('debrief', messageId, { confirmStatus: 'failed' });
    useSessionStore
      .getState()
      .appendMessage('debrief', makeMessage('agent', executeErrorText(err), 'text', 'chat'));
    return;
  }

  useSessionStore.getState().updateMessage('debrief', messageId, { confirmStatus: 'done' });
  useSessionStore
    .getState()
    .appendMessage(
      'debrief',
      makeMessage('agent', `Done — ${action.input.summary}.`, 'text', 'chat'),
    );

  // Packet-changing actions update the artifact view; request_feedback does not.
  // Patch whichever artifact currently renders the ACTIVE packet (a reopened
  // packet lives under `debrief-packet-<id>`, not the generation-time id).
  if (PACKET_CHANGING_KINDS.has(bareKind(action.kind))) {
    const activeArtifactId =
      (useSessionStore.getState().sessions.debrief?.selections.packetArtifactId as
        | string
        | undefined) ?? DEBRIEF_ARTIFACT_ID;
    try {
      const packet = await getPacket(packetId);
      useArtifactStore.getState().patchArtifact(activeArtifactId, { packet });
    } catch {
      // The action committed; a refetch hiccup is non-fatal — leave the prior
      // packet rendered rather than surfacing a scary error on a successful write.
    }
  }
}

/** Dismiss a proposed action: mark the card dismissed and append a short turn.
 *  No API call. Idempotent — a settled card is left untouched. */
export function dismissDebriefAction(messageId: string): void {
  const msg = debriefMessage(messageId);
  if (!msg?.confirmAction || msg.confirmStatus !== 'pending') return;
  useSessionStore.getState().updateMessage('debrief', messageId, { confirmStatus: 'dismissed' });
  useSessionStore
    .getState()
    .appendMessage('debrief', makeMessage('agent', 'Dismissed.', 'text', 'chat'));
}

export async function pickDebriefRole(role: RoleFixture): Promise<void> {
  const sessions = useSessionStore.getState();
  ensureSession('role_pick');
  sessions.appendMessage('debrief', makeMessage('user', `Let’s debrief ${role.title}.`));
  sessions.updateSelections('debrief', {
    roleId: role.id,
    roleTitle: role.title,
    selectedCandidates: [],
  });
  sessions.setStage('debrief', 'candidate_pick');
  await runDebriefStage('candidate_pick', { roleTitle: role.title });
}

/**
 * Atomic initializer for deep-link entry (e.g. /debrief?role=<id>).
 *
 * Skips the role_pick stage entirely: starts the session directly at
 * candidate_pick with the user's "Let's debrief <role>" message pre-seeded
 * and the role stored in selections. Idempotent — if the current session
 * already has this role picked, it's a no-op so React strict mode's
 * double-fire of the canvas effect doesn't produce duplicate bubbles or an
 * unwanted "Which role do you want to debrief?" greeting.
 */
export async function initDebriefFromRole(role: RoleFixture): Promise<void> {
  const sessions = useSessionStore.getState();
  const existing = sessions.sessions.debrief;
  const userText = `Let’s debrief ${role.title}.`;

  const alreadyInitialized =
    !!existing &&
    (existing.selections.roleId as string | undefined) === role.id &&
    existing.messages.some((m) => m.role === 'user' && m.text === userText);
  if (alreadyInitialized) return;

  if (existing) {
    sessions.endSession('debrief');
    useArtifactStore.getState().removeArtifact(DEBRIEF_ARTIFACT_ID);
  }

  sessions.startSession('debrief', 'candidate_pick');
  sessions.appendMessage('debrief', makeMessage('user', userText));
  sessions.updateSelections('debrief', {
    roleId: role.id,
    roleTitle: role.title,
    selectedCandidates: [],
  });
  await runDebriefStage('candidate_pick', { roleTitle: role.title });
}

export function toggleCandidate(candidateId: string): void {
  const sessions = useSessionStore.getState();
  const current = sessions.sessions.debrief;
  if (!current) return;
  const existing = (current.selections.selectedCandidates as string[] | undefined) ?? [];
  const next = existing.includes(candidateId)
    ? existing.filter((c) => c !== candidateId)
    : [...existing, candidateId];
  sessions.updateSelections('debrief', { selectedCandidates: next });
}

export function cancelCandidatePick(): void {
  const sessions = useSessionStore.getState();
  sessions.updateSelections('debrief', { selectedCandidates: [] });
  sessions.setStage('debrief', 'role_pick');
}

export async function confirmCandidatePick(options: { speed?: number } = {}): Promise<void> {
  const sessions = useSessionStore.getState();
  const current = sessions.sessions.debrief;
  if (!current) return;
  const roleId = (current.selections.roleId as string | undefined) ?? '';
  const roleTitle = (current.selections.roleTitle as string | undefined) ?? 'this role';
  const selected = (current.selections.selectedCandidates as string[] | undefined) ?? [];
  if (selected.length < 2) return;
  const pool = current.selections.candidatePool as CandidateFixture[] | undefined;
  const candidates = resolveCandidateMeta(roleId, selected, pool);
  const candidateNames = candidates.map((c) => c.name.split(' ')[0] ?? c.name);

  sessions.appendMessage('debrief', makeMessage('user', `Compare ${candidateNames.join(', ')}.`));
  sessions.setStage('debrief', 'analyzing');

  // Kick off real generation NOW so it overlaps the analyzing animation. Under
  // v2 only — the mock path renders a synthesized packet at artifact time.
  if (isV2ApiEnabled() && roleId) {
    sessions.updateSelections('debrief', { generationError: null });
    // Capture the ROW id from the generate response and thread it through —
    // `/save` + `/packets/{id}` key on it, NOT the polled packet body's `.id`.
    generationInFlight = generateDebrief(roleId, selected).then(async (res) => ({
      packetId: res.packet_id,
      packet: await pollPacket(res.packet_id),
    }));
    // Swallow rejections here so an unhandled rejection never fires before
    // completeAnalyzing awaits the same promise (which surfaces the error).
    generationInFlight.catch(() => {});
  }

  await runDebriefStage('analyzing', { roleTitle, candidateNames }, options);
}

export async function completeAnalyzing(options: { speed?: number } = {}): Promise<void> {
  const sessions = useSessionStore.getState();
  const current = sessions.sessions.debrief;
  if (!current) return;
  const roleId = (current.selections.roleId as string | undefined) ?? '';
  const roleTitle = (current.selections.roleTitle as string | undefined) ?? 'this role';
  const selected = (current.selections.selectedCandidates as string[] | undefined) ?? [];
  const pool = current.selections.candidatePool as CandidateFixture[] | undefined;
  const candidates = resolveCandidateMeta(roleId, selected, pool);
  const candidateNames = candidates.map((c) => c.name.split(' ')[0] ?? c.name);

  // Under v2: await the real packet that confirmCandidatePick started. On
  // failure/timeout surface the error (no silent swallow) and stay put.
  let packet: DebriefPacket | null = null;
  let packetRowId: string | null = null;
  if (isV2ApiEnabled() && roleId) {
    try {
      const generation = generationInFlight ? await generationInFlight : null;
      packet = generation?.packet ?? null;
      packetRowId = generation?.packetId ?? null;
    } catch (err) {
      const message =
        err instanceof DebriefGenerationError || err instanceof Error
          ? err.message
          : 'Debrief generation failed.';
      useSessionStore.getState().updateSelections('debrief', { generationError: message });
      useSessionStore.getState().setStage('debrief', 'failed');
      generationInFlight = null;
      return;
    }
    generationInFlight = null;
  }

  // Thread the ROW id (from the `/generate` response) into selections so the
  // result stage's Save button + print/download link commit the SAME packet the
  // backend keys on — NOT the packet body's `.id` (which the cortex skill
  // stamps and is not the `debrief_packets` row id). Only present on the v2
  // path (the mock path has no real backend packet).
  if (packetRowId) {
    sessions.updateSelections('debrief', {
      packetId: packetRowId,
      packetArtifactId: DEBRIEF_ARTIFACT_ID,
    });
  }

  // Seed the comparative artifact. When we have a real packet, carry it in
  // initialData so the renderer draws the fetched packet directly. The mock
  // path carries only the id pointers (the artifact synthesizes from them).
  useArtifactStore.getState().openArtifact({
    id: DEBRIEF_ARTIFACT_ID,
    type: 'comparative',
    title: `Debrief · ${roleTitle}`,
    initialData: {
      roleId,
      roleTitle,
      candidateIds: selected,
      ...(packet ? { packet } : {}),
    },
  });
  useSessionStore.getState().setArtifactId('debrief', DEBRIEF_ARTIFACT_ID);

  sessions.setStage('debrief', 'result');
  await runDebriefStage('result', { roleTitle, candidateNames }, options);

  // Leave a durable packet-reference card in the transcript so the packet can
  // be reopened after the workspace panel is closed — or from restored history
  // in a later session (the card refetches by row id when the artifact is gone).
  const pill = makeMessage('agent', `Debrief packet ready — ${roleTitle}`, 'text', 'chat');
  pill.packetRef = { packetId: packetRowId, roleTitle };
  useSessionStore.getState().appendMessage('debrief', pill);
}

/**
 * Reopen a debrief packet from its transcript reference card — and RESUME it.
 *
 * Three paths, cheapest first:
 * 1. The card points at the live session's packet (or the mock packet) and the
 *    artifact is still in the store → just re-point the session at it.
 * 2. The card points at an older real packet → refetch it by row id, open it
 *    under its own `debrief-packet-<id>` artifact (never clobbering the live
 *    one), make it the ACTIVE chat target (selections.packetId + result stage so
 *    the composer routes to the conversation agent), and hydrate its persisted
 *    server-side conversation into the transcript (once per packet, deduped).
 * 3. A mock-path card whose artifact was torn down → nothing to refetch; say so.
 */
export async function reopenDebriefPacket(ref: {
  packetId: string | null;
  roleTitle: string;
}): Promise<void> {
  ensureSession('role_pick');
  const sessions = useSessionStore.getState();
  const livePacketId = sessions.sessions.debrief?.selections.packetId as string | undefined;

  const isLivePacket = ref.packetId ? ref.packetId === livePacketId : true;
  if (isLivePacket && ref.packetId) {
    const liveArtifactId =
      (sessions.sessions.debrief?.selections.packetArtifactId as string | undefined) ??
      DEBRIEF_ARTIFACT_ID;
    if (useArtifactStore.getState().artifacts[liveArtifactId]) {
      sessions.setArtifactId('debrief', liveArtifactId);
      return;
    }
    // Live id but the artifact was torn down (e.g. reload) — fall through to the
    // refetch path below, which reopens and re-activates it.
  } else if (isLivePacket && useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID]) {
    sessions.setArtifactId('debrief', DEBRIEF_ARTIFACT_ID);
    return;
  }

  if (!ref.packetId) {
    sessions.appendMessage(
      'debrief',
      makeMessage(
        'agent',
        'That packet isn’t available anymore — run a fresh comparison to view it.',
        'text',
        'chat',
      ),
    );
    return;
  }

  const artifactId = `debrief-packet-${ref.packetId}`;
  let fetchedPacket: DebriefPacket | null = null;
  if (!useArtifactStore.getState().artifacts[artifactId]) {
    try {
      fetchedPacket = await getPacket(ref.packetId);
      useArtifactStore.getState().openArtifact({
        id: artifactId,
        type: 'comparative',
        title: `Debrief · ${ref.roleTitle}`,
        initialData: { roleTitle: ref.roleTitle, packet: fetchedPacket },
      });
      useArtifactStore.getState().completeArtifact(artifactId);
    } catch {
      useSessionStore
        .getState()
        .appendMessage(
          'debrief',
          makeMessage(
            'agent',
            'I couldn’t reopen that packet just now. Please try again.',
            'text',
            'chat',
          ),
        );
      return;
    }
  }

  // Resume the packet: point the workspace AND the conversation agent at it.
  // The `result` stage is what routes composer input to the SSE chat.
  useSessionStore.getState().setArtifactId('debrief', artifactId);
  useSessionStore.getState().updateSelections('debrief', {
    packetId: ref.packetId,
    packetArtifactId: artifactId,
  });
  useSessionStore.getState().setStage('debrief', 'result');

  await hydrateConversation(ref.packetId, ref.roleTitle, fetchedPacket?.generated_at);
}

/**
 * Pull the packet's persisted server-side conversation into the transcript —
 * once per packet per session (`selections.hydratedConversationFor`). Turns are
 * deduped against messages already on screen by `role:text` (covers both the
 * stable `conv-*` ids of a prior hydration AND locally-restored history whose
 * ids differ), so "Show earlier" + hydration never double-print a turn.
 * Best-effort: a fetch failure just skips hydration — the chat still works.
 */
async function hydrateConversation(
  packetId: string,
  roleTitle: string,
  fallbackTs?: string,
): Promise<void> {
  const current = useSessionStore.getState().sessions.debrief;
  if (!current) return;
  if ((current.selections.hydratedConversationFor as string | undefined) === packetId) return;

  let turns: Awaited<ReturnType<typeof getConversation>>;
  try {
    turns = await getConversation(packetId);
  } catch {
    return;
  }
  useSessionStore.getState().updateSelections('debrief', {
    hydratedConversationFor: packetId,
  });

  const session = useSessionStore.getState().sessions.debrief;
  if (!session) return;
  const seen = new Set(session.messages.map((m) => `${m.role}:${m.text}`));
  const restored: Message[] = [];
  for (const turn of turns) {
    const text = (turn.text ?? '').trim();
    if (!text) continue; // propose-only turns have no prose; the card isn't replayable
    const role = turn.role === 'user' ? 'user' : 'agent';
    if (seen.has(`${role}:${text}`)) continue;
    restored.push({
      id: `conv-${packetId}-${turn.idx ?? restored.length}`,
      role,
      text,
      ts: turn.ts ?? fallbackTs ?? new Date().toISOString(),
      source: 'chat',
    });
  }
  if (restored.length === 0) return;

  const announce = makeMessage(
    'agent',
    `Picking up the ${roleTitle} debrief — restored ${restored.length} earlier message${
      restored.length === 1 ? '' : 's'
    } from this packet's conversation.`,
    'text',
    'chat',
  );
  for (const msg of restored) {
    useSessionStore.getState().appendMessage('debrief', msg);
  }
  useSessionStore.getState().appendMessage('debrief', announce);
}

/**
 * Return to the candidate picker after a generation failure. Selections
 * (role + chosen candidates + fetched pool) are preserved so the user can
 * adjust and retry; the error is cleared and the in-flight handle is dropped.
 */
export function retryFromFailure(): void {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.debrief) return;
  generationInFlight = null;
  sessions.updateSelections('debrief', { generationError: null });
  sessions.setStage('debrief', 'candidate_pick');
}

export function resetDebrief(): void {
  const sessions = useSessionStore.getState();
  sessions.endSession('debrief');
  useArtifactStore.getState().removeArtifact(DEBRIEF_ARTIFACT_ID);
  generationInFlight = null;
}
