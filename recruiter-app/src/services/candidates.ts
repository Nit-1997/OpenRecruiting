import type {
  Candidate,
  CandidateCreateInput,
  CandidateRound,
  CandidateStatus,
  CandidateUpdateInput,
  CustomRoundCreateInput,
  FeedbackEntry,
  FinalVerdict,
  Round,
} from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { isCustomRound } from '@/lib/rounds';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import { notImplementedInV2, ServiceError } from './service-error';

// Packet RPC response (spec §7 row 4). One round-trip; the drawer derives
// all its read-side state (candidate rounds, feedback, recording metadata,
// assessment) from this single payload.
export interface CandidatePacketFeedbackQuestion {
  id: string;
  question_number: number;
  heading: string;
  description: string | null;
  summary: string | null;
  feedback_entries: FeedbackEntry[] | null;
}

export interface CandidatePacketRecording {
  status: string;
  duration_seconds: number | null;
  has_transcript: boolean;
}

// Assessment payload — opaque to FE today (no domain type yet). Keep the
// envelope so the drawer can pass it down once an assessment surface ships.
export interface CandidatePacketAssessment {
  template: Record<string, unknown> | null;
  instance: Record<string, unknown> | null;
}

export interface CandidatePacketEntry {
  round: Round;
  candidate_round: CandidateRound | null;
  feedback_questions: CandidatePacketFeedbackQuestion[];
  assessment: CandidatePacketAssessment | null;
  recording: CandidatePacketRecording | null;
}

export interface CandidatePacket {
  candidate: Candidate;
  rounds: CandidatePacketEntry[];
}

const DEFAULT_AVATAR_COLORS = ['#EADFD4', '#D8EFE3', '#E9DFF5', '#FDE68A', '#BFDBFE', '#FECACA'];

