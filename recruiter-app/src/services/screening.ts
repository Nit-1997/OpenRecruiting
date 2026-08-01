// Screening-agent config client.
//
// Routes through the SAME shared `v2Client` (getV2ApiBase + 401-refresh) every
// other recruiter service uses. The backend speaks snake_case; this module owns
// the snake↔camel boundary so the rest of the app (store, UI) stays camelCase —
// matching how the requisitions service maps at its own boundary.
//
// Endpoints (all under /api/v2/roles/{req}/rounds/{round}/screening):
//   POST .../generate  → draft config (NOT persisted)
//   GET  ...           → saved config or null
//   PUT  ...           → save config
//   POST .../attach    → enabled = true
//   POST .../detach    → enabled = false
//   POST .../invite    → send screening invites
//   POST .../persona/derive → reduce the org's interviewer style from Cortex
//   GET  .../persona        → the round's current persona (or empty)
//   PUT  .../persona        → recompose + save the edited rubric

import { v2Client } from '@/lib/v2-client';

export type ScreeningDeployScope = 'all_resume_passed' | string;

export interface ScreeningQuestion {
  /** Server-assigned id; absent on freshly generated drafts. */
  id?: string;
  orderIndex: number;
  title: string;
  prompt: string;
  probe: string;
  signal: string;
  dimension: string;
  durationMinutes: number;
}

export interface ScreeningConfig {
  roundId: string;
  enabled: boolean;
  voice: string;
  followUpStyle: string;
  // Backend column is nullable (int | None); null when no draft has set it yet.
  estDurationMinutes: number | null;
  validityDays: number;
  deployScope: ScreeningDeployScope;
  questions: ScreeningQuestion[];
}

export interface GenerateScreeningBody {
  preferences?: string;
}

/** Proactive "OpenRecruiting sees recurring gaps — add a screen?" nudge for a role. */
export interface ScreeningSuggestion {
  shouldSuggest: boolean;
  reason: string;
  targetRoundId: string | null;
}

export interface InviteScreeningBody {
  emails?: string[];
  scope?: ScreeningDeployScope;
}

// ---- Persona (interviewer style rubric) -------------------------------------

/** `cortex` = derived from interview history, `generic` = low-confidence
 *  fallback, `recruiter` = manually edited. */
export type PersonaSource = 'cortex' | 'generic' | 'recruiter';

export interface PersonaDimension {
  /** One of the 5 fixed keys: tone_rapport | probing_depth | eval_priorities |
   *  must_haves | structure. */
  key: string;
  value: string;
  /** 0..1. */
  confidence: number;
  source: PersonaSource;
}

export interface Persona {
  /** null when no persona is attached to the round yet. */
  personaId: string | null;
  dimensions: PersonaDimension[];
  composedText: string;
}

export interface SavePersonaBody {
  dimensions: PersonaDimension[];
}

// ---- Intake (pre-publish, draft) --------------------------------------------
//
// During intake the round has no DB id yet, so screening is configured against
// the SESSION and the result is stored in the plan artifact (carried at publish,
// materialized server-side). These are RETURN-ONLY drafts: nothing is persisted
// until publish. See `lib/screening-eligibility.ts` for the eligibility rule and
// `intake/use-interview-plan-editor` for where the draft lives in the plan.

export interface GenerateScreeningDraftBody {
  roundName: string;
  category: string;
  skills?: string[];
  preferences?: string;
}

/** The persona snapshot the backend persists at publish: dimensions + the
 *  composed runtime text. Stored verbatim in the plan artifact. */
export interface PersonaSnapshot {
  dimensions: PersonaDimension[];
  text: string;
}

/** A persona derived during intake — carries the snapshot the plan artifact
 *  stores (publish persists + attaches it to the materialized round config). */
export interface DraftPersona extends Persona {
  snapshot: PersonaSnapshot;
}

// ---- Persona library (saved/reusable org personas) --------------------------

/** A saved org persona, as returned by the library CRUD routes. */
export interface PersonaLibraryItem {
  id: string;
  name: string | null;
  dimensions: PersonaDimension[];
  composedText: string;
  isTemplate: boolean;
  /** null for org-level templates. */
  requisitionId: string | null;
  derivedAt: string | null;
}

export interface CreatePersonaBody {
  name?: string | null;
  dimensions: PersonaDimension[];
  isTemplate?: boolean;
}

export interface UpdatePersonaBody {
  name?: string | null;
  dimensions?: PersonaDimension[];
  isTemplate?: boolean;
}

// ---- snake_case wire shapes (what the backend actually sends/expects) --------

