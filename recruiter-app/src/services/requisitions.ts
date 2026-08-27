import type {
  FeedbackQuestion,
  QuestionCreateInput,
  QuestionUpdateInput,
  Requisition,
  RequisitionCreateInput,
  RequisitionStatus,
  RequisitionUpdateInput,
  Round,
  RoundCreateInput,
  RoundTemplateKey,
  RoundUpdateInput,
  ScreeningAgentQuestion,
  SourcingStrategyRecord,
} from '@/domain';
import {
  SCREENING_AGENT_DEPLOY,
  SCREENING_AGENT_FOLLOWUP,
  SCREENING_AGENT_VOICE,
} from '@/fixtures/screening';
import { isV2ApiEnabled } from '@/lib/env';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import { notImplementedInV2, ServiceError } from './service-error';

const ORG_ID = 'org_1';
const OWNER_ID = 'user_1';

interface TemplateRound {
  name: string;
  category: Round['category'];
  duration_minutes: number;
}

const TEMPLATES: Record<RoundTemplateKey, TemplateRound[]> = {
  staff_pm_4: [
    { name: 'Recruiter screen', category: 'screening', duration_minutes: 30 },
    { name: 'Hiring manager', category: 'behavioral', duration_minutes: 45 },
    { name: 'Product panel', category: 'panel', duration_minutes: 60 },
    { name: 'Culture + values', category: 'culture', duration_minutes: 45 },
  ],
  senior_eng_5: [
    { name: 'Recruiter screen', category: 'screening', duration_minutes: 30 },
    { name: 'Coding', category: 'technical', duration_minutes: 60 },
    { name: 'System design', category: 'technical', duration_minutes: 60 },
    { name: 'Behavioral', category: 'behavioral', duration_minutes: 45 },
    { name: 'Hiring committee', category: 'final', duration_minutes: 45 },
  ],
  design_eng_4: [
    { name: 'Recruiter screen', category: 'screening', duration_minutes: 30 },
    { name: 'Portfolio review', category: 'behavioral', duration_minutes: 45 },
    { name: 'Pairing', category: 'technical', duration_minutes: 60 },
    { name: 'Culture + craft', category: 'culture', duration_minutes: 45 },
  ],
  leader_6: [
    { name: 'Recruiter screen', category: 'screening', duration_minutes: 30 },
    { name: 'VP round', category: 'behavioral', duration_minutes: 45 },
    { name: 'Peer panel', category: 'panel', duration_minutes: 60 },
    { name: 'Strategy deep dive', category: 'behavioral', duration_minutes: 60 },
    { name: 'Culture', category: 'culture', duration_minutes: 45 },
    { name: 'CEO', category: 'final', duration_minutes: 30 },
  ],
};

// The v2 plan-read wire (`PlanRoundResponse`) is snake_case and structurally
// matches `@/domain` Round for every field EXCEPT screening eligibility, which
// the backend sends as `ai_screenable` / `ai_screenable_reason`. Map those
// to the camelCase `@/domain` fields here so the dashboard surface reads them
// the same way the intake `@/types` Round does. Other fields pass through.
interface PlanRoundWire extends Round {
  ai_screenable?: boolean;
  ai_screenable_reason?: string | null;
}

function mapPlanRound(wire: PlanRoundWire): Round {
  const { ai_screenable, ai_screenable_reason, ...rest } = wire;
  const round: Round = { ...rest };
  if (ai_screenable !== undefined) round.aiScreenable = ai_screenable;
  if (ai_screenable_reason !== undefined) {
    round.aiScreenableReason = ai_screenable_reason;
  }
  return round;
}

function templateRounds(reqId: string, template: RoundTemplateKey | undefined): Round[] {
  const chosen = TEMPLATES[template ?? 'staff_pm_4'];
  const now = nowIso();
  return chosen.map((t, i) => ({
    id: `${reqId}_round_${i + 1}`,
    requisition_id: reqId,
    round_number: i + 1,
    name: t.name,
    category: t.category,
    duration_minutes: t.duration_minutes,
    skills: [],
    guidelines: [],
    feedback_questions: [],
    created_at: now,
    updated_at: now,
  }));
}

