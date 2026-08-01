import type { BrainCanvasArtifactData } from '@/components/artifacts/brain-canvas';
import type { CortexAnalysisData } from '@/components/artifacts/cortex-analysis';
import type { CortexInsightArtifactData } from '@/components/artifacts/cortex-insight';
import {
  BRAIN_DEFAULT_RANGE,
  BRAIN_LINKS,
  BRAIN_NODES,
  BRAIN_STORIES,
  type BrainTimeRangeId,
  findBrainNode,
  findBrainStory,
} from '@/fixtures/brain';
import {
  CORTEX_ANALYSIS_ARTIFACT_ID,
  CORTEX_INSIGHT_ARTIFACT_ID,
  CORTEX_INSIGHTS,
  CORTEX_MESSAGE_GAP_MS,
  CORTEX_TRAIL_STAGGER_MS,
  type CortexInsightKind,
  detectCortexInsightIntent,
} from '@/fixtures/cortex-insights';
import {
  abortableDelay,
  beginRun,
  driveStageStream,
  makeMessage,
  widenSelections,
} from '@/lib/sub-agent-runner';
import { useArtifactStore, useSessionStore, useTypingStore } from '@/stores';
import type { Message } from '@/types/sub-agent';
import {
  BRAIN_ARTIFACT_ID,
  BRAIN_WEEK_LABEL,
  type BrainStageId,
  brainMockStream,
  detectBrainIntent,
} from './mock-stream';

export interface BrainWorkspaceTab {
  id: string;
  label: string;
  pinned?: boolean;
  kind?: 'brain' | 'analysis';
}

export interface BrainSelections {
  weekLabel?: string;
  timeRangeId?: BrainTimeRangeId;
  mutedStoryIds?: string[];
  focusedNodeId?: string | null;
  highlightedNodeIds?: string[];
  activeStoryId?: string | null;
  workspaceTabs?: BrainWorkspaceTab[];
}

function ensureWorkspaceTab(tab: BrainWorkspaceTab): void {
  const current = getSelections();
  const existing = current.workspaceTabs ?? [];
  if (existing.some((t) => t.id === tab.id)) return;
  updateSelections({ workspaceTabs: [...existing, tab] });
}

function ensureSession(initialStage: BrainStageId = 'brain'): void {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.brain) sessions.startSession('brain', initialStage);
}

function getSelections(): BrainSelections {
  const current = useSessionStore.getState().sessions.brain;
  return (current?.selections as BrainSelections | undefined) ?? {};
}

function updateSelections(partial: Partial<BrainSelections>): void {
  const current = getSelections();
  const merged: BrainSelections = { ...current, ...partial };
  useSessionStore.getState().updateSelections('brain', widenSelections(merged));
}

function getArtifactData(): BrainCanvasArtifactData | null {
  const artifact = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID];
  if (!artifact) return null;
  return artifact.data as BrainCanvasArtifactData;
}

function patchArtifact(patch: Partial<BrainCanvasArtifactData>): void {
  useArtifactStore.getState().patchArtifact(BRAIN_ARTIFACT_ID, patch as Record<string, unknown>);
}

export async function runBrainStage(options: { speed?: number } = {}): Promise<void> {
  ensureSession('brain');
  useSessionStore.getState().setStage('brain', 'brain');

  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  const stream = brainMockStream('brain', null, streamOptions);

  await driveStageStream('brain', 'brain', stream);

  // Seed selections defaults.
  updateSelections({
    weekLabel: BRAIN_WEEK_LABEL,
    timeRangeId: BRAIN_DEFAULT_RANGE,
    mutedStoryIds: [],
    focusedNodeId: null,
    highlightedNodeIds: [],
    activeStoryId: null,
  });
  ensureWorkspaceTab({ id: BRAIN_ARTIFACT_ID, label: 'Brain', pinned: true, kind: 'brain' });
}

export async function rehydrateBrain(): Promise<void> {
  const sessions = useSessionStore.getState();
  const session = sessions.sessions.brain;
  if (!session) return;
  const selections = getSelections();
  const artifacts = useArtifactStore.getState();
  if (artifacts.artifacts[BRAIN_ARTIFACT_ID]) return;

  const data: BrainCanvasArtifactData = {
    weekLabel: selections.weekLabel ?? BRAIN_WEEK_LABEL,
    timeRangeId: selections.timeRangeId ?? BRAIN_DEFAULT_RANGE,
    nodes: BRAIN_NODES,
    links: BRAIN_LINKS,
    stories: BRAIN_STORIES,
    mutedStoryIds: selections.mutedStoryIds ?? [],
    focusedNodeId: selections.focusedNodeId ?? null,
    highlightedNodeIds: selections.highlightedNodeIds ?? [],
    activeStoryId: selections.activeStoryId ?? null,
  };

  artifacts.openArtifact({
    id: BRAIN_ARTIFACT_ID,
    type: 'brain-canvas',
    title: `OpenRecruiting Brain · ${data.weekLabel}`,
    initialData: data,
  });
  artifacts.completeArtifact(BRAIN_ARTIFACT_ID);
  useSessionStore.getState().setArtifactId('brain', BRAIN_ARTIFACT_ID);
  ensureWorkspaceTab({ id: BRAIN_ARTIFACT_ID, label: 'Brain', pinned: true, kind: 'brain' });
}