interface ScreeningQuestionWire {
  id?: string;
  order_index: number;
  title: string;
  prompt: string;
  probe: string;
  signal: string;
  dimension: string;
  duration_minutes: number;
}

interface ScreeningSuggestionWire {
  should_suggest: boolean;
  reason: string;
  target_round_id: string | null;
}

interface ScreeningConfigWire {
  round_id: string;
  enabled: boolean;
  voice: string;
  follow_up_style: string;
  est_duration_minutes: number | null;
  validity_days: number;
  deploy_scope: ScreeningDeployScope;
  questions: ScreeningQuestionWire[];
}

interface PersonaDimensionWire {
  key: string;
  value: string;
  confidence: number;
  source: string;
}

interface PersonaWire {
  persona_id: string | null;
  dimensions: PersonaDimensionWire[];
  composed_text: string;
}

interface PersonaSnapshotWire {
  dimensions: PersonaDimensionWire[];
  text: string;
}

interface IntakeScreeningQuestionsWire {
  questions: ScreeningQuestionWire[];
}

interface IntakePersonaWire extends PersonaWire {
  persona_snapshot: PersonaSnapshotWire;
}

interface PersonaLibraryItemWire {
  id: string;
  name: string | null;
  dimensions: PersonaDimensionWire[];
  composed_text: string;
  is_template: boolean;
  requisition_id: string | null;
  derived_at: string | null;
}

// ---- boundary mappers -------------------------------------------------------

function questionFromWire(q: ScreeningQuestionWire): ScreeningQuestion {
  const out: ScreeningQuestion = {
    orderIndex: q.order_index,
    title: q.title,
    prompt: q.prompt,
    probe: q.probe,
    signal: q.signal,
    dimension: q.dimension,
    durationMinutes: q.duration_minutes,
  };
  if (q.id !== undefined) out.id = q.id;
  return out;
}

function questionToWire(q: ScreeningQuestion): ScreeningQuestionWire {
  const out: ScreeningQuestionWire = {
    order_index: q.orderIndex,
    title: q.title,
    prompt: q.prompt,
    probe: q.probe,
    signal: q.signal,
    dimension: q.dimension,
    duration_minutes: q.durationMinutes,
  };
  if (q.id !== undefined) out.id = q.id;
  return out;
}

function configFromWire(c: ScreeningConfigWire | null | undefined): ScreeningConfig {
  // Defense in depth: a null/empty response (e.g. attach/detach hitting a
  // missing config row) must surface a CLEAR error, not a cryptic
  // "Cannot read properties of null (reading 'round_id')" TypeError.
  if (!c) throw new Error('No screening config returned');
  return {
    roundId: c.round_id,
    enabled: c.enabled,
    voice: c.voice,
    followUpStyle: c.follow_up_style,
    estDurationMinutes: c.est_duration_minutes,
    validityDays: c.validity_days,
    deployScope: c.deploy_scope,
    questions: (c.questions ?? []).map(questionFromWire),
  };
}

function configToWire(c: ScreeningConfig): ScreeningConfigWire {
  return {
    round_id: c.roundId,
    enabled: c.enabled,
    voice: c.voice,
    follow_up_style: c.followUpStyle,
    est_duration_minutes: c.estDurationMinutes,
    validity_days: c.validityDays,
    deploy_scope: c.deployScope,
    questions: c.questions.map(questionToWire),
  };
}

function personaFromWire(p: PersonaWire | null | undefined): Persona {
  if (!p) throw new Error('No persona returned');
  return {
    personaId: p.persona_id ?? null,
    composedText: p.composed_text ?? '',
    dimensions: (p.dimensions ?? []).map((d) => ({
      key: d.key,
      value: d.value,
      confidence: d.confidence,
      source: d.source as PersonaSource,
    })),
  };
}

function dimensionsFromWire(dims: PersonaDimensionWire[]): PersonaDimension[] {
  return (dims ?? []).map((d) => ({
    key: d.key,
    value: d.value,
    confidence: d.confidence,
    source: d.source as PersonaSource,
  }));
}

function snapshotFromWire(s: PersonaSnapshotWire | undefined): PersonaSnapshot {
  return {
    dimensions: dimensionsFromWire(s?.dimensions ?? []),
    text: s?.text ?? '',
  };
}

function libraryItemFromWire(p: PersonaLibraryItemWire): PersonaLibraryItem {
  return {
    id: p.id,
    name: p.name ?? null,
    composedText: p.composed_text ?? '',
    isTemplate: Boolean(p.is_template),
    requisitionId: p.requisition_id ?? null,
    derivedAt: p.derived_at ?? null,
    dimensions: dimensionsFromWire(p.dimensions),
  };
}