/**
 * Canonical requisition status per spec §15. UI tab labels map to these:
 *   Open    → 'planned'
 *   Pending → 'intake_pending'
 *   Closed  → 'closed'
 * Omit to fetch all statuses.
 */
export type RequisitionStatusFilter = 'planned' | 'intake_pending' | 'closed';

/**
 * Per-row pipeline summary returned in the LIST response. Lets the rail
 * render `N candidates · M rounds` without firing an additional fetch per
 * row (previously useCandidatesForRequisition caused an N+1).
 */
export interface RolePipelineCounts {
  round_count: number;
  candidate_count: number;
}

/**
 * Status badge counts surfaced once per LIST response. Keys are
 * UI-friendly aliases of canonical status:
 *   open    ← planned
 *   pending ← intake_pending
 *   closed  ← closed
 */
export interface RoleStatusCounts {
  open: number;
  pending: number;
  closed: number;
}

/**
 * Item shape from GET /api/v2/roles. Carries the role header plus
 * `pipeline` for the rail; full `rounds` are not included (the plan tab
 * fetches them separately via /plan).
 */
export interface RoleListItem extends Requisition {
  pipeline: RolePipelineCounts;
}

export interface RoleListPage {
  items: RoleListItem[];
  page: number;
  page_size: number;
  total: number;
  status_counts: RoleStatusCounts;
}

export interface ListRolesOptions {
  page?: number;
  page_size?: number;
  /**
   * Case-insensitive substring search applied server-side across role_title
   * and role_location. Returns matching roles from the entire org, not just
   * the current page slice. `status_counts` on the response stays org-wide.
   * Explicit `| undefined` so callers can pass a falsy-cleared query under
   * `exactOptionalPropertyTypes`.
   */
  q?: string | undefined;
}

const DEFAULT_PAGE_SIZE = 10;

function emptyPipeline(): RolePipelineCounts {
  return { round_count: 0, candidate_count: 0 };
}

function statusCountsFromAll(all: Requisition[]): RoleStatusCounts {
  return {
    open: all.filter((r) => r.status === 'planned').length,
    pending: all.filter((r) => r.status === 'intake_pending').length,
    closed: all.filter((r) => r.status === 'closed').length,
  };
}

