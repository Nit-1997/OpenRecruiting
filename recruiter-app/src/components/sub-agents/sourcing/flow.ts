import type { SourcingStrategyArtifactData } from '@/components/artifacts/sourcing-strategy';
import type { RoleFixture } from '@/fixtures/roles';
import type { SourcingCriteria } from '@/fixtures/sourcing-queries';
import {
  filterByQuery,
  SOURCING_CANDIDATES,
  TOTAL_MATCH_COUNT_LABEL,
} from '@/fixtures/sourcing-results';
import {
  SOURCING_STRATEGY_ARTIFACT_ID,
  SOURCING_STRATEGY_CANDIDATES,
  SOURCING_STRATEGY_CHANNELS,
  SOURCING_STRATEGY_DEFAULTS,
  SOURCING_STRATEGY_TOTAL_LABEL,
} from '@/fixtures/sourcing-strategy';
import { createMockStream, type StreamScript } from '@/lib/mock-stream';
import {
  abortableDelay,
  beginRun,
  cancelRun,
  driveStageStream,
  makeMessage,
  widenSelections,
} from '@/lib/sub-agent-runner';
import { candidates as candidatesService } from '@/services';
import { ServiceError } from '@/services/service-error';
import { useArtifactStore, useSessionStore } from '@/stores';
import type { Message } from '@/types';
import {
  detectSourcingIntent,
  SOURCING_ARTIFACT_ID,
  type SourcingActionIntent,
  type SourcingContext,
  type SourcingStageId,
  sourcingMockStream,
} from './mock-stream';

export type SourcingMode = 'existing' | 'fresh';

export interface SourcingSelections {
  mode?: SourcingMode | undefined;
  roleId?: string | undefined;
  roleTitle?: string | undefined;
  queryText?: string | undefined;
  criteria?: SourcingCriteria | undefined;
  selectedIds?: string[] | undefined;
  lastIntent?: SourcingActionIntent | undefined;
  preferenceTurnIdx?: number | undefined;
  preferenceAnswers?: string[] | undefined;
}

function ensureSession(initialStage: SourcingStageId = 'mode_pick'): void {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.sourcing) sessions.startSession('sourcing', initialStage);
}

function getSelections(): SourcingSelections {
  const current = useSessionStore.getState().sessions.sourcing;
  return (current?.selections as SourcingSelections | undefined) ?? {};
}

function updateSelections(partial: Partial<SourcingSelections>): void {
  const current = getSelections();
  const merged: SourcingSelections = { ...current, ...partial };
  useSessionStore.getState().updateSelections('sourcing', widenSelections(merged));
}

const MODE_PICK_CHIPS: Message['chips'] = [
  { label: 'Source for an existing role', value: 'existing', primary: true },
  { label: 'Start from a fresh search', value: 'fresh' },
];

export async function runSourcingStage(
  stageId: SourcingStageId,
  ctx: SourcingContext = {},
  options: { speed?: number } = {},
): Promise<void> {
  ensureSession(stageId);
  useSessionStore.getState().setStage('sourcing', stageId);

  const streamOptions: { speed?: number } = {};
  if (options.speed !== undefined) streamOptions.speed = options.speed;
  const stream = sourcingMockStream(stageId, JSON.stringify(ctx), streamOptions);

  await driveStageStream('sourcing', stageId, stream, {
    chipsFor: (stage) => (stage === 'mode_pick' ? MODE_PICK_CHIPS : undefined),
  });
}

export async function pickMode(mode: SourcingMode): Promise<void> {
  const sessions = useSessionStore.getState();
  ensureSession('mode_pick');
  const userText =
    mode === 'existing' ? 'Source for an existing role.' : 'Start from a fresh search.';
  sessions.appendMessage('sourcing', makeMessage('user', userText));
  updateSelections({ mode });
  const nextStage: SourcingStageId = mode === 'existing' ? 'role_pick' : 'query_build';
  sessions.setStage('sourcing', nextStage);
  await runSourcingStage(nextStage);
}

