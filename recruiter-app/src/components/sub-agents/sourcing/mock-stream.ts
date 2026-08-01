import type { SourcingCriteria } from '@/fixtures/sourcing-queries';
import type { SourcingCandidate } from '@/fixtures/sourcing-results';
import {
  filterByQuery,
  SOURCING_CANDIDATES,
  TOTAL_MATCH_COUNT_LABEL,
} from '@/fixtures/sourcing-results';
import type { StreamScript } from '@/lib/mock-stream';
import { createMockStream, type StreamEvent } from '@/lib/mock-stream';

export const SOURCING_STAGES = [
  'mode_pick',
  'role_pick',
  'query_build',
  'results',
  'preferences_chat',
  'strategy_publish',
  'channel_stream',
  'candidate_stream',
  'offer_add',
] as const;
export type SourcingStageId = (typeof SOURCING_STAGES)[number];

export const SOURCING_ARTIFACT_ID = 'sourcing-results';

export interface SourcingContext {
  mode?: 'existing' | 'fresh';
  roleId?: string;
  roleTitle?: string;
  queryText?: string;
  criteria?: SourcingCriteria;
}

export interface SourcingMockStreamOptions {
  speed?: number;
}

function tokens(text: string): StreamScript {
  return text
    .split(/(\s+)/)
    .filter(Boolean)
    .map((token) => ({ type: 'prose_token' as const, token }));
}

function buildModePickScript(): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens('Sourcing for an existing role or starting fresh?'),
    {
      type: 'sub_reveal',
      sub: 'Pick a path below and I will tune the query and surface candidates.',
    },
    { type: 'stage_end', nextStage: 'mode_pick' },
  ];
}

function buildRolePickScript(): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens('Which role should I source for?'),
    {
      type: 'sub_reveal',
      sub: 'I will pre-fill the query from the JD and must-haves so you can tweak from there.',
    },
    { type: 'stage_end', nextStage: 'role_pick' },
  ];
}

function buildQueryBuildScript(): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens('Describe who you are looking for in plain English.'),
    {
      type: 'sub_reveal',
      sub: 'As you type, I will extract title, location, years, industry, and skills into filter pills.',
    },
    { type: 'stage_end', nextStage: 'query_build' },
  ];
}

function buildResultsScript(ctx: SourcingContext): StreamScript {
  const criteria = ctx.criteria ?? {};
  const roleLabel = ctx.roleTitle ?? null;
  const items: SourcingCandidate[] = filterByQuery(SOURCING_CANDIDATES, criteria).slice(0, 16);

  const events: StreamScript = [
    { type: 'stage_start' },
    ...tokens(
      `Pulling candidates that match — ${TOTAL_MATCH_COUNT_LABEL} total, streaming the top ${items.length} now.`,
    ),
    {
      type: 'sub_reveal',
      sub: 'Click a card to inspect. Check off candidates to enable pipeline actions on the right.',
    },
    {
      type: 'artifact_start',
      artifactId: SOURCING_ARTIFACT_ID,
      artifactType: 'sourcing-results',
      title: roleLabel ? `Sourcing · ${roleLabel}` : 'Sourcing results',
    },
    {
      type: 'artifact_patch',
      artifactId: SOURCING_ARTIFACT_ID,
      patch: {
        criteria,
        roleLabel,
        candidates: [],
        selectedIds: [],
        totalMatchesLabel: TOTAL_MATCH_COUNT_LABEL,
        page: 0,
        pageSize: 8,
      },
    },
  ];

  // Stream candidates in small batches so the UI feels alive.
  const batchSize = 4;
  const rolling: SourcingCandidate[] = [];
  for (let i = 0; i < items.length; i += batchSize) {
    const batch = items.slice(i, i + batchSize);
    rolling.push(...batch);
    events.push({
      type: 'artifact_patch',
      artifactId: SOURCING_ARTIFACT_ID,
      patch: { candidates: [...rolling] },
    });
  }

  events.push(
    { type: 'artifact_complete', artifactId: SOURCING_ARTIFACT_ID },
    { type: 'stage_end', nextStage: 'results' },
  );
  return events;
}

export function buildSourcingScript(
  stageId: SourcingStageId,
  ctx: SourcingContext = {},
): StreamScript {
  switch (stageId) {
    case 'mode_pick':
      return buildModePickScript();
    case 'role_pick':
      return buildRolePickScript();
    case 'query_build':
      return buildQueryBuildScript();
    case 'results':
      return buildResultsScript(ctx);
    case 'preferences_chat':
    case 'strategy_publish':
    case 'channel_stream':
    case 'candidate_stream':
    case 'offer_add':
      // These refined-flow stages are built dynamically by sourcing/flow.ts
      return [{ type: 'stage_end', nextStage: stageId }];
  }
}

export function sourcingMockStream(
  stageId: SourcingStageId,
  contextJson: string | null = null,
  options: SourcingMockStreamOptions = {},
): AsyncIterable<StreamEvent> {
  let ctx: SourcingContext = {};
  if (contextJson) {
    try {
      const parsed = JSON.parse(contextJson) as SourcingContext;
      if (parsed && typeof parsed === 'object') ctx = parsed;
    } catch {
      // ignore malformed context.
    }
  }
  const script = buildSourcingScript(stageId, ctx);
  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  return createMockStream(script, streamOptions);
}

// ---- Composer intents (for refine/add/send on results stage) ----

export type SourcingActionIntent =
  | 'refine_filters'
  | 'add_to_pipeline'
  | 'send_outreach'
  | 'export'
  | 'generic';

export interface SourcingActionOutcome {
  kind: SourcingActionIntent;
  response: string;
}

function normalizeInput(input: string): string {
  return input.trim().toLowerCase();
}

export function detectSourcingIntent(input: string, selectedCount: number): SourcingActionOutcome {
  const n = normalizeInput(input);

  if (n.includes('refine') || n.includes('tweak filter') || n.includes('tweak the filter')) {
    return {
      kind: 'refine_filters',
      response:
        'Tell me what to change — remove a pill, add "in NYC", bump the years, or drop a skill.',
    };
  }

  if (
    n.includes('add to pipeline') ||
    n.includes('add selected') ||
    n.includes('push to pipeline')
  ) {
    if (selectedCount === 0) {
      return {
        kind: 'add_to_pipeline',
        response: 'Pick a few candidates with the checkboxes first, then I will add them.',
      };
    }
    return {
      kind: 'add_to_pipeline',
      response: `Queued ${selectedCount} candidate${
        selectedCount === 1 ? '' : 's'
      } for the role pipeline. Recruiters will see them on next refresh.`,
    };
  }

  if (n.includes('outreach') || n.includes('send message') || n.includes('reach out')) {
    if (selectedCount === 0) {
      return {
        kind: 'send_outreach',
        response: 'Select candidates first — outreach sends in a batch.',
      };
    }
    return {
      kind: 'send_outreach',
      response: `Drafted outreach to ${selectedCount} candidate${
        selectedCount === 1 ? '' : 's'
      }. Review each draft before I send.`,
    };
  }

  if (n.includes('export') || n.includes('download') || n.includes('csv')) {
    return {
      kind: 'export',
      response: 'Export is stubbed in this demo — would drop a CSV with the visible results.',
    };
  }

  return {
    kind: 'generic',
    response:
      'Got it — make note. Say "refine filters", "add selected to pipeline", "send outreach", or "export" to act on results.',
  };
}