export async function list(
  status?: RequisitionStatusFilter,
  options?: ListRolesOptions,
): Promise<RoleListPage> {
  const page = Math.max(options?.page ?? 1, 1);
  const pageSize = Math.max(Math.min(options?.page_size ?? DEFAULT_PAGE_SIZE, 100), 1);
  const q = options?.q?.trim() || undefined;

  if (isV2ApiEnabled()) {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    if (q) params.set('q', q);
    const result = await v2Client.get<{
      items: Array<Partial<RoleListItem> & { id: string }>;
      page: number;
      page_size: number;
      total: number;
      status_counts: RoleStatusCounts;
    }>(`/api/v2/roles?${params.toString()}`);
    const items: RoleListItem[] = (result.items ?? []).map((r) => ({
      ...(r as RoleListItem),
      rounds: r.rounds ?? [],
      pipeline: r.pipeline ?? emptyPipeline(),
    }));
    return {
      items,
      page: result.page,
      page_size: result.page_size,
      total: result.total,
      status_counts: result.status_counts,
    };
  }

  await simulate();
  const all = structuredClone(getDb().requisitions);
  const statusFiltered = status ? all.filter((r) => r.status === status) : all;
  // Mock-path mirrors the backend filter: role_title + role_location ilike.
  const needle = q?.toLowerCase();
  const filtered = needle
    ? statusFiltered.filter(
        (r) =>
          (r.role_title ?? '').toLowerCase().includes(needle) ||
          (r.role_location ?? '').toLowerCase().includes(needle),
      )
    : statusFiltered;
  const start = (page - 1) * pageSize;
  const sliced = filtered.slice(start, start + pageSize);
  // Mock-path: compute pipeline counts from the seeded DB so the FE sees
  // the same shape it gets from v2.
  const candidatesByReq = getDb().candidates.reduce<Record<string, number>>((acc, c) => {
    const key = c.requisition_id;
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const items: RoleListItem[] = sliced.map((r) => ({
    ...r,
    pipeline: {
      round_count: r.rounds.filter((rd) => !rd.for_candidate_id && !rd.removed_from_plan_at).length,
      candidate_count: candidatesByReq[r.id] ?? 0,
    },
  }));
  return {
    items,
    page,
    page_size: pageSize,
    total: filtered.length,
    status_counts: statusCountsFromAll(all),
  };
}

export async function get(id: string): Promise<Requisition> {
  if (isV2ApiEnabled()) {
    // v2 `GET /roles/{id}` returns the header only; rounds aren't included.
    // We fetch the plan in parallel to preserve the mock's "full requisition"
    // shape so existing call sites keep working unchanged.
    const [header, plan] = await Promise.all([
      v2Client.get<Partial<Requisition> & { id: string }>(`/api/v2/roles/${id}`),
      v2Client.get<{ rounds: PlanRoundWire[] }>(`/api/v2/roles/${id}/plan`),
    ]);
    return {
      ...(header as Requisition),
      rounds: (plan.rounds ?? []).map(mapPlanRound),
    };
  }
  await simulate();
  const r = getDb().requisitions.find((req) => req.id === id);
  if (!r) throw new ServiceError('not_found', `Requisition ${id} not found`);
  return structuredClone(r);
}

export async function create(input: RequisitionCreateInput): Promise<Requisition> {
  // TODO PR6: backend POST /api/v2/roles is not implemented yet. On the v2
  // path we MUST NOT fall through to the mock — that would create a
  // fabricated localStorage requisition indistinguishable from a real one.
  // Fail loudly so the UI surfaces "not available yet" instead.
  if (isV2ApiEnabled()) throw notImplementedInV2('requisitions.create');
  await simulate();
  if (!input.role_title?.trim()) {
    throw new ServiceError('validation', 'role_title is required', { field: 'role_title' });
  }
  const id = generateId('req');
  const now = nowIso();
  const req: Requisition = {
    id,
    organization_id: ORG_ID,
    role_title: input.role_title.trim(),
    role_location: input.role_location ?? '',
    department: input.department ?? 'Product',
    created_by: input.created_by ?? OWNER_ID,
    created_by_name: input.created_by_name ?? 'Taylor',
    experience_min_years: input.experience_min_years ?? 0,
    experience_max_years: input.experience_max_years ?? null,
    status: 'intake_pending',
    intake_notes: '',
    job_description: input.job_description ?? '',
    must_have_skills: input.must_have_skills ?? [],
    good_to_have_skills: input.good_to_have_skills ?? [],
    rounds: templateRounds(id, input.round_template),
    created_at: now,
    updated_at: now,
  };
  const db = getDb();
  db.requisitions.unshift(req);
  db.activity.unshift({
    id: generateId('act'),
    type: 'role:created',
    title: 'Role created',
    description: `${req.role_title} was opened.`,
    actor_name: req.created_by_name,
    requisition_id: id,
    candidate_id: null,
    created_at: now,
  });
  persist();
  emit('requisition:created', req);
  emit('activity:created');
  return structuredClone(req);
}

export async function update(id: string, patch: RequisitionUpdateInput): Promise<Requisition> {
  await simulate();
  const db = getDb();
  const idx = db.requisitions.findIndex((r) => r.id === id);
  if (idx === -1) throw new ServiceError('not_found', `Requisition ${id} not found`);
  const existing = db.requisitions[idx];
  if (!existing) throw new ServiceError('not_found', `Requisition ${id} not found`);
  const next: Requisition = { ...existing, ...patch, updated_at: nowIso() };
  db.requisitions[idx] = next;
  persist();
  emit('requisition:updated', next);
  return structuredClone(next);
}

// Backend canonical transitions:
//   intake_pending → planned (plan attached), intake_pending → closed (abandoned)
//   planned → intake_pending (rare: re-plan), planned → closed (filled or dropped)
//   closed → planned (reopened)
const VALID_TRANSITIONS: Record<RequisitionStatus, RequisitionStatus[]> = {
  draft: ['intake_pending', 'closed'],
  intake_pending: ['planned', 'closed'],
  planned: ['intake_pending', 'closed'],
  closed: ['planned'],
};

export async function setStatus(id: string, status: RequisitionStatus): Promise<Requisition> {
  if (isV2ApiEnabled()) {
    // v2 only exposes /close and /reopen — both produce a closed↔planned toggle.
    // intake_pending transitions are still handled via the mock path because
    // there's no v2 endpoint for them. Surface validation here rather than
    // bouncing off a 404.
    if (status === 'closed') {
      const next = await v2Client.post<Requisition>(`/api/v2/roles/${id}/close`);
      emit('requisition:status_changed', next);
      return next;
    }
    if (status === 'planned') {
      const next = await v2Client.post<Requisition>(`/api/v2/roles/${id}/reopen`);
      emit('requisition:status_changed', next);
      return next;
    }
    throw new ServiceError(
      'invalid_state',
      `v2 backend does not support transitioning to ${status}`,
    );
  }
  await simulate();
  const db = getDb();
  const idx = db.requisitions.findIndex((r) => r.id === id);
  if (idx === -1) throw new ServiceError('not_found', `Requisition ${id} not found`);
  const existing = db.requisitions[idx];
  if (!existing) throw new ServiceError('not_found', `Requisition ${id} not found`);
  const current = existing.status;
  if (current === status) return structuredClone(existing);
  if (!VALID_TRANSITIONS[current].includes(status)) {
    throw new ServiceError(
      'invalid_state',
      `Cannot transition requisition from ${current} to ${status}`,
    );
  }
  const next: Requisition = { ...existing, status, updated_at: nowIso() };
  db.requisitions[idx] = next;
  db.activity.unshift({
    id: generateId('act'),
    type: 'role:status_changed',
    title: `Role marked ${status}`,
    description: `${next.role_title} → ${status}.`,
    actor_name: next.created_by_name,
    requisition_id: id,
    candidate_id: null,
    created_at: nowIso(),
  });
  persist();
  emit('requisition:status_changed', next);
  emit('activity:created');
  return structuredClone(next);
}

export async function updateIntake(id: string, intake_notes: string): Promise<Requisition> {
  // No v2 endpoint for intake-note edits; delegating to the mock `update`
  // would fabricate a persisted change. Fail loudly on the v2 path.
  if (isV2ApiEnabled()) throw notImplementedInV2('requisitions.updateIntake');
  return update(id, { intake_notes });
}

export async function getPlan(id: string): Promise<Round[]> {
  if (isV2ApiEnabled()) {
    // Spec §4 read: GET /roles/{id}/plan returns `{ rounds: [...] }`. Unwrap
    // to match the mock's array return signature.
    const result = await v2Client.get<{ rounds: PlanRoundWire[] }>(`/api/v2/roles/${id}/plan`);
    return (result.rounds ?? []).map(mapPlanRound);
  }
  await simulate();
  const r = getDb().requisitions.find((req) => req.id === id);
  if (!r) throw new ServiceError('not_found', `Requisition ${id} not found`);
  return structuredClone(r.rounds);
}

export async function addRound(reqId: string, input: RoundCreateInput): Promise<Round> {
  if (isV2ApiEnabled()) {
    const round = await v2Client.post<Round>(`/api/v2/roles/${reqId}/plan/rounds`, input);
    emit('round:created', round);
    return round;
  }
  await simulate();
  if (!input.name?.trim()) {
    throw new ServiceError('validation', 'name is required', { field: 'name' });
  }
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const position =
    input.position !== undefined
      ? Math.max(0, Math.min(input.position, req.rounds.length))
      : req.rounds.length;
  const now = nowIso();
  const round: Round = {
    id: generateId('round'),
    requisition_id: reqId,
    round_number: position + 1,
    name: input.name.trim(),
    category: input.category,
    duration_minutes: input.duration_minutes,
    skills: input.skills ?? [],
    guidelines: input.guidelines ?? [],
    feedback_questions: (input.feedback_questions ?? []).map((q, idx) => ({
      id: generateId('q'),
      round_id: '',
      question_number: idx + 1,
      heading: q.heading,
      description: q.description,
    })),
    created_at: now,
    updated_at: now,
  };
  if (input.description !== undefined) round.description = input.description;
  // Stamp round_id on embedded feedback questions now that round.id is known.
  round.feedback_questions.forEach((q) => {
    q.round_id = round.id;
  });
  req.rounds.splice(position, 0, round);
  req.rounds.forEach((r, i) => {
    r.round_number = i + 1;
  });
  req.updated_at = now;
  persist();
  emit('round:created', round);
  return structuredClone(round);
}

export async function updateRound(roundId: string, patch: RoundUpdateInput): Promise<Round> {
  if (isV2ApiEnabled()) {
    const next = await v2Client.put<Round>(`/api/v2/plan/rounds/${roundId}`, patch);
    emit('round:updated', next);
    return next;
  }
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    const idx = req.rounds.findIndex((r) => r.id === roundId);
    if (idx === -1) continue;
    const existing = req.rounds[idx];
    if (!existing) continue;
    const next: Round = { ...existing, ...patch, updated_at: nowIso() };
    req.rounds[idx] = next;
    req.updated_at = nowIso();
    persist();
    emit('round:updated', next);
    return structuredClone(next);
  }
  throw new ServiceError('not_found', `Round ${roundId} not found`);
}

export async function deleteRound(roundId: string): Promise<void> {
  if (isV2ApiEnabled()) {
    await v2Client.delete<{ deleted_round_id: string }>(`/api/v2/plan/rounds/${roundId}`);
    emit('round:deleted', { round_id: roundId });
    return;
  }
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    const idx = req.rounds.findIndex((r) => r.id === roundId);
    if (idx === -1) continue;
    req.rounds.splice(idx, 1);
    req.rounds.forEach((r, i) => {
      r.round_number = i + 1;
    });
    req.updated_at = nowIso();
    db.candidate_rounds = db.candidate_rounds.filter((cr) => cr.round_id !== roundId);
    persist();
    emit('round:deleted', { round_id: roundId });
    return;
  }
  throw new ServiceError('not_found', `Round ${roundId} not found`);
}