function basePath(req: string, round: string): string {
  return `/api/v2/roles/${req}/rounds/${round}/screening`;
}

// ---- API surface ------------------------------------------------------------

/** Draft a config from the round's plan. NOT persisted — caller saves it. */
export async function generateScreening(
  req: string,
  round: string,
  body?: GenerateScreeningBody,
): Promise<ScreeningConfig> {
  const wire = await v2Client.post<ScreeningConfigWire>(
    `${basePath(req, round)}/generate`,
    body ?? {},
  );
  return configFromWire(wire);
}

/** Saved config for the round, or null when none exists yet. */
export async function getScreening(req: string, round: string): Promise<ScreeningConfig | null> {
  const wire = await v2Client.get<ScreeningConfigWire | null>(basePath(req, round));
  return wire ? configFromWire(wire) : null;
}

/** Proactive "add a screen?" nudge for the role, driven by recurring Cortex
 *  gaps. Role-level (not round-level). Always safe — the backend returns
 *  shouldSuggest=false on cold start / no pattern / a screen already enabled. */
export async function getScreeningSuggestion(req: string): Promise<ScreeningSuggestion> {
  const wire = await v2Client.get<ScreeningSuggestionWire>(
    `/api/v2/roles/${req}/screening/suggestion`,
  );
  return {
    shouldSuggest: wire.should_suggest,
    reason: wire.reason ?? '',
    targetRoundId: wire.target_round_id ?? null,
  };
}

/** Persist the full config (idempotent upsert). */
export async function saveScreening(
  req: string,
  round: string,
  config: ScreeningConfig,
): Promise<ScreeningConfig> {
  const wire = await v2Client.put<ScreeningConfigWire>(basePath(req, round), configToWire(config));
  return configFromWire(wire);
}

/** Toggle enabled = true. Returns the resulting config. */
export async function attachScreening(req: string, round: string): Promise<ScreeningConfig> {
  const wire = await v2Client.post<ScreeningConfigWire>(`${basePath(req, round)}/attach`);
  return configFromWire(wire);
}

/** Toggle enabled = false. Returns the resulting config. */
export async function detachScreening(req: string, round: string): Promise<ScreeningConfig> {
  const wire = await v2Client.post<ScreeningConfigWire>(`${basePath(req, round)}/detach`);
  return configFromWire(wire);
}

/** Send screening invites to specific emails or a deploy scope. */
export async function inviteScreening(
  req: string,
  round: string,
  body?: InviteScreeningBody,
): Promise<void> {
  await v2Client.post<void>(`${basePath(req, round)}/invite`, body ?? {});
}

/** The minted screening invite for a single candidate_round — what
 *  "scheduling" a AI-hosted round returns. `verifyUrl` is the copy-link the
 *  recruiter can share when email isn't configured locally. */
export interface CandidateRoundInvite {
  token: string;
  expiresAt: string;
  verifyUrl: string;
  validityDays: number;
}

interface CandidateRoundInviteWire {
  token: string;
  expires_at: string;
  verify_url: string;
  validity_days: number;
}

/** "Schedule" a AI-hosted round for ONE existing candidate_round: send (or
 *  re-send) that candidate the async screening link. No booked time, no human
 *  interviewer, no meeting URL — the open-window model. Returns the verify link
 *  + validity window so the UI can show success + a copy affordance. */
export async function inviteCandidateRound(
  candidateRoundId: string,
): Promise<CandidateRoundInvite> {
  const wire = await v2Client.post<CandidateRoundInviteWire>(
    `/api/v2/screening/candidate-rounds/${candidateRoundId}/invite`,
  );
  return {
    token: wire.token,
    expiresAt: wire.expires_at,
    verifyUrl: wire.verify_url,
    validityDays: wire.validity_days,
  };
}

/** REDUCE the org's real interviewer style (from Cortex) into a per-round
 *  persona rubric and attach it to the round config. Always safe — falls back
 *  to a generic persona when there's no Cortex data. */
export async function derivePersona(req: string, round: string): Promise<Persona> {
  const wire = await v2Client.post<PersonaWire>(`${basePath(req, round)}/persona/derive`);
  return personaFromWire(wire);
}

/** The round's currently-attached persona, or an empty persona when none. */
export async function getPersona(req: string, round: string): Promise<Persona> {
  const wire = await v2Client.get<PersonaWire>(`${basePath(req, round)}/persona`);
  return personaFromWire(wire);
}

/** Recompose + persist the recruiter-edited rubric. */
export async function savePersona(
  req: string,
  round: string,
  body: SavePersonaBody,
): Promise<Persona> {
  const wire = await v2Client.put<PersonaWire>(`${basePath(req, round)}/persona`, {
    dimensions: body.dimensions,
  });
  return personaFromWire(wire);
}