function initialsFor(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function assertReqExists(reqId: string): void {
  if (!getDb().requisitions.some((r) => r.id === reqId)) {
    throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  }
}

export async function listForReq(reqId: string): Promise<Candidate[]> {
  if (isV2ApiEnabled()) {
    // Spec §7 row 2: pipeline RPC returns each candidate with its ordered
    // candidate_rounds *and* an embedded round header. Preserve that nested
    // data on the Candidate (optional field) so the rail can render custom
    // rounds without a per-row fetch.
    const result = await v2Client.get<{ candidates: Candidate[] }>(
      `/api/v2/roles/${reqId}/candidates`,
    );
    return result.candidates ?? [];
  }
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  const roundDefsById = new Map(req?.rounds.map((r) => [r.id, r] as const) ?? []);
  return db.candidates
    .filter((c) => c.requisition_id === reqId)
    .map((c) => {
      const candidateRounds = db.candidate_rounds
        .filter((cr) => cr.candidate_id === c.id)
        .map((cr) => {
          const def = roundDefsById.get(cr.round_id);
          if (!def) return null;
          return {
            ...cr,
            round: {
              id: def.id,
              round_number: def.round_number,
              name: def.name,
              category: def.category,
              duration_minutes: def.duration_minutes,
              is_custom: !!def.for_candidate_id,
              for_candidate_id: def.for_candidate_id ?? null,
            },
          };
        })
        .filter((cr): cr is NonNullable<typeof cr> => cr !== null)
        .sort((a, b) => a.round.round_number - b.round.round_number);
      return structuredClone({ ...c, candidate_rounds: candidateRounds });
    });
}

export async function get(reqId: string, candidateId: string): Promise<Candidate> {
  if (isV2ApiEnabled()) {
    // No dedicated single-candidate GET on the backend; the pipeline RPC
    // (same one listForReq uses) is the source of truth. Filter to the
    // requested id. Strip the embedded `candidate_rounds` to honor the
    // existing `Candidate` return contract.
    type PipelineCandidate = Candidate & { candidate_rounds?: unknown };
    const result = await v2Client.get<{ candidates: PipelineCandidate[] }>(
      `/api/v2/roles/${reqId}/candidates`,
    );
    const found = (result.candidates ?? []).find((c) => c.id === candidateId);
    if (!found) {
      throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
    }
    const { candidate_rounds: _candidateRounds, ...candidate } = found;
    return candidate as Candidate;
  }
  await simulate();
  assertReqExists(reqId);
  const c = getDb().candidates.find((x) => x.id === candidateId && x.requisition_id === reqId);
  if (!c) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  return structuredClone(c);
}

export async function create(reqId: string, input: CandidateCreateInput): Promise<Candidate> {
  if (isV2ApiEnabled()) {
    // v2 returns `{ candidate, counts }`; the mock's contract is `Candidate`,
    // so we unwrap. Emit `candidate:created` to mirror the mock path.
    const result = await v2Client.post<{
      candidate: Candidate;
      counts?: unknown;
    }>(`/api/v2/roles/${reqId}/candidates`, input);
    emit('candidate:created', result.candidate);
    return result.candidate;
  }
  await simulate();
  assertReqExists(reqId);
  if (!input.name?.trim()) {
    throw new ServiceError('validation', 'name is required', { field: 'name' });
  }
  if (!input.email?.trim()) {
    throw new ServiceError('validation', 'email is required', { field: 'email' });
  }
  const db = getDb();
  const existing = db.candidates.find(
    (c) => c.requisition_id === reqId && c.email.toLowerCase() === input.email.toLowerCase(),
  );
  if (existing) {
    throw new ServiceError('conflict', `Candidate with email ${input.email} already exists`);
  }
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const id = generateId('cand');
  const now = nowIso();
  const colorIdx = db.candidates.length % DEFAULT_AVATAR_COLORS.length;
  const candidate: Candidate = {
    id,
    requisition_id: reqId,
    name: input.name.trim(),
    email: input.email.trim(),
    phone: input.phone ?? null,
    resume_url: input.resume_url ?? null,
    avatar_initials: initialsFor(input.name),
    avatar_color: DEFAULT_AVATAR_COLORS[colorIdx] ?? '#EADFD4',
    status: 'active',
    final_verdict: null,
    current_round_id: req.rounds[0]?.id ?? null,
    tags: input.tags ?? [],
    source: input.source ?? 'manual',
    created_at: now,
    updated_at: now,
  };
  db.candidates.push(candidate);
  // Eager-create candidate_rounds for every active shared round (per v2 invariant:
  // for_candidate_id IS NULL AND removed_from_plan_at IS NULL).
  req.rounds
    .filter((round) => !round.for_candidate_id && !round.removed_from_plan_at)
    .forEach((round) => {
      db.candidate_rounds.push({
        id: `${id}_${round.id}`,
        candidate_id: id,
        round_id: round.id,
        status: 'pending',
        scorecard_status: 'pending',
        rating: null,
        summary: '',
        question_summaries: {},
        authenticity_signals: null,
        feedback_approved_at: null,
        feedback_approved_by_email: null,
        scheduled_at: null,
        scheduling_timezone: null,
        completed_at: null,
        interviewer_email: null,
        interviewer_name: null,
        meeting_url: null,
        scorecard: [],
      });
    });
  db.activity.unshift({
    id: generateId('act'),
    type: 'candidate:created',
    title: 'Candidate added',
    description: `${candidate.name} added to ${req.role_title}.`,
    actor_name: req.created_by_name,
    requisition_id: reqId,
    candidate_id: id,
    created_at: now,
  });
  persist();
  emit('candidate:created', candidate);
  emit('activity:created');
  return structuredClone(candidate);
}

export async function update(
  reqId: string,
  candidateId: string,
  patch: CandidateUpdateInput,
): Promise<Candidate> {
  if (isV2ApiEnabled()) throw notImplementedInV2('candidates.update');
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const idx = db.candidates.findIndex((c) => c.id === candidateId && c.requisition_id === reqId);
  if (idx === -1) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const existing = db.candidates[idx];
  if (!existing) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const next: Candidate = { ...existing, ...patch, updated_at: nowIso() };
  db.candidates[idx] = next;
  persist();
  emit('candidate:updated', next);
  return structuredClone(next);
}

export async function remove(reqId: string, candidateId: string): Promise<void> {
  if (isV2ApiEnabled()) throw notImplementedInV2('candidates.remove');
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const idx = db.candidates.findIndex((c) => c.id === candidateId && c.requisition_id === reqId);
  if (idx === -1) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  db.candidates.splice(idx, 1);
  const removedCrIds = new Set(
    db.candidate_rounds.filter((cr) => cr.candidate_id === candidateId).map((cr) => cr.id),
  );
  db.candidate_rounds = db.candidate_rounds.filter((cr) => cr.candidate_id !== candidateId);
  db.feedback_entries = db.feedback_entries.filter((f) => !removedCrIds.has(f.candidate_round_id));
  persist();
  emit('candidate:deleted', { candidate_id: candidateId });
}

// Backend canonical: candidates.status CHECK ('active','hired','rejected','withdrawn').
// Terminal states: hired, rejected. withdrawn is a candidate-initiated drop; surface in UI later.
const CANDIDATE_TRANSITIONS: Record<CandidateStatus, CandidateStatus[]> = {
  active: ['hired', 'rejected', 'withdrawn'],
  hired: [],
  rejected: ['active'],
  withdrawn: ['active'],
};

export async function setStatus(
  reqId: string,
  candidateId: string,
  status: CandidateStatus,
  verdict?: FinalVerdict | null,
): Promise<Candidate> {
  if (isV2ApiEnabled()) throw notImplementedInV2('candidates.setStatus');
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const idx = db.candidates.findIndex((c) => c.id === candidateId && c.requisition_id === reqId);
  if (idx === -1) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const existing = db.candidates[idx];
  if (!existing) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const current = existing.status;
  if (current === status) return structuredClone(existing);
  if (!CANDIDATE_TRANSITIONS[current].includes(status)) {
    throw new ServiceError(
      'invalid_state',
      `Cannot transition candidate from ${current} to ${status}`,
    );
  }
  const next: Candidate = {
    ...existing,
    status,
    final_verdict: verdict === undefined ? existing.final_verdict : verdict,
    updated_at: nowIso(),
  };
  db.candidates[idx] = next;
  db.activity.unshift({
    id: generateId('act'),
    type: 'candidate:status_changed',
    title: `Candidate moved to ${status}`,
    description: `${next.name} → ${status}.`,
    actor_name: 'Nitin',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: nowIso(),
  });
  persist();
  emit('candidate:status_changed', next);
  emit('activity:created');
  return structuredClone(next);
}

export async function listRounds(reqId: string, candidateId: string): Promise<CandidateRound[]> {
  if (isV2ApiEnabled()) {
    // Spec §7 row 2: the pipeline RPC already returns each candidate with its
    // ordered `candidate_rounds` (including custom rounds for that candidate).
    // We reuse that endpoint so this call doesn't need its own backend route.
    // Per-row callers should prefer reading from the parent listForReq result
    // to avoid N+1 fetches; this v2 branch is the safety net.
    type PipelineCandidate = Candidate & {
      candidate_rounds?: Array<CandidateRound & { round?: unknown }>;
    };
    const result = await v2Client.get<{ candidates: PipelineCandidate[] }>(
      `/api/v2/roles/${reqId}/candidates`,
    );
    const cand = (result.candidates ?? []).find((c) => c.id === candidateId);
    if (!cand) {
      throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
    }
    // Strip the embedded `round` to honor the existing CandidateRound[] contract.
    return (cand.candidate_rounds ?? []).map(({ round: _round, ...cr }) => cr as CandidateRound);
  }
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const cand = db.candidates.find((c) => c.id === candidateId && c.requisition_id === reqId);
  if (!cand) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const rounds = req.rounds
    .filter((round) => !isCustomRound(round) || round.for_candidate_id === candidateId)
    .map((round) =>
      db.candidate_rounds.find((cr) => cr.candidate_id === candidateId && cr.round_id === round.id),
    )
    .filter((cr): cr is CandidateRound => !!cr);
  return structuredClone(rounds);
}

export async function addCustomRound(
  reqId: string,
  candidateId: string,
  input: CustomRoundCreateInput,
): Promise<{ round: Round; candidateRound: CandidateRound }> {
  if (isV2ApiEnabled()) {
    // Backend returns `{ round, candidate_round }`. The mock returns
    // `{ round, candidateRound }` (camelCase) — adapt to preserve callers.
    const result = await v2Client.post<{
      round: Round;
      candidate_round: CandidateRound;
    }>(`/api/v2/roles/${reqId}/candidates/${candidateId}/rounds`, input);
    emit('round:created', result.round);
    emit('candidate_round:updated', result.candidate_round);
    return { round: result.round, candidateRound: result.candidate_round };
  }
  await simulate();
  assertReqExists(reqId);
  if (!input.name?.trim()) {
    throw new ServiceError('validation', 'name is required', { field: 'name' });
  }
  if (!input.duration_minutes || input.duration_minutes <= 0) {
    throw new ServiceError('validation', 'duration_minutes must be positive', {
      field: 'duration_minutes',
    });
  }
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const cand = db.candidates.find((c) => c.id === candidateId && c.requisition_id === reqId);
  if (!cand) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const now = nowIso();
  const roundId = generateId('round');
  const skills = (input.skills ?? [])
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  const feedbackQuestions = (input.feedback_questions ?? [])
    .map((q, i) => ({
      heading: q.heading.trim(),
      description: q.description.trim(),
      question_number: i + 1,
    }))
    .filter((q) => q.heading.length > 0)
    .map((q) => ({
      id: generateId('q'),
      round_id: roundId,
      question_number: q.question_number,
      heading: q.heading,
      description: q.description,
    }));
  const guidelines = (input.guidelines ?? [])
    .map((g) => ({ title: g.title.trim(), description: g.description.trim() }))
    .filter((g) => g.title.length > 0);
  const round: Round = {
    id: roundId,
    requisition_id: reqId,
    round_number: req.rounds.length + 1,
    name: input.name.trim(),
    category: input.category,
    duration_minutes: input.duration_minutes,
    skills,
    guidelines,
    feedback_questions: feedbackQuestions,
    is_custom: true,
    for_candidate_id: candidateId,
    created_at: now,
    updated_at: now,
  };
  const trimmedDescription = input.description?.trim();
  if (trimmedDescription) round.description = trimmedDescription;
  req.rounds.push(round);
  req.updated_at = now;
  const candidateRound: CandidateRound = {
    id: `${candidateId}_${round.id}`,
    candidate_id: candidateId,
    round_id: round.id,
    status: 'pending',
    scorecard_status: 'pending',
    rating: null,
    summary: '',
    question_summaries: {},
    authenticity_signals: null,
    feedback_approved_at: null,
    feedback_approved_by_email: null,
    scheduled_at: null,
    scheduling_timezone: null,
    completed_at: null,
    interviewer_email: null,
    interviewer_name: null,
    meeting_url: null,
    scorecard: [],
  };
  db.candidate_rounds.push(candidateRound);
  persist();
  emit('round:created', round);
  emit('candidate_round:updated', candidateRound);
  return structuredClone({ round, candidateRound });
}

// v2 DELETE wants `cr_id`, but the existing API takes `round_id` (mock
// indexes CRs by candidate+round). Resolve cr_id via the packet response.
async function resolveCrIdFromPacket(
  reqId: string,
  candidateId: string,
  roundId: string,
): Promise<string> {
  type PacketRow = {
    round: { id: string };
    candidate_round: { id: string } | null;
  };
  const packet = await v2Client.get<{ rounds: PacketRow[] }>(
    `/api/v2/roles/${reqId}/candidates/${candidateId}/packet`,
  );
  const match = (packet.rounds ?? []).find(
    (r) => r.round?.id === roundId && r.candidate_round?.id,
  );
  if (!match?.candidate_round?.id) {
    throw new ServiceError(
      'not_found',
      `Candidate round for ${candidateId}/${roundId} not found`,
    );
  }
  return match.candidate_round.id;
}

export async function removeRoundForCandidate(
  reqId: string,
  candidateId: string,
  roundId: string,
): Promise<void> {
  if (isV2ApiEnabled()) {
    const crId = await resolveCrIdFromPacket(reqId, candidateId, roundId);
    const result = await v2Client.delete<{
      deleted_cr_id: string;
      deleted_round_id: string | null;
    }>(`/api/v2/roles/${reqId}/candidates/${candidateId}/rounds/${crId}`);
    if (result?.deleted_round_id) {
      emit('round:deleted', { round_id: result.deleted_round_id });
    } else {
      emit('candidate_round:updated', {
        candidate_id: candidateId,
        round_id: roundId,
      });
    }
    return;
  }
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const cand = db.candidates.find((c) => c.id === candidateId && c.requisition_id === reqId);
  if (!cand) throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  const round = req.rounds.find((r) => r.id === roundId);
  if (!round) throw new ServiceError('not_found', `Round ${roundId} not found`);
  const crIdx = db.candidate_rounds.findIndex(
    (cr) => cr.candidate_id === candidateId && cr.round_id === roundId,
  );
  if (crIdx === -1) {
    throw new ServiceError('not_found', `Candidate round for ${candidateId}/${roundId} not found`);
  }
  const cr = db.candidate_rounds[crIdx];
  db.candidate_rounds.splice(crIdx, 1);
  if (cr) {
    db.feedback_entries = db.feedback_entries.filter((f) => f.candidate_round_id !== cr.id);
  }
  const ownedByThisCandidate =
    isCustomRound(round) && round.for_candidate_id === candidateId;
  if (ownedByThisCandidate) {
    const rIdx = req.rounds.findIndex((r) => r.id === roundId);
    if (rIdx !== -1) req.rounds.splice(rIdx, 1);
    req.rounds.forEach((r, i) => {
      r.round_number = i + 1;
    });
  }
  req.updated_at = nowIso();
  persist();
  if (ownedByThisCandidate) {
    emit('round:deleted', { round_id: roundId });
  } else {
    emit('candidate_round:updated', { candidate_id: candidateId, round_id: roundId });
  }
}

// Spec §7 row 4: single-call packet fetch. Backend pure-passes the
// get_candidate_packet RPC. The mock path synthesizes the same shape from
// mock-db so existing demo flows keep working without an HTTP layer.
export async function getPacket(
  reqId: string,
  candidateId: string,
): Promise<CandidatePacket> {
  if (isV2ApiEnabled()) {
    const packet = await v2Client.get<CandidatePacket>(
      `/api/v2/roles/${reqId}/candidates/${candidateId}/packet`,
    );
    // The RPC's `round` payload only carries the round header (no
    // feedback_questions, skills/guidelines may be null). The candidate_round
    // payload returns `question_summaries: null` when the feedback Lambda
    // hasn't produced summaries yet. Downstream consumers (drawer, print
    // view, summary card) treat these as non-nullable per the domain types,
    // so denormalize here:
    //   - synthesize round.feedback_questions from entry.feedback_questions
    //   - default nullable arrays (skills/guidelines) so .length / .map calls
    //     in the drawer don't throw when the backend returns NULL
    //   - default candidate_round.question_summaries to {} so the evaluation
    //     criteria card can index it by question id without crashing
    return {
      ...packet,
      rounds: (packet.rounds ?? []).map((entry) => ({
        ...entry,
        candidate_round: entry.candidate_round
          ? {
              ...entry.candidate_round,
              question_summaries: entry.candidate_round.question_summaries ?? {},
              // Screening authenticity is a directional add-on (migration 117);
              // the RPC returns NULL for non-screening / unprocessed rounds.
              authenticity_signals: entry.candidate_round.authenticity_signals ?? null,
            }
          : null,
        round: {
          ...entry.round,
          skills: entry.round?.skills ?? [],
          guidelines: entry.round?.guidelines ?? [],
          feedback_questions: (entry.feedback_questions ?? []).map((q) => ({
            id: q.id,
            round_id: entry.round.id,
            question_number: q.question_number,
            heading: q.heading,
            description: q.description ?? '',
          })),
        },
      })),
    };
  }
  await simulate();
  assertReqExists(reqId);
  const db = getDb();
  const candidate = db.candidates.find(
    (c) => c.id === candidateId && c.requisition_id === reqId,
  );
  if (!candidate) {
    throw new ServiceError('not_found', `Candidate ${candidateId} not found`);
  }
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);

  // Same visibility rule as listRounds: shared rounds + this candidate's
  // custom rounds. Ordered by round_number, matching the RPC.
  const visibleRounds = req.rounds
    .filter(
      (round) => !isCustomRound(round) || round.for_candidate_id === candidateId,
    )
    .slice()
    .sort((a, b) => a.round_number - b.round_number);

  const entries: CandidatePacketEntry[] = visibleRounds.map((round) => {
    const cr =
      db.candidate_rounds.find(
        (x) => x.candidate_id === candidateId && x.round_id === round.id,
      ) ?? null;
    const recording = cr
      ? db.recordings.find((r) => r.candidate_round_id === cr.id) ?? null
      : null;
    const fbQuestions: CandidatePacketFeedbackQuestion[] = round.feedback_questions.map(
      (q) => ({
        id: q.id,
        question_number: q.question_number,
        heading: q.heading,
        description: q.description ?? null,
        summary:
          cr?.question_summaries?.[String(q.question_number)] ?? null,
        feedback_entries: cr
          ? db.feedback_entries.filter(
              (f) =>
                f.candidate_round_id === cr.id && f.feedback_question_id === q.id,
            )
          : [],
      }),
    );
    return {
      round: structuredClone(round),
      candidate_round: cr ? structuredClone(cr) : null,
      feedback_questions: fbQuestions,
      assessment: null,
      recording: recording
        ? {
            status: recording.available ? 'done' : 'pending',
            duration_seconds: recording.duration_seconds,
            has_transcript: recording.transcript_segments.length > 0,
          }
        : null,
    };
  });

  return {
    candidate: structuredClone(candidate),
    rounds: entries,
  };
}