export async function reorderRounds(
  reqId: string,
  order: string[],
  etag?: string,
): Promise<Round[]> {
  if (isV2ApiEnabled()) {
    // Resolve the `If-Match` etag. Callers should pass it from the Zustand
    // store; if missing we fetch the plan to read the current max(updated_at).
    // The v2 reorder endpoint returns `{ rounds, etag }` — we surface the new
    // etag back through the event payload so the store can update.
    let ifMatch = etag;
    if (!ifMatch) {
      const plan = await v2Client.get<{ rounds: Round[] }>(`/api/v2/roles/${reqId}/plan`);
      ifMatch = plan.rounds.reduce<string>((acc, r) => {
        const ts = r.updated_at;
        return !acc || ts > acc ? ts : acc;
      }, '');
      if (!ifMatch) {
        throw new ServiceError('invalid_state', 'Cannot reorder: no rounds in plan');
      }
    }
    const payload = order.map((round_id, idx) => ({
      round_id,
      round_number: idx + 1,
    }));
    const result = await v2Client.post<{ rounds: Round[]; etag: string | null }>(
      `/api/v2/roles/${reqId}/plan/rounds/reorder`,
      payload,
      { ifMatch },
    );
    emit('round:reordered', {
      requisition_id: reqId,
      etag: result.etag ?? null,
    });
    return result.rounds;
  }
  await simulate();
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  if (order.length !== req.rounds.length || new Set(order).size !== order.length) {
    throw new ServiceError('validation', 'order must include every round id exactly once');
  }
  const byId = new Map(req.rounds.map((r) => [r.id, r]));
  const next: Round[] = [];
  for (const id of order) {
    const r = byId.get(id);
    if (!r) throw new ServiceError('validation', `Unknown round id ${id}`);
    next.push(r);
  }
  next.forEach((r, i) => {
    r.round_number = i + 1;
  });
  req.rounds = next;
  req.updated_at = nowIso();
  persist();
  emit('round:reordered', { requisition_id: reqId });
  return structuredClone(next);
}