export async function pickRoleForSourcing(role: RoleFixture): Promise<void> {
  const sessions = useSessionStore.getState();
  ensureSession('role_pick');
  sessions.appendMessage('sourcing', makeMessage('user', `Source for ${role.title}.`));
  updateSelections({
    mode: 'existing',
    roleId: role.id,
    roleTitle: role.title,
    selectedIds: [],
    preferenceTurnIdx: 0,
    preferenceAnswers: [],
  });
  sessions.setStage('sourcing', 'preferences_chat');
  const opener: StreamScript = [
    { type: 'stage_start' },
    ...sourcingTokens(
      `Sourcing for ${role.title}. I'll ask a couple of quick questions to lock in the ICP, then draft the strategy and scan channels.`,
    ),
    { type: 'stage_end', nextStage: 'preferences_chat' },
  ];
  await drainSourcingStream('preferences_chat', opener);
  await sleep(300);
  await playPreferenceTurn();
}

export async function submitQuery(text: string): Promise<void> {
  const sessions = useSessionStore.getState();
  ensureSession('query_build');
  const trimmed = text.trim();
  if (!trimmed) return;
  sessions.appendMessage('sourcing', makeMessage('user', trimmed));
  updateSelections({
    mode: 'fresh',
    roleId: undefined,
    roleTitle: undefined,
    queryText: trimmed,
    selectedIds: [],
    preferenceTurnIdx: 0,
    preferenceAnswers: [trimmed],
  });
  sessions.setStage('sourcing', 'preferences_chat');
  const opener: StreamScript = [
    { type: 'stage_start' },
    ...sourcingTokens(
      `Got it — "${trimmed}". I'll treat that as your baseline ICP and ask one quick follow-up to lock the strategy, then start sourcing.`,
    ),
    { type: 'stage_end', nextStage: 'preferences_chat' },
  ];
  await drainSourcingStream('preferences_chat', opener);
  await sleep(300);
  await playPreferenceTurn();
}

export function toggleCandidateSelection(candidateId: string): void {
  const selections = getSelections();
  const current = selections.selectedIds ?? [];
  const next = current.includes(candidateId)
    ? current.filter((id) => id !== candidateId)
    : [...current, candidateId];
  updateSelections({ selectedIds: next });
  useArtifactStore.getState().patchArtifact(SOURCING_ARTIFACT_ID, { selectedIds: next });
}

export function removeFilterPill(pillKey: string): void {
  const selections = getSelections();
  const criteria: SourcingCriteria = { ...(selections.criteria ?? {}) };
  if (pillKey.startsWith('skill:')) {
    const target = pillKey.slice('skill:'.length);
    const nextSkills = (criteria.skills ?? []).filter((s) => s !== target);
    if (nextSkills.length === 0) delete criteria.skills;
    else criteria.skills = nextSkills;
  } else {
    delete criteria[pillKey as keyof SourcingCriteria];
  }
  const filtered = filterByQuery(SOURCING_CANDIDATES, criteria).slice(0, 16);
  updateSelections({ criteria, selectedIds: [] });
  useArtifactStore.getState().patchArtifact(SOURCING_ARTIFACT_ID, {
    criteria,
    candidates: filtered,
    selectedIds: [],
    page: 0,
  });
}

export function setPage(page: number): void {
  useArtifactStore.getState().patchArtifact(SOURCING_ARTIFACT_ID, { page });
}

export function resetSourcing(): void {
  const sessions = useSessionStore.getState();
  const artifacts = useArtifactStore.getState();
  sessions.endSession('sourcing');
  artifacts.removeArtifact(SOURCING_ARTIFACT_ID);
}

export function cancelFreshQuery(): void {
  useSessionStore.getState().setStage('sourcing', 'mode_pick');
  updateSelections({ mode: undefined });
}

const INTENT_PROMPTS: Record<SourcingActionIntent, string> = {
  refine_filters: 'Refine filters',
  add_to_pipeline: 'Add selected to pipeline',
  send_outreach: 'Send outreach to selected',
  export: 'Export results',
  generic: 'Do something with the results',
};