export async function getRound(
  reqId: string,
  candidateId: string,
  roundId: string,
): Promise<CandidateRound> {
  if (isV2ApiEnabled()) {
    // No standalone candidate-round GET on the backend; the packet RPC carries
    // every round's `candidate_round` already, so read from there (same source
    // the drawer uses). Strip the embedded `round` header to honor the
    // CandidateRound return contract.
    type PacketRow = {
      round: { id: string };
      candidate_round: (CandidateRound & { round?: unknown }) | null;
    };
    const packet = await v2Client.get<{ rounds: PacketRow[] }>(
      `/api/v2/roles/${reqId}/candidates/${candidateId}/packet`,
    );
    const match = (packet.rounds ?? []).find(
      (r) => r.round?.id === roundId && r.candidate_round,
    );
    if (!match?.candidate_round) {
      throw new ServiceError('not_found', 'CandidateRound not found');
    }
    const { round: _round, ...cr } = match.candidate_round;
    return cr as CandidateRound;
  }
  await simulate();
  assertReqExists(reqId);
  const cr = getDb().candidate_rounds.find(
    (x) => x.candidate_id === candidateId && x.round_id === roundId,
  );
  if (!cr) throw new ServiceError('not_found', 'CandidateRound not found');
  return structuredClone(cr);
}