function findRound(roundId: string): Round | null {
  const db = getDb();
  for (const req of db.requisitions) {
    const r = req.rounds.find((x) => x.id === roundId);
    if (r) return r;
  }
  return null;
}

export async function addQuestion(
  roundId: string,
  input: QuestionCreateInput,
): Promise<FeedbackQuestion> {
  if (isV2ApiEnabled()) {
    const q = await v2Client.post<FeedbackQuestion>(
      `/api/v2/plan/rounds/${roundId}/questions`,
      input,
    );
    emit('question:created', q);
    return q;
  }
  await simulate();
  const round = findRound(roundId);
  if (!round) throw new ServiceError('not_found', `Round ${roundId} not found`);
  if (!input.heading?.trim()) {
    throw new ServiceError('validation', 'heading is required', { field: 'heading' });
  }
  const q: FeedbackQuestion = {
    id: generateId('q'),
    round_id: roundId,
    question_number: round.feedback_questions.length + 1,
    heading: input.heading.trim(),
    description: input.description ?? '',
  };
  round.feedback_questions.push(q);
  round.updated_at = nowIso();
  persist();
  emit('question:created', q);
  return structuredClone(q);
}

export async function updateQuestion(
  questionId: string,
  patch: QuestionUpdateInput,
): Promise<FeedbackQuestion> {
  if (isV2ApiEnabled()) {
    const next = await v2Client.put<FeedbackQuestion>(
      `/api/v2/plan/questions/${questionId}`,
      patch,
    );
    emit('question:updated', next);
    return next;
  }
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    for (const round of req.rounds) {
      const idx = round.feedback_questions.findIndex((q) => q.id === questionId);
      if (idx === -1) continue;
      const existing = round.feedback_questions[idx];
      if (!existing) continue;
      const next: FeedbackQuestion = { ...existing, ...patch };
      round.feedback_questions[idx] = next;
      round.updated_at = nowIso();
      persist();
      emit('question:updated', next);
      return structuredClone(next);
    }
  }
  throw new ServiceError('not_found', `Question ${questionId} not found`);
}

