import { beforeEach, describe, expect, test } from 'bun:test';
import { BRAIN_STORIES } from '@/fixtures/brain';
import { useArtifactStore, useSessionStore } from '@/stores';
import {
  type BrainSelections,
  clearFocus,
  explainStory,
  focusNode,
  muteStory,
  rehydrateBrain,
  resetBrain,
  runBrainStage,
  setRange,
  submitBrainInput,
} from './flow';
import { BRAIN_ARTIFACT_ID } from './mock-stream';

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

function getSelections(): BrainSelections {
  const session = useSessionStore.getState().sessions.brain;
  return (session?.selections as BrainSelections | undefined) ?? {};
}

describe('brain flow', () => {
  test('runBrainStage seeds the artifact with nodes/links/stories and messages', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    const artifact = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID];
    expect(artifact?.type).toBe('brain-canvas');
    const data = artifact?.data as {
      nodes: unknown[];
      stories: unknown[];
      mutedStoryIds: string[];
    };
    expect(Array.isArray(data.nodes)).toBe(true);
    expect(data.nodes.length).toBeGreaterThan(0);
    expect(data.stories.length).toBe(BRAIN_STORIES.length);
    const session = useSessionStore.getState().sessions.brain;
    expect(session?.messages.filter((m) => m.role === 'agent').length).toBeGreaterThan(0);
  });

  test('explainStory sets activeStoryId + highlights and appends user+agent messages', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    explainStory('story-scoring-drift');
    const sel = getSelections();
    expect(sel.activeStoryId).toBe('story-scoring-drift');
    expect((sel.highlightedNodeIds ?? []).length).toBeGreaterThan(0);
    const session = useSessionStore.getState().sessions.brain;
    const lastTwo = session?.messages.slice(-2) ?? [];
    expect(lastTwo[0]?.role).toBe('user');
    expect(lastTwo[1]?.role).toBe('agent');
    const data = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID]?.data as {
      activeStoryId: string | null;
    };
    expect(data.activeStoryId).toBe('story-scoring-drift');
  });

  test('muteStory adds to mutedStoryIds list', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    muteStory('story-panel-overload');
    const sel = getSelections();
    expect(sel.mutedStoryIds).toContain('story-panel-overload');
    const data = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID]?.data as {
      mutedStoryIds: string[];
    };
    expect(data.mutedStoryIds).toContain('story-panel-overload');
  });

  test('focusNode toggles the focusedNodeId', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    focusNode('i-ben');
    expect(getSelections().focusedNodeId).toBe('i-ben');
    focusNode('i-ben');
    expect(getSelections().focusedNodeId).toBe(null);
  });

  test('clearFocus resets focus + story highlights', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    focusNode('i-ben');
    clearFocus();
    expect(getSelections().focusedNodeId).toBe(null);
    expect(getSelections().highlightedNodeIds).toEqual([]);
    expect(getSelections().activeStoryId).toBe(null);
  });

  test('setRange updates the timeRangeId in selections + artifact', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    setRange('quarter');
    expect(getSelections().timeRangeId).toBe('quarter');
    const data = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID]?.data as {
      timeRangeId: string;
    };
    expect(data.timeRangeId).toBe('quarter');
  });

  test('submitBrainInput("explain scoring drift") sets active story + agent msg', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    await submitBrainInput('explain scoring drift');
    const session = useSessionStore.getState().sessions.brain;
    expect(getSelections().activeStoryId).toBe('story-scoring-drift');
    const last = session?.messages.at(-1);
    expect(last?.role).toBe('agent');
    expect(last?.text.toLowerCase()).toContain('scoring drift');
  });

  test('submitBrainInput("mute panel load") hides the panel overload story', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    await submitBrainInput('mute panel load');
    expect(getSelections().mutedStoryIds).toContain('story-panel-overload');
  });

  test('submitBrainInput("drill into Ben") focuses the Ben node', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    await submitBrainInput('drill into Ben');
    expect(getSelections().focusedNodeId).toBe('i-ben');
  });

  test('submitBrainInput empty noop', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    const msgsBefore = useSessionStore.getState().sessions.brain?.messages.length ?? 0;
    await submitBrainInput('   ');
    const msgsAfter = useSessionStore.getState().sessions.brain?.messages.length ?? 0;
    expect(msgsAfter).toBe(msgsBefore);
  });

  test('rehydrateBrain restores the artifact from session selections', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    muteStory('story-panel-overload');
    useArtifactStore.getState().removeArtifact(BRAIN_ARTIFACT_ID);
    await rehydrateBrain();
    const art = useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID];
    expect(art).toBeDefined();
    const data = art?.data as { mutedStoryIds: string[] };
    expect(data.mutedStoryIds).toContain('story-panel-overload');
  });

  test('resetBrain removes session + artifact', async () => {
    useSessionStore.getState().startSession('brain', 'brain');
    await runBrainStage({ speed: 0 });
    resetBrain();
    expect(useSessionStore.getState().sessions.brain).toBe(null);
    expect(useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID]).toBeUndefined();
  });
});