export function explainStory(storyId: string): void {
  const story = findBrainStory(storyId);
  if (!story) return;
  const sessions = useSessionStore.getState();
  sessions.appendMessage('brain', makeMessage('user', `Explain ${story.title}.`));
  sessions.appendMessage('brain', makeMessage('agent', `${story.title} — ${story.elaboration}`));
  updateSelections({
    activeStoryId: storyId,
    highlightedNodeIds: story.targetIds,
    focusedNodeId: null,
  });
  if (getArtifactData()) {
    patchArtifact({
      activeStoryId: storyId,
      highlightedNodeIds: story.targetIds,
      focusedNodeId: null,
    });
  }
}

export function muteStory(storyId: string): void {
  const story = findBrainStory(storyId);
  if (!story) return;
  const selections = getSelections();
  const current = selections.mutedStoryIds ?? [];
  if (current.includes(storyId)) return;
  const next = [...current, storyId];
  const wasActive = selections.activeStoryId === storyId;
  updateSelections({
    mutedStoryIds: next,
    ...(wasActive ? { activeStoryId: null, highlightedNodeIds: [] } : {}),
  });
  const current2 = getArtifactData();
  if (current2) {
    patchArtifact({
      mutedStoryIds: next,
      ...(wasActive ? { activeStoryId: null, highlightedNodeIds: [] } : {}),
    });
  }
  useSessionStore
    .getState()
    .appendMessage('brain', makeMessage('agent', `Muted "${story.title}". It is hidden for now.`));
}

export function focusNode(nodeId: string): void {
  const node = findBrainNode(nodeId);
  if (!node) return;
  const selections = getSelections();
  const nextFocus = selections.focusedNodeId === nodeId ? null : nodeId;
  /* When focusing a node, light up the 1-hop neighborhood so the
     surrounding context is visually obvious. Clearing focus drops the
     highlight set back to empty.                                          */
  const neighborhood = nextFocus ? computeNeighborhood(nextFocus) : [];
  updateSelections({
    focusedNodeId: nextFocus,
    highlightedNodeIds: neighborhood,
    activeStoryId: null,
  });
  if (getArtifactData()) {
    patchArtifact({
      focusedNodeId: nextFocus,
      highlightedNodeIds: neighborhood,
      activeStoryId: null,
    });
  }
}

function computeNeighborhood(nodeId: string): string[] {
  const ids = new Set<string>([nodeId]);
  for (const link of BRAIN_LINKS) {
    if (link.source === nodeId) ids.add(link.target);
    if (link.target === nodeId) ids.add(link.source);
  }
  return Array.from(ids);
}

/* Highlight every node whose label or meta matches the search query
   (case-insensitive). Empty query clears the highlight set.              */
export function searchGraph(query: string): void {
  const q = query.trim().toLowerCase();
  const matches = q
    ? BRAIN_NODES.filter(
        (n) => n.label.toLowerCase().includes(q) || n.meta.toLowerCase().includes(q),
      ).map((n) => n.id)
    : [];
  updateSelections({
    focusedNodeId: null,
    highlightedNodeIds: matches,
    activeStoryId: null,
  });
  if (getArtifactData()) {
    patchArtifact({
      focusedNodeId: null,
      highlightedNodeIds: matches,
      activeStoryId: null,
    });
  }
}

/* Highlight every node of a given type (or clear when type is null). */
export function filterByType(type: 'role' | 'interviewer' | 'signal' | null): void {
  const matches = type ? BRAIN_NODES.filter((n) => n.type === type).map((n) => n.id) : [];
  updateSelections({
    focusedNodeId: null,
    highlightedNodeIds: matches,
    activeStoryId: null,
  });
  if (getArtifactData()) {
    patchArtifact({
      focusedNodeId: null,
      highlightedNodeIds: matches,
      activeStoryId: null,
    });
  }
}

export function clearFocus(): void {
  updateSelections({
    focusedNodeId: null,
    highlightedNodeIds: [],
    activeStoryId: null,
  });
  if (getArtifactData()) {
    patchArtifact({
      focusedNodeId: null,
      highlightedNodeIds: [],
      activeStoryId: null,
    });
  }
}

export function setRange(rangeId: BrainTimeRangeId): void {
  updateSelections({ timeRangeId: rangeId });
  if (getArtifactData()) {
    patchArtifact({ timeRangeId: rangeId });
  }
}