export { SCREENING_AGENT_DEPLOY, SCREENING_AGENT_FOLLOWUP, SCREENING_AGENT_VOICE };

export async function attachScreeningAgent(
  roundId: string,
  questions: ScreeningAgentQuestion[],
): Promise<Round> {
  if (isV2ApiEnabled()) throw notImplementedInV2('requisitions.attachScreeningAgent');
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    const idx = req.rounds.findIndex((r) => r.id === roundId);
    if (idx === -1) continue;
    const existing = req.rounds[idx];
    if (!existing) continue;
    const next: Round = {
      ...existing,
      screening_agent_enabled: true,
      screening_agent_voice: SCREENING_AGENT_VOICE,
      screening_agent_questions: structuredClone(questions),
      updated_at: nowIso(),
    };
    req.rounds[idx] = next;
    req.updated_at = nowIso();
    persist();
    emit('round:updated', next);
    return structuredClone(next);
  }
  throw new ServiceError('not_found', `Round ${roundId} not found`);
}

export async function detachScreeningAgent(roundId: string): Promise<Round> {
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    const idx = req.rounds.findIndex((r) => r.id === roundId);
    if (idx === -1) continue;
    const existing = req.rounds[idx];
    if (!existing) continue;
    const next: Round = {
      ...existing,
      screening_agent_enabled: false,
      screening_agent_questions: [],
      updated_at: nowIso(),
    };
    req.rounds[idx] = next;
    req.updated_at = nowIso();
    persist();
    emit('round:updated', next);
    return structuredClone(next);
  }
  throw new ServiceError('not_found', `Round ${roundId} not found`);
}

