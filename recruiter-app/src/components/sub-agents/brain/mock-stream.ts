import {
  BRAIN_DEFAULT_RANGE,
  BRAIN_LINKS,
  BRAIN_NODES,
  BRAIN_STORIES,
  type BrainStory,
  findBrainNode,
  findBrainStory,
  searchBrainNodes,
} from '@/fixtures/brain';
import type { StreamScript } from '@/lib/mock-stream';
import { createMockStream, type StreamEvent } from '@/lib/mock-stream';

export const BRAIN_STAGES = ['brain'] as const;
export type BrainStageId = (typeof BRAIN_STAGES)[number];

export const BRAIN_ARTIFACT_ID = 'brain-canvas';
export const BRAIN_WEEK_LABEL = 'Week of April 13';

export interface BrainContext {
  weekLabel?: string;
}

export interface BrainMockStreamOptions {
  speed?: number;
}

function tokens(text: string): StreamScript {
  return text
    .split(/(\s+)/)
    .filter(Boolean)
    .map((token) => ({ type: 'prose_token' as const, token }));
}

function buildBrainScript(ctx: BrainContext = {}): StreamScript {
  const weekLabel = ctx.weekLabel ?? BRAIN_WEEK_LABEL;
  const events: StreamScript = [
    { type: 'stage_start' },
    ...tokens(`Here is what I am seeing across your roles for ${weekLabel}.`),
    {
      type: 'sub_reveal',
      sub: 'Click a node to drill in · click a story to elaborate · ask me "what is causing X" to go deeper.',
    },
    {
      type: 'artifact_start',
      artifactId: BRAIN_ARTIFACT_ID,
      artifactType: 'brain-canvas',
      title: `OpenRecruiting Brain · ${weekLabel}`,
    },
    {
      type: 'artifact_patch',
      artifactId: BRAIN_ARTIFACT_ID,
      patch: {
        weekLabel,
        timeRangeId: BRAIN_DEFAULT_RANGE,
        nodes: BRAIN_NODES,
        links: BRAIN_LINKS,
        stories: BRAIN_STORIES,
        mutedStoryIds: [],
        focusedNodeId: null,
        highlightedNodeIds: [],
        activeStoryId: null,
      },
    },
    { type: 'artifact_complete', artifactId: BRAIN_ARTIFACT_ID },
    { type: 'stage_end', nextStage: 'brain' },
  ];
  return events;
}

export function brainMockStream(
  _stageId: BrainStageId,
  contextJson: string | null = null,
  options: BrainMockStreamOptions = {},
): AsyncIterable<StreamEvent> {
  let ctx: BrainContext = {};
  if (contextJson) {
    try {
      const parsed = JSON.parse(contextJson) as BrainContext;
      if (parsed && typeof parsed === 'object') ctx = parsed;
    } catch {
      // ignore malformed context
    }
  }
  const script = buildBrainScript(ctx);
  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  return createMockStream(script, streamOptions);
}

// ---- Intent matcher ----

export type BrainIntentKind =
  | 'explain_story'
  | 'drill_node'
  | 'cause_query'
  | 'compare'
  | 'mute_story'
  | 'list_stories'
  | 'reset'
  | 'generic';

export interface BrainIntentOutcome {
  kind: BrainIntentKind;
  response: string;
  storyId?: string;
  nodeId?: string;
  focusNodeIds?: string[];
  mute?: boolean;
}

function normalize(input: string): string {
  return input.trim().toLowerCase();
}

function matchStory(input: string): BrainStory | undefined {
  const n = normalize(input);
  // direct keyword per story id
  if (n.includes('scoring drift') || n.includes('drift'))
    return findBrainStory('story-scoring-drift');
  if (
    n.includes('panel load') ||
    n.includes('panel overload') ||
    n.includes('panel imbalance') ||
    n.includes('overload')
  ) {
    return findBrainStory('story-panel-overload');
  }
  if (
    n.includes('pipeline at risk') ||
    n.includes('pipeline risk') ||
    n.includes('data scientist') ||
    n.includes('ds role')
  ) {
    return findBrainStory('story-pipeline-risk');
  }
  if (
    n.includes('design engineer') ||
    n.includes('design velocity') ||
    n.includes('design moving')
  ) {
    return findBrainStory('story-design-velocity');
  }
  // fallback: partial match on title
  for (const s of BRAIN_STORIES) {
    const title = s.title.toLowerCase();
    if (n.includes(title)) return s;
  }
  return undefined;
}

