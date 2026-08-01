import type { StreamScript } from '@/lib/mock-stream';
import { createMockStream, type StreamEvent } from '@/lib/mock-stream';

export const DEBRIEF_STAGES = ['role_pick', 'candidate_pick', 'analyzing', 'result'] as const;
export type DebriefStageId = (typeof DEBRIEF_STAGES)[number];

export interface DebriefMockStreamOptions {
  speed?: number;
}

export const DEBRIEF_ARTIFACT_ID = 'debrief-pm-sfo';

function tokens(text: string): StreamScript {
  return text
    .split(/(\s+)/)
    .filter(Boolean)
    .map((token) => ({ type: 'prose_token' as const, token }));
}

function buildRolePickScript(): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens('Which role do you want to debrief?'),
    {
      type: 'sub_reveal',
      sub: 'Pick a role below — I\u2019ll pull the interview signal next.',
    },
    { type: 'stage_end', nextStage: 'role_pick' },
  ];
}

function buildCandidatePickScript(roleTitle: string): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens(`Got it \u2014 ${roleTitle}. Which candidates should I compare?`),
    { type: 'sub_reveal', sub: 'Pick 2 or more and hit Compare.' },
    { type: 'stage_end', nextStage: 'candidate_pick' },
  ];
}

function buildAnalyzingScript(candidateNames: string[]): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens(
      `Analyzing ${candidateNames.join(', ')}\u2026 I\u2019m cross-referencing transcripts and scorecards.`,
    ),
    { type: 'stage_end', nextStage: 'analyzing' },
  ];
}

function buildResultScript(roleTitle: string, candidateNames: string[]): StreamScript {
  return [
    { type: 'stage_start' },
    ...tokens(
      `Done. ${candidateNames[0] ?? 'The top candidate'} edges ahead on systems thinking; ${candidateNames[1] ?? 'the runner-up'} brings the strongest execution signal for ${roleTitle}.`,
    ),
    {
      type: 'artifact_patch',
      artifactId: DEBRIEF_ARTIFACT_ID,
      patch: { roleTitle, streamedAt: new Date().toISOString() },
    },
    { type: 'artifact_complete', artifactId: DEBRIEF_ARTIFACT_ID },
    {
      type: 'ux_reveal',
      component: 'debrief_result_chips',
      props: {
        chips: [
          { label: 'Push back on a score', value: 'pushback' },
          { label: 'Re-weigh a dimension', value: 'reweigh' },
        ],
      },
    },
    { type: 'stage_end', nextStage: 'result' },
  ];
}

export interface DebriefContext {
  roleTitle?: string;
  candidateNames?: string[];
}

export function buildDebriefScript(
  stageId: DebriefStageId,
  ctx: DebriefContext = {},
): StreamScript {
  switch (stageId) {
    case 'role_pick':
      return buildRolePickScript();
    case 'candidate_pick':
      return buildCandidatePickScript(ctx.roleTitle ?? 'that role');
    case 'analyzing':
      return buildAnalyzingScript(ctx.candidateNames ?? []);
    case 'result':
      return buildResultScript(ctx.roleTitle ?? 'this role', ctx.candidateNames ?? []);
  }
}

export function debriefMockStream(
  stageId: DebriefStageId,
  contextJson: string | null = null,
  options: DebriefMockStreamOptions = {},
): AsyncIterable<StreamEvent> {
  let ctx: DebriefContext = {};
  if (contextJson) {
    try {
      const parsed = JSON.parse(contextJson) as DebriefContext;
      if (parsed && typeof parsed === 'object') ctx = parsed;
    } catch {
      // ignore malformed input; fall back to defaults.
    }
  }
  const script = buildDebriefScript(stageId, ctx);
  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  return createMockStream(script, streamOptions);
}