// ---- Intake (pre-publish, draft) --------------------------------------------

/** Generate draft screening questions for a plan round DURING intake (no round
 *  id exists yet). RETURN-ONLY — the caller stores the result in the plan
 *  artifact; publish materializes it. */
export async function generateScreeningDraft(
  sessionId: string,
  body: GenerateScreeningDraftBody,
): Promise<ScreeningQuestion[]> {
  const wire = await v2Client.post<IntakeScreeningQuestionsWire>(
    `/api/v2/intake/sessions/${sessionId}/screening/generate`,
    {
      round_name: body.roundName,
      category: body.category,
      ...(body.skills !== undefined ? { skills: body.skills } : {}),
      ...(body.preferences !== undefined ? { preferences: body.preferences } : {}),
    },
  );
  return (wire.questions ?? []).map(questionFromWire);
}

/** Derive an interviewer persona for a plan round DURING intake. Cold-start
 *  safe (returns a generic persona). RETURN-ONLY — the caller stores the
 *  `snapshot` in the plan artifact; publish persists + attaches it. */
export async function derivePersonaDraft(sessionId: string): Promise<DraftPersona> {
  const wire = await v2Client.post<IntakePersonaWire>(
    `/api/v2/intake/sessions/${sessionId}/screening/persona/derive`,
  );
  return {
    ...personaFromWire(wire),
    snapshot: snapshotFromWire(wire.persona_snapshot),
  };
}

/** Map a per-round screening artifact (camelCase) to the snake_case shape the
 *  publish endpoint materializes (intake_publish_service._materialize_screening).
 *  Imported by the plan editor to convert the `screening` it stores on each round
 *  right before publish. `import('@/types/intake').RoundScreening` is typed
 *  loosely here to avoid a types↔services import cycle. */
export function roundScreeningToWire(s: {
  enabled: boolean;
  voice: string;
  followUpStyle: string;
  validityDays: number;
  questions: ScreeningQuestion[];
  personaSnapshot?: PersonaSnapshot;
}): Record<string, unknown> {
  const wire: Record<string, unknown> = {
    enabled: s.enabled,
    voice: s.voice,
    follow_up_style: s.followUpStyle,
    validity_days: s.validityDays,
    questions: s.questions.map(questionToWire),
  };
  if (s.personaSnapshot) {
    wire.persona_snapshot = {
      dimensions: s.personaSnapshot.dimensions,
      text: s.personaSnapshot.text,
    };
  }
  return wire;
}

// ---- Persona library (saved/reusable org personas) --------------------------

/** Attach an existing saved persona to this round (the picker's "Use this
 *  persona"). Returns the applied persona. */
export async function selectPersona(
  req: string,
  round: string,
  personaId: string,
): Promise<Persona> {
  const wire = await v2Client.post<PersonaWire>(`${basePath(req, round)}/persona/select`, {
    persona_id: personaId,
  });
  return personaFromWire(wire);
}

/** List the org's saved personas (optionally only reusable templates). */
export async function listPersonas(opts?: { templates?: boolean }): Promise<PersonaLibraryItem[]> {
  const qs = opts?.templates ? '?templates=true' : '';
  const wire = await v2Client.get<PersonaLibraryItemWire[]>(`/api/v2/personas${qs}`);
  return (wire ?? []).map(libraryItemFromWire);
}

/** Create a saved persona (composed_text is rendered server-side). Set
 *  `isTemplate` to save it as a reusable org template. */
export async function createPersona(body: CreatePersonaBody): Promise<PersonaLibraryItem> {
  const wire = await v2Client.post<PersonaLibraryItemWire>('/api/v2/personas', {
    name: body.name ?? null,
    dimensions: body.dimensions,
    is_template: body.isTemplate ?? false,
  });
  return libraryItemFromWire(wire);
}

/** Update a saved persona (recomposes server-side when dimensions change). */
export async function updatePersona(
  id: string,
  body: UpdatePersonaBody,
): Promise<PersonaLibraryItem> {
  const payload: Record<string, unknown> = {};
  if (body.name !== undefined) payload.name = body.name;
  if (body.dimensions !== undefined) payload.dimensions = body.dimensions;
  if (body.isTemplate !== undefined) payload.is_template = body.isTemplate;
  const wire = await v2Client.put<PersonaLibraryItemWire>(`/api/v2/personas/${id}`, payload);
  return libraryItemFromWire(wire);
}

/** Hard-delete a saved persona. */
export async function deletePersona(id: string): Promise<void> {
  await v2Client.delete<void>(`/api/v2/personas/${id}`);
}