export async function updateScreeningQuestion(
  roundId: string,
  questionId: string,
  patch: Partial<Omit<ScreeningAgentQuestion, 'id'>>,
): Promise<Round> {
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    const idx = req.rounds.findIndex((r) => r.id === roundId);
    if (idx === -1) continue;
    const existing = req.rounds[idx];
    if (!existing) continue;
    const questions = existing.screening_agent_questions ?? [];
    const qIdx = questions.findIndex((q) => q.id === questionId);
    if (qIdx === -1) {
      throw new ServiceError('not_found', `Screening question ${questionId} not found`);
    }
    const prev = questions[qIdx];
    if (!prev) throw new ServiceError('not_found', `Screening question ${questionId} not found`);
    const nextQuestions = [...questions];
    nextQuestions[qIdx] = { ...prev, ...patch };
    const next: Round = {
      ...existing,
      screening_agent_questions: nextQuestions,
      updated_at: nowIso(),
    };
    req.rounds[idx] = next;
    req.updated_at = nowIso();
    persist();
    emit('round:updated', next);
    return structuredClone(next);
  }
  throw new ServiceError('not_found', `Round ${roundId} not found`);
}

export async function saveSourcingStrategy(
  reqId: string,
  input: Omit<SourcingStrategyRecord, 'created_at'>,
): Promise<SourcingStrategyRecord> {
  if (isV2ApiEnabled()) throw notImplementedInV2('requisitions.saveSourcingStrategy');
  await simulate();
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const now = nowIso();
  const record: SourcingStrategyRecord = { ...input, created_at: now };
  const existing = req.sourcing_strategies ?? [];
  const idx = existing.findIndex((s) => s.id === input.id);
  if (idx === -1) {
    req.sourcing_strategies = [record, ...existing];
  } else {
    const next = [...existing];
    next[idx] = record;
    req.sourcing_strategies = next;
  }
  req.updated_at = now;
  persist();
  emit('requisition:updated', req);
  return structuredClone(record);
}

export async function listSourcingStrategies(reqId: string): Promise<SourcingStrategyRecord[]> {
  if (isV2ApiEnabled()) throw notImplementedInV2('requisitions.listSourcingStrategies');
  await simulate();
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  return structuredClone(req.sourcing_strategies ?? []);
}

export async function deleteQuestion(questionId: string): Promise<void> {
  if (isV2ApiEnabled()) {
    await v2Client.delete<{ deleted_question_id: string }>(`/api/v2/plan/questions/${questionId}`);
    emit('question:deleted', { question_id: questionId });
    return;
  }
  await simulate();
  const db = getDb();
  for (const req of db.requisitions) {
    for (const round of req.rounds) {
      const idx = round.feedback_questions.findIndex((q) => q.id === questionId);
      if (idx === -1) continue;
      round.feedback_questions.splice(idx, 1);
      round.updated_at = nowIso();
      persist();
      emit('question:deleted', { question_id: questionId });
      return;
    }
  }
  throw new ServiceError('not_found', `Question ${questionId} not found`);
}