export async function submitSourcingAction(intent: SourcingActionIntent): Promise<void> {
  await submitSourcingInput(INTENT_PROMPTS[intent]);
}

export async function submitSourcingInput(input: string): Promise<void> {
  const sessions = useSessionStore.getState();
  sessions.appendMessage('sourcing', makeMessage('user', input));
  const selections = getSelections();
  const selectedCount = (selections.selectedIds ?? []).length;
  const outcome = detectSourcingIntent(input, selectedCount);
  updateSelections({ lastIntent: outcome.kind });
  sessions.appendMessage('sourcing', makeMessage('agent', outcome.response));
}

function sourcingTokens(text: string): StreamScript {
  return text
    .split(/(\s+)/)
    .filter(Boolean)
    .map((token) => ({ type: 'prose_token' as const, token }));
}

async function drainSourcingStream(
  stageId: SourcingStageId,
  script: StreamScript,
  chips?: Message['chips'],
): Promise<void> {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.sourcing) sessions.startSession('sourcing', stageId);
  sessions.setStage('sourcing', stageId);

  await driveStageStream('sourcing', stageId, createMockStream(script), {
    chipsFor: () => chips,
  });
}

function formatTimestamp(): string {
  const now = new Date();
  return now.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function baseStrategyData(
  roleId: string | null,
  roleTitle: string | null,
  userPreferences: string | null,
): SourcingStrategyArtifactData {
  return {
    strategyId: `ss_${Date.now().toString(36)}`,
    version: 1,
    roleId,
    roleTitle,
    ownerName: 'Taylor',
    createdAtLabel: formatTimestamp(),
    ...SOURCING_STRATEGY_DEFAULTS,
    userPreferences,
    trailSteps: [],
    trailVisible: false,
    channels: SOURCING_STRATEGY_CHANNELS.map((c) => ({ ...c })),
    candidates: [],
    selectedCandidateIds: [],
    phase: 'drafting',
    activeTab: 'strategy',
    addedCount: 0,
    totalProfilesLabel: SOURCING_STRATEGY_TOTAL_LABEL,
    savedToRole: false,
    shareUrl: null,
  };
}

interface PreferenceTurn {
  key: 'industry' | 'companies' | 'musthaves';
  prompt: string;
  chips: Array<{ label: string; value: string; text: string; primary?: boolean }>;
}

const PREFERENCE_TURNS: PreferenceTurn[] = [
  {
    key: 'industry',
    prompt:
      'Before I draft, a couple of quick confirms. First — any specific industry or vertical we should focus on?',
    chips: [
      {
        label: 'PLG B2B SaaS',
        value: 'pref_industry_plg',
        text: 'PLG B2B SaaS',
        primary: true,
      },
      {
        label: 'Any top-tier tech',
        value: 'pref_industry_any',
        text: 'Open to any top-tier tech',
      },
    ],
  },
  {
    key: 'companies',
    prompt:
      'Got it. Any specific target companies, or archetypes we should avoid (e.g., pure enterprise, agency backgrounds)?',
    chips: [
      {
        label: 'Notion / Figma / Linear / Vercel adjacent',
        value: 'pref_companies_plg',
        text: 'Notion, Figma, Linear, Vercel adjacent · avoid pure enterprise PMs',
        primary: true,
      },
      {
        label: 'Broader PLG + exclude agencies',
        value: 'pref_companies_broad',
        text: 'Broader top PLG · exclude agencies and consultants',
      },
    ],
  },
  {
    key: 'musthaves',
    prompt: 'Last one — any must-haves on background (schools, shipped metrics, specific motions)?',
    chips: [
      {
        label: 'Shipped activation or onboarding',
        value: 'pref_musthaves_metrics',
        text: 'Must have shipped activation or onboarding metric end-to-end · no school filter',
        primary: true,
      },
      {
        label: 'Top schools + PLG chops',
        value: 'pref_musthaves_schools',
        text: 'Prioritize top schools with PLG experience',
      },
    ],
  },
];

function getPrefTurnIndex(): number {
  const selections = getSelections();
  return (selections.preferenceTurnIdx as number | undefined) ?? 0;
}

function setPrefTurnIndex(idx: number): void {
  updateSelections({ preferenceTurnIdx: idx } as Partial<SourcingSelections>);
}

function appendPref(text: string): void {
  const selections = getSelections();
  const current =
    ((selections.preferenceAnswers as string[] | undefined) ?? []).filter(Boolean) ?? [];
  const next = [...current, text];
  updateSelections({ preferenceAnswers: next } as Partial<SourcingSelections>);
}

function joinedPrefs(): string | null {
  const selections = getSelections();
  const list = (selections.preferenceAnswers as string[] | undefined) ?? [];
  if (list.length === 0) return null;
  return list.join(' · ');
}

async function playPreferenceTurn(): Promise<void> {
  const idx = getPrefTurnIndex();
  const turn = PREFERENCE_TURNS[idx];
  if (!turn) {
    await runStrategyAndChannels(joinedPrefs());
    return;
  }
  const script: StreamScript = [
    { type: 'stage_start' },
    ...sourcingTokens(turn.prompt),
    { type: 'stage_end', nextStage: 'preferences_chat' },
  ];
  const chips: Message['chips'] = [
    ...turn.chips.map((c) => ({
      label: c.label,
      value: c.value,
      primary: c.primary ?? false,
    })),
    { label: 'Start with defaults', value: 'start_sourcing_defaults' },
  ];
  await drainSourcingStream('preferences_chat', script, chips);
}

export async function handlePreferenceChip(chipValue: string): Promise<void> {
  const sessions = useSessionStore.getState();
  if (chipValue === 'start_sourcing_defaults') {
    sessions.appendMessage('sourcing', makeMessage('user', 'Start with defaults.'));
    await runStrategyAndChannels(joinedPrefs());
    return;
  }
  const idx = getPrefTurnIndex();
  const turn = PREFERENCE_TURNS[idx];
  if (!turn) return;
  const match = turn.chips.find((c) => c.value === chipValue);
  if (!match) return;
  sessions.appendMessage('sourcing', makeMessage('user', match.label));
  appendPref(match.text);
  setPrefTurnIndex(idx + 1);
  if (idx + 1 >= PREFERENCE_TURNS.length) {
    await runStrategyAndChannels(joinedPrefs());
    return;
  }
  await playPreferenceTurn();
}

export async function startSourcingForRole(roleId: string, roleTitle: string): Promise<void> {
  const sessions = useSessionStore.getState();
  if (!sessions.sessions.sourcing) sessions.startSession('sourcing', 'preferences_chat');
  sessions.setStage('sourcing', 'preferences_chat');
  updateSelections({
    mode: 'existing',
    roleId,
    roleTitle,
    selectedIds: [],
    preferenceTurnIdx: 0,
    preferenceAnswers: [],
  });
  const opener: StreamScript = [
    { type: 'stage_start' },
    ...sourcingTokens(
      `Kicking off sourcing for ${roleTitle}. I'll ask a couple of quick questions to lock in the ICP, then I'll draft the strategy and start scanning channels.`,
    ),
    { type: 'stage_end', nextStage: 'preferences_chat' },
  ];
  await drainSourcingStream('preferences_chat', opener);
  await sleep(300);
  await playPreferenceTurn();
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

// ---------- Sourcing-flow cancellation ----------
//
// Long-running artifact animations (channel scans, candidate streams) are
// driven by `await abortableDelay()` chains that patch the artifact store. When
// the user navigates away mid-flow (e.g. "See the role"), those patches keep
// firing against unmounted components and race with Next's RSC fetch — hence
// the "TypeError: Failed to fetch" console noise. A per-session AbortController
// (keyed by sub-agent id in sub-agent-runner) lets any running flow bail the
// moment we kick a new one or the canvas unmounts. The canvas unmount-cancel
// effect calls `cancelSourcingRun`.

export function cancelSourcingRun(): void {
  cancelRun('sourcing');
}

const TRAIL_DRAFT_STEPS: Array<{ id: string; body: string; durationMs: number }> = [
  { id: 'parse-role', body: 'Parsing role context & JD', durationMs: 420 },
  { id: 'parse-prefs', body: 'Locking in your preferences', durationMs: 360 },
  { id: 'icp', body: 'Building ICP vector from role + preferences', durationMs: 560 },
  { id: 'dedupe', body: 'Loading your existing pipeline for dedupe', durationMs: 360 },
  { id: 'doc', body: 'Drafting sourcing strategy document', durationMs: 420 },
];

const TRAIL_SCAN_STEPS: Array<{
  id: string;
  body: string;
  channelId: string;
}> = [
  { id: 'linkedin', body: 'Scanning LinkedIn Recruiter', channelId: 'linkedin' },
  {
    id: 'greenhouse-pool',
    body: 'Pulling Greenhouse talent pool + rescoring past candidates',
    channelId: 'greenhouse-pool',
  },
  { id: 'referrals', body: 'Checking referrals network for warm intros', channelId: 'referrals' },
  {
    id: 'wellfound',
    body: 'Running a Wellfound x Google X-ray for actively-looking PMs',
    channelId: 'wellfound',
  },
];

const TRAIL_RANK_STEPS: Array<{ id: string; body: string; durationMs: number }> = [
  { id: 'dedup', body: 'Deduping across channels & ATS history', durationMs: 360 },
  { id: 'score', body: 'Scoring each profile against the ICP', durationMs: 520 },
  { id: 'rank', body: 'Ranking top 5 · attaching evidence highlights', durationMs: 420 },
];

function buildInitialTrail(): SourcingStrategyArtifactData['trailSteps'] {
  const steps: SourcingStrategyArtifactData['trailSteps'] = [];
  for (const s of TRAIL_DRAFT_STEPS) {
    steps.push({ id: `draft-${s.id}`, label: 'draft', body: s.body, status: 'pending' });
  }
  for (const s of TRAIL_SCAN_STEPS) {
    steps.push({ id: `scan-${s.id}`, label: 'scan', body: s.body, status: 'pending' });
  }
  for (const s of TRAIL_RANK_STEPS) {
    steps.push({ id: `rank-${s.id}`, label: 'rank', body: s.body, status: 'pending' });
  }
  return steps;
}

function patchStrategy(patch: Partial<SourcingStrategyArtifactData>): void {
  useArtifactStore
    .getState()
    .patchArtifact(SOURCING_STRATEGY_ARTIFACT_ID, patch as Record<string, unknown>);
}

function updateTrailStep(
  stepId: string,
  update: Partial<SourcingStrategyArtifactData['trailSteps'][number]>,
): void {
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return;
  const next = data.trailSteps.map((s) => (s.id === stepId ? { ...s, ...update } : s));
  patchStrategy({ trailSteps: next });
}

export async function runStrategyAndChannels(userPreferences?: string | null): Promise<void> {
  const signal = beginRun('sourcing');
  const selections = getSelections();
  const roleId = selections.roleId ?? null;
  const roleTitle =
    selections.roleTitle ??
    (selections.mode === 'fresh' && selections.queryText
      ? roleTitleFromQuery(selections.queryText)
      : null);
  const prefs = userPreferences?.trim() ? userPreferences.trim() : null;
  const base = baseStrategyData(roleId, roleTitle, prefs);
  base.trailSteps = buildInitialTrail();
  base.trailVisible = true;
  const artifacts = useArtifactStore.getState();
  const sessions = useSessionStore.getState();

  artifacts.openArtifact({
    id: SOURCING_STRATEGY_ARTIFACT_ID,
    type: 'sourcing-strategy',
    title: roleTitle ? `Sourcing Strategy · ${roleTitle}` : 'Sourcing Strategy · v1',
    initialData: base,
  });
  sessions.setArtifactId('sourcing', SOURCING_STRATEGY_ARTIFACT_ID);
  sessions.setStage('sourcing', 'strategy_publish');

  sessions.appendMessage(
    'sourcing',
    makeMessage(
      'agent',
      prefs
        ? "Locked in your preferences. Drafting the sourcing strategy on the right — you'll see my thinking trail as it runs."
        : "Drafting the sourcing strategy on the right — you'll see my thinking trail as it runs.",
    ),
  );

  // Phase 1: drafting — walk through trail steps. Each step unveils a new
  // section of the strategy doc, so pacing here matters. Keep it deliberate.
  for (const step of TRAIL_DRAFT_STEPS) {
    if (signal.aborted) return;
    const stepId = `draft-${step.id}`;
    updateTrailStep(stepId, { status: 'running' });
    await abortableDelay(step.durationMs, signal);
    if (signal.aborted) return;
    updateTrailStep(stepId, { status: 'done' });
    // Breathing room so users can see each section unveil.
    await abortableDelay(350, signal);
  }

  await abortableDelay(600, signal);
  if (signal.aborted) return;

  // Phase 2: scanning channels — keep patch frequency low so React doesn't
  // thrash during the progress bar animation.
  sessions.setStage('sourcing', 'channel_stream');
  patchStrategy({ phase: 'scanning' });
  const working = base.channels.map((c) => ({ ...c }));

  const patchChannel = (ch: SourcingChannelMut) => {
    // Only swap the channel reference that changed — the rest keep their
    // stable object identity so React.memo on ChannelCard works.
    const next = working.map((x) => (x.id === ch.id ? { ...ch } : x));
    patchStrategy({ channels: next });
  };

  for (let i = 0; i < TRAIL_SCAN_STEPS.length; i += 1) {
    if (signal.aborted) return;
    const scan = TRAIL_SCAN_STEPS[i];
    if (!scan) continue;
    const ch = working.find((c) => c.id === scan.channelId);
    if (!ch) continue;
    const trailId = `scan-${scan.id}`;

    updateTrailStep(trailId, { status: 'running' });
    ch.status = 'scanning';
    patchChannel(ch);

    const target = ch.totalTarget;
    // Lower tick counts so the scan feels snappy and doesn't flood the store.
    const ticks = target > 500 ? 6 : target > 100 ? 4 : 3;
    for (let t = 1; t <= ticks; t += 1) {
      await abortableDelay(target > 500 ? 140 : 110, signal);
      if (signal.aborted) return;
      const progress = Math.floor((target * t) / ticks);
      ch.scanned = t === ticks ? target : progress;
      patchChannel(ch);
    }
    ch.status = 'done';
    ch.scanned = target;
    patchChannel(ch);
    updateTrailStep(trailId, {
      status: 'done',
      detail: `${target.toLocaleString()} ${ch.statLabel}`,
    });

    // Hold on the strategy tab — do not auto-flip. Users switch manually
    // via the CTA at the bottom or the Candidates tab itself.
    await abortableDelay(260, signal);
  }

  if (signal.aborted) return;

  // Phase 3: ranking — slow and deliberate so the trail is readable.
  await abortableDelay(700, signal);
  if (signal.aborted) return;
  sessions.setStage('sourcing', 'candidate_stream');
  patchStrategy({ phase: 'ranking' });

  for (const step of TRAIL_RANK_STEPS) {
    if (signal.aborted) return;
    const stepId = `rank-${step.id}`;
    updateTrailStep(stepId, { status: 'running' });
    await abortableDelay(step.durationMs, signal);
    if (signal.aborted) return;
    updateTrailStep(stepId, { status: 'done' });
    await abortableDelay(220, signal);
  }

  // Phase 4: candidates stream in behind the scenes (user is still on
  // Strategy tab — they'll switch via the CTA).
  const rollingCands: typeof SOURCING_STRATEGY_CANDIDATES = [];
  for (const c of SOURCING_STRATEGY_CANDIDATES) {
    if (signal.aborted) return;
    rollingCands.push(c);
    patchStrategy({
      candidates: [...rollingCands],
      selectedCandidateIds: rollingCands.map((x) => x.id),
    });
    await abortableDelay(280, signal);
  }

  if (signal.aborted) return;
  await abortableDelay(520, signal);
  if (signal.aborted) return;
  patchStrategy({
    phase: 'awaiting_selection',
    trailVisible: false,
  });
  artifacts.completeArtifact(SOURCING_STRATEGY_ARTIFACT_ID);
  sessions.setStage('sourcing', 'offer_add');

  sessions.appendMessage(
    'sourcing',
    makeMessage(
      'agent',
      `Candidates sourced successfully. ${SOURCING_STRATEGY_CANDIDATES.length} matches are ready — tap "View candidates" on the strategy tab (or the Candidates tab) to review and add them to the pipeline.`,
    ),
  );

  await saveStrategyToRole();
}

type SourcingChannelMut = SourcingStrategyArtifactData['channels'][number];

async function saveStrategyToRole(): Promise<void> {
  const selections = getSelections();
  const roleId = selections.roleId;
  if (!roleId) return;
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return;
  try {
    const saved = await (await import('@/services')).requisitions.saveSourcingStrategy(roleId, {
      id: data.strategyId,
      version: data.version,
      owner_name: data.ownerName,
      icp: data.icp,
      target_companies: data.targetCompanies,
      exclude: data.exclude,
      outreach_voice: data.outreachVoice,
      sequence: data.sequence,
      user_preferences: data.userPreferences,
      candidate_count: data.candidates.length,
      total_profiles_label: data.totalProfilesLabel,
    });
    useArtifactStore.getState().patchArtifact(SOURCING_STRATEGY_ARTIFACT_ID, {
      savedToRole: true,
      shareUrl: `/view/roles/${roleId}?strategy=${saved.id}`,
    });
  } catch (err) {
    if (err instanceof ServiceError) {
      console.warn(`[sourcing] save-strategy failed: ${err.code}: ${err.message}`);
    }
  }
}

export function switchStrategyTab(tab: SourcingStrategyArtifactData['activeTab']): void {
  patchStrategy({ activeTab: tab });
}

export function toggleStrategyCandidate(candidateId: string): void {
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return;
  const next = data.selectedCandidateIds.includes(candidateId)
    ? data.selectedCandidateIds.filter((id) => id !== candidateId)
    : [...data.selectedCandidateIds, candidateId];
  useArtifactStore
    .getState()
    .patchArtifact(SOURCING_STRATEGY_ARTIFACT_ID, { selectedCandidateIds: next });
}

export async function submitSourcingPreferences(text: string): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) return;
  const sessions = useSessionStore.getState();
  sessions.appendMessage('sourcing', makeMessage('user', trimmed, 'text', 'chat'));
  appendPref(trimmed);
  setPrefTurnIndex(PREFERENCE_TURNS.length);
  await runStrategyAndChannels(joinedPrefs());
}