const CORTEX_THINKING_PAUSE_MS = 4000;
const CORTEX_CONSTRUCT_PAUSE_MS = 2000;

export async function runCortexInsight(kind: CortexInsightKind): Promise<void> {
  const signal = beginRun('brain');
  const fixture = CORTEX_INSIGHTS[kind];
  const artifacts = useArtifactStore.getState();
  const sessions = useSessionStore.getState();

  // (1) Thinking silence — the agent is "thinking" before anything renders.
  // The typing pill is the only signal during this window.
  useTypingStore.getState().start('brain');
  await abortableDelay(CORTEX_THINKING_PAUSE_MS, signal);
  if (signal.aborted) {
    useTypingStore.getState().stop('brain');
    return;
  }
  useTypingStore.getState().stop('brain');

  // (2) Seed the trail-backing artifact (data only — it renders inline in the
  // chat, not in the right panel).
  const initialTrail: CortexInsightArtifactData = {
    title: fixture.title,
    elapsedLabel: fixture.elapsedLabel,
    steps: fixture.steps,
    activeStepNum: fixture.steps[0]?.num ?? null,
    stats: [],
    complete: false,
  };
  artifacts.openArtifact({
    id: CORTEX_INSIGHT_ARTIFACT_ID,
    type: 'cortex-insight',
    title: fixture.title,
    initialData: initialTrail,
  });

  // (3) Drop the trail card into the chat transcript (left side).
  const trailMsg: Message = {
    ...makeMessage('agent', ''),
    cortexTrail: { artifactId: CORTEX_INSIGHT_ARTIFACT_ID },
  };
  sessions.appendMessage('brain', trailMsg);

  // (4) Fill the trail step-by-step (300–500ms stagger per step).
  for (let i = 1; i < fixture.steps.length; i += 1) {
    const delay = CORTEX_TRAIL_STAGGER_MS[i - 1] ?? 400;
    await abortableDelay(delay, signal);
    if (signal.aborted) return;
    const step = fixture.steps[i];
    artifacts.patchArtifact(CORTEX_INSIGHT_ARTIFACT_ID, {
      activeStepNum: step?.num ?? null,
    });
  }

  await abortableDelay(360, signal);
  if (signal.aborted) return;
  artifacts.patchArtifact(CORTEX_INSIGHT_ARTIFACT_ID, {
    stats: fixture.stats,
    activeStepNum: null,
    complete: true,
  });
  artifacts.completeArtifact(CORTEX_INSIGHT_ARTIFACT_ID);

  // (5) Construction pause — Brain stays on the right until we're ready.
  // Second typing burst signals "building the artifact" before the blink-in.
  useTypingStore.getState().start('brain');
  await abortableDelay(CORTEX_CONSTRUCT_PAUSE_MS, signal);
  if (signal.aborted) {
    useTypingStore.getState().stop('brain');
    return;
  }

  // (6) Open the visual analysis artifact, append a tab, and switch to it.
  // The artifact root uses the `cortex-blink-in` animation to flash in.
  if (fixture.analysis) {
    artifacts.openArtifact({
      id: CORTEX_ANALYSIS_ARTIFACT_ID,
      type: 'cortex-analysis',
      title: fixture.analysis.title,
      initialData: fixture.analysis as unknown as Record<string, unknown>,
    });
    artifacts.completeArtifact(CORTEX_ANALYSIS_ARTIFACT_ID);
    ensureWorkspaceTab({
      id: CORTEX_ANALYSIS_ARTIFACT_ID,
      label: `${fixture.analysis.role} · close-rate`,
      kind: 'analysis',
    });
    sessions.setArtifactId('brain', CORTEX_ANALYSIS_ARTIFACT_ID);
  }

  useTypingStore.getState().stop('brain');

  // (7) Closer message.
  if (fixture.analysis) {
    await abortableDelay(420, signal);
    if (signal.aborted) return;
    sessions.appendMessage(
      'brain',
      makeMessage(
        'agent',
        `Analysis ready — opened the ${fixture.analysis.role} close-rate workspace on the right as a new tab.`,
      ),
    );
    return;
  }

  // Fallback for fixtures without `analysis` — lands rich Cortex cards inline.
  for (let i = 0; i < fixture.messages.length; i += 1) {
    if (i > 0) await abortableDelay(CORTEX_MESSAGE_GAP_MS, signal);
    if (signal.aborted) return;
    const m = fixture.messages[i];
    if (!m) continue;
    const base = makeMessage('agent', m.who);
    const msg: Message = {
      ...base,
      cortex: {
        who: m.who,
        blocks: m.blocks,
        ...(m.chips ? { chips: m.chips } : {}),
      },
    };
    sessions.appendMessage('brain', msg);
  }
}