export function detectBrainIntent(input: string): BrainIntentOutcome {
  const n = normalize(input);

  if (!n) {
    return {
      kind: 'generic',
      response:
        'Ask me to explain a story, drill into a node, compare quarters, or mute a signal you already saw.',
    };
  }

  if (n.startsWith('mute') || n.includes('mute ')) {
    const story = matchStory(n);
    if (story) {
      return {
        kind: 'mute_story',
        response: `Muted "${story.title}". It will not show up until you refresh the range.`,
        storyId: story.id,
        mute: true,
      };
    }
    return {
      kind: 'generic',
      response:
        'Tell me which story to mute — scoring drift, panel load, pipeline at risk, or design engineer.',
    };
  }

  // Cause queries must be checked before explain/what-is since they overlap ("what is causing X").
  if (
    n.includes("what's causing") ||
    n.includes('what is causing') ||
    n.includes('why is') ||
    n.includes('cause') ||
    n.includes('root')
  ) {
    const story = matchStory(n);
    if (story) {
      return {
        kind: 'cause_query',
        response: `Root cause for "${story.title}": ${story.evidence.join(' · ')}.`,
        storyId: story.id,
        focusNodeIds: story.targetIds,
      };
    }
    return {
      kind: 'cause_query',
      response:
        'Narrow that down for me — which story or node? Try "what is causing scoring drift?" or "why is the data scientist pipeline at risk?"',
    };
  }

  if (n.startsWith('explain') || n.startsWith('tell me about') || n.startsWith('what is')) {
    const story = matchStory(n);
    if (story) {
      const nodes = story.targetIds;
      return {
        kind: 'explain_story',
        response: `${story.title} — ${story.elaboration}`,
        storyId: story.id,
        focusNodeIds: nodes,
      };
    }
  }

  if (n.includes('drill into') || n.includes('show me') || n.startsWith('focus')) {
    // try to match a node by name
    const rest = n.replace(/drill into|show me|focus on|focus/g, '').trim();
    const matches = searchBrainNodes(rest || n);
    const first = matches[0];
    if (first) {
      return {
        kind: 'drill_node',
        response: `Focusing on ${first.label}. ${first.meta}. Click a neighbor to follow a relationship.`,
        nodeId: first.id,
        focusNodeIds: [first.id],
      };
    }
  }

  if (n.includes('compare') || n.includes('vs') || n.includes('versus')) {
    return {
      kind: 'compare',
      response:
        'Quarter-over-quarter view is stubbed in this demo — Q1 shows 2 open stories versus Q2 with 4 (scoring drift is new this quarter).',
    };
  }

  if (
    n === 'stories' ||
    n.includes('what stories') ||
    n.includes('what are you tracking') ||
    n.includes('list stories')
  ) {
    const titles = BRAIN_STORIES.map((s) => `"${s.title}"`).join(' · ');
    return {
      kind: 'list_stories',
      response: `Tracking ${BRAIN_STORIES.length} stories this week: ${titles}.`,
    };
  }

  if (n === 'clear' || n === 'reset' || n.includes('clear focus')) {
    return {
      kind: 'reset',
      response: 'Cleared the focus — showing the full graph again.',
    };
  }

  // Fallback: try to match a story by keyword
  const story = matchStory(n);
  if (story) {
    return {
      kind: 'explain_story',
      response: `${story.title} — ${story.elaboration}`,
      storyId: story.id,
      focusNodeIds: story.targetIds,
    };
  }

  // Fallback: try to match a node
  const matches = searchBrainNodes(n);
  const first = matches[0];
  if (first) {
    return {
      kind: 'drill_node',
      response: `${first.label} — ${first.meta}. Click a neighbor to follow the relationship.`,
      nodeId: first.id,
      focusNodeIds: [first.id],
    };
  }

  return {
    kind: 'generic',
    response:
      'Try "explain scoring drift", "drill into Ben", "what is causing pipeline risk", or "mute panel load".',
  };
}

export function labelForNode(nodeId: string): string {
  const n = findBrainNode(nodeId);
  return n?.label ?? nodeId;
}