function roleTitleFromQuery(queryText: string | undefined): string {
  if (!queryText?.trim()) return 'Sourced role';
  // Grab the leading phrase before a filler — keeps the demo title sensible.
  const clean = queryText.trim().replace(/\s+/g, ' ').slice(0, 80);
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

async function ensureRoleForStrategy(): Promise<{
  roleId: string;
  roleTitle: string;
  created: boolean;
} | null> {
  const selections = getSelections();
  if (selections.roleId && selections.roleTitle) {
    return { roleId: selections.roleId, roleTitle: selections.roleTitle, created: false };
  }
  try {
    const { requisitions } = await import('@/services');
    const title = roleTitleFromQuery(selections.queryText);
    const created = await requisitions.create({
      role_title: title,
      role_location: 'Remote',
      department: 'Product',
      created_by: 'user_1',
      created_by_name: 'Taylor',
      round_template: 'staff_pm_4',
    });
    updateSelections({ roleId: created.id, roleTitle: created.role_title });
    patchStrategy({ roleId: created.id, roleTitle: created.role_title });
    return { roleId: created.id, roleTitle: created.role_title, created: true };
  } catch (err) {
    if (err instanceof ServiceError) {
      console.warn(`[sourcing] auto-create-role failed: ${err.code}: ${err.message}`);
    }
    return null;
  }
}

export async function addStrategyCandidatesToPipeline(): Promise<void> {
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return;
  const toAdd = data.candidates.filter((c) => data.selectedCandidateIds.includes(c.id));
  if (toAdd.length === 0) return;

  const target = await ensureRoleForStrategy();
  if (!target) return;
  const sessions = useSessionStore.getState();

  let imported = 0;
  for (const cand of toAdd) {
    try {
      await candidatesService.create(target.roleId, {
        name: cand.name,
        email: cand.email,
        source: 'openrecruiting-sourcing',
        tags: [...cand.tags, 'sourcing'],
      });
      imported += 1;
    } catch (err) {
      if (err instanceof ServiceError && err.code === 'conflict') continue;
      throw err;
    }
  }

  // Now that a role is definitely bound, re-save the strategy onto it so the
  // Plan tab lists this one too (no-op when the role already had it).
  if (target.created) {
    await saveStrategyToRole();
  }

  useArtifactStore.getState().patchArtifact(SOURCING_STRATEGY_ARTIFACT_ID, {
    phase: 'added',
    addedCount: imported,
  });

  const addedLine =
    imported === 0
      ? 'Those candidates were already in the pipeline — no new adds.'
      : target.created
        ? `Created a new role "${target.roleTitle}" and added ${imported} candidate${imported === 1 ? '' : 's'} to its pipeline at stage "applied".`
        : `Added ${imported} candidate${imported === 1 ? '' : 's'} to the ${target.roleTitle} pipeline at stage "applied".`;

  sessions.appendMessage(
    'sourcing',
    makeMessage('agent', addedLine, undefined, 'scripted', [
      { label: 'See the role · schedule interviews', primary: true, value: 'back_to_role' },
    ]),
  );
}

export function shareStrategyCopyLink(): string | null {
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return null;
  const url = data.shareUrl ?? (typeof window !== 'undefined' ? window.location.href : null) ?? '';
  if (!url) return null;
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(url);
    }
  } catch {
    // swallow — demo.
  }
  return url;
}