function getCortexAnalysis(): CortexAnalysisData | null {
  const artifact = useArtifactStore.getState().artifacts[CORTEX_ANALYSIS_ARTIFACT_ID];
  if (!artifact) return null;
  return artifact.data as CortexAnalysisData;
}

export function draftSilverMedalistNote(candidateId: string): void {
  const analysis = getCortexAnalysis();
  if (!analysis) return;
  const candidate = analysis.silverMedalists.find((c) => c.id === candidateId);
  if (!candidate) return;
  const sessions = useSessionStore.getState();
  sessions.appendMessage(
    'brain',
    makeMessage('user', `Draft a warm re-engagement note to ${candidate.name}.`),
  );
  sessions.appendMessage(
    'brain',
    makeMessage(
      'agent',
      `Drafting a warm note to ${candidate.name}, anchored in why we passed then ("${candidate.whyThen}") and why now ("${candidate.whyNow.split('.')[0]}."). I'll drop it in your outbox for review.`,
    ),
  );
}

export function draftSilverMedalistsAll(): void {
  const analysis = getCortexAnalysis();
  if (!analysis) return;
  const names = analysis.silverMedalists.map((c) => c.name).join(', ');
  const sessions = useSessionStore.getState();
  sessions.appendMessage(
    'brain',
    makeMessage('user', 'Draft warm re-engagement notes to all three silver medalists.'),
  );
  sessions.appendMessage(
    'brain',
    makeMessage(
      'agent',
      `On it — drafting warm notes to ${names}, each anchored in the specific interview moment that earned them this callback. I'll drop all three in your outbox for review.`,
    ),
  );
}

export async function submitBrainInput(input: string): Promise<void> {
  const trimmed = input.trim();
  if (!trimmed) return;
  const sessions = useSessionStore.getState();
  ensureSession('brain');
  sessions.appendMessage('brain', makeMessage('user', trimmed));

  const insightKind = detectCortexInsightIntent(trimmed);
  if (insightKind) {
    await runCortexInsight(insightKind);
    return;
  }

  const outcome = detectBrainIntent(trimmed);

  switch (outcome.kind) {
    case 'explain_story': {
      if (outcome.storyId) {
        updateSelections({
          activeStoryId: outcome.storyId,
          highlightedNodeIds: outcome.focusNodeIds ?? [],
          focusedNodeId: null,
        });
        if (getArtifactData()) {
          patchArtifact({
            activeStoryId: outcome.storyId,
            highlightedNodeIds: outcome.focusNodeIds ?? [],
            focusedNodeId: null,
          });
        }
      }
      break;
    }
    case 'drill_node': {
      if (outcome.nodeId) {
        updateSelections({
          focusedNodeId: outcome.nodeId,
          highlightedNodeIds: [],
          activeStoryId: null,
        });
        if (getArtifactData()) {
          patchArtifact({
            focusedNodeId: outcome.nodeId,
            highlightedNodeIds: [],
            activeStoryId: null,
          });
        }
      }
      break;
    }
    case 'cause_query': {
      if (outcome.storyId) {
        updateSelections({
          activeStoryId: outcome.storyId,
          highlightedNodeIds: outcome.focusNodeIds ?? [],
          focusedNodeId: null,
        });
        if (getArtifactData()) {
          patchArtifact({
            activeStoryId: outcome.storyId,
            highlightedNodeIds: outcome.focusNodeIds ?? [],
            focusedNodeId: null,
          });
        }
      }
      break;
    }
    case 'mute_story': {
      if (outcome.storyId) {
        const selections = getSelections();
        const nextMuted = Array.from(
          new Set([...(selections.mutedStoryIds ?? []), outcome.storyId]),
        );
        const wasActive = selections.activeStoryId === outcome.storyId;
        updateSelections({
          mutedStoryIds: nextMuted,
          ...(wasActive ? { activeStoryId: null, highlightedNodeIds: [] } : {}),
        });
        if (getArtifactData()) {
          patchArtifact({
            mutedStoryIds: nextMuted,
            ...(wasActive ? { activeStoryId: null, highlightedNodeIds: [] } : {}),
          });
        }
      }
      break;
    }
    case 'reset': {
      updateSelections({
        focusedNodeId: null,
        highlightedNodeIds: [],
        activeStoryId: null,
      });
      if (getArtifactData()) {
        patchArtifact({
          focusedNodeId: null,
          highlightedNodeIds: [],
          activeStoryId: null,
        });
      }
      break;
    }
    default:
      break;
  }

  useSessionStore.getState().appendMessage('brain', makeMessage('agent', outcome.response));
}

export function resetBrain(): void {
  const sessions = useSessionStore.getState();
  const artifacts = useArtifactStore.getState();
  sessions.endSession('brain');
  artifacts.removeArtifact(BRAIN_ARTIFACT_ID);
}