export function downloadStrategyJson(): void {
  if (typeof window === 'undefined') return;
  const artifact = useArtifactStore.getState().artifacts[SOURCING_STRATEGY_ARTIFACT_ID];
  const data = (artifact?.data as SourcingStrategyArtifactData | undefined) ?? null;
  if (!data) return;
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `sourcing-strategy-${data.roleTitle?.replace(/\s+/g, '-').toLowerCase() ?? 'v1'}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function rehydrateResults(): Promise<void> {
  const sessions = useSessionStore.getState();
  const session = sessions.sessions.sourcing;
  if (!session) return;
  const selections = getSelections();
  if (!selections.criteria) return;
  const artifacts = useArtifactStore.getState();
  if (artifacts.artifacts[SOURCING_ARTIFACT_ID]) return;
  const filtered = filterByQuery(SOURCING_CANDIDATES, selections.criteria).slice(0, 16);
  artifacts.openArtifact({
    id: SOURCING_ARTIFACT_ID,
    type: 'sourcing-results',
    title: selections.roleTitle ? `Sourcing · ${selections.roleTitle}` : 'Sourcing results',
    initialData: {
      criteria: selections.criteria,
      roleLabel: selections.roleTitle ?? null,
      candidates: filtered,
      selectedIds: selections.selectedIds ?? [],
      totalMatchesLabel: TOTAL_MATCH_COUNT_LABEL,
      page: 0,
      pageSize: 8,
    },
  });
  artifacts.completeArtifact(SOURCING_ARTIFACT_ID);
  useSessionStore.getState().setArtifactId('sourcing', SOURCING_ARTIFACT_ID);
}
