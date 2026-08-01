import type {
  Candidate,
  EvidenceStatus,
  FeedbackEntry,
  RoundRating,
  UntrackedInterview,
} from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { v2Client } from '@/lib/v2-client';
import { create as createCandidate } from './candidates';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import {
  UNTRACKED_GENERIC_REQ_ID,
  UNTRACKED_GENERIC_ROUND_ID,
  untrackedCandidateId,
  untrackedCandidateRoundId,
} from './seed';
import { notImplementedInV2, ServiceError } from './service-error';

export interface UntrackedListPage {
  items: UntrackedInterview[];
  page: number;
  page_size: number;
  total: number;
}

export interface ListUntrackedOptions {
  page?: number;
  page_size?: number;
}

const DEFAULT_PAGE_SIZE = 10;

export async function list(options?: ListUntrackedOptions): Promise<UntrackedListPage> {
  const page = Math.max(options?.page ?? 1, 1);
  const pageSize = Math.max(Math.min(options?.page_size ?? DEFAULT_PAGE_SIZE, 100), 1);

  if (isV2ApiEnabled()) {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    const result = await v2Client.get<UntrackedListPage>(
      `/api/v2/untracked-interviews?${params.toString()}`,
    );
    return {
      items: result.items ?? [],
      page: result.page,
      page_size: result.page_size,
      total: result.total,
    };
  }
  await simulate();
  const all = structuredClone(getDb().untracked).filter((u) => u.status !== 'dismissed');
  const start = (page - 1) * pageSize;
  return {
    items: all.slice(start, start + pageSize),
    page,
    page_size: pageSize,
    total: all.length,
  };
}

/**
 * Resolve the synthetic (reqId, candidateId) backing an untracked interview's
 * feedback packet. The PacketDrawer reads the standard CandidatePacket via
 * usePacket(reqId, candidateId); the synthetic ids live under the hidden
 * `req_ut_generic` requisition mirrored from the backend's
 * `org_generic_template_bindings.materialized_requisition_id`.
 */
export function packetIds(untrackedId: string): {
  reqId: string;
  candidateId: string;
} {
  return {
    reqId: UNTRACKED_GENERIC_REQ_ID,
    candidateId: untrackedCandidateId(untrackedId),
  };
}

/**
 * Fetch the rich feedback packet for an untracked interview. The standard
 * `/roles/{id}/candidates/{cid}/packet` RPC doesn't return data for rows
 * under the materialized untracked requisition, so v2 has a dedicated
 * endpoint that reads the same source candidate_round + feedback +
 * recording metadata and returns it in CandidatePacket shape.
 *
 * Mock-path resolves to the standard `getPacket(reqId, candidateId)`
 * against the synthetic seed, so demos without a backend keep working.
 */
export async function getPacket(
  untrackedId: string,
): Promise<import('./candidates').CandidatePacket> {
  if (isV2ApiEnabled()) {
    return await v2Client.get<import('./candidates').CandidatePacket>(
      `/api/v2/untracked-interviews/${untrackedId}/packet`,
    );
  }
  await simulate();
  const { getPacket: getCandidatePacket } = await import('./candidates');
  const ids = packetIds(untrackedId);
  return getCandidatePacket(ids.reqId, ids.candidateId);
}

function findUntrackedOrThrow(id: string): UntrackedInterview {
  const row = getDb().untracked.find((u) => u.id === id);
  if (!row) throw new ServiceError('not_found', `Untracked ${id} not found`);
  return row;
}

/**
 * Options for `linkToExistingRole`. Controls how the captured interview is
 * attached to a target requisition:
 *
 *   - reqId (required): the requisition to import into.
 *   - mode: 'new_candidate' creates a fresh candidate in the target req;
 *           'merge_existing' attaches this interview to an existing
 *           candidate already in that req.
 *   - targetCandidateId (required when mode==='merge_existing'): the
 *           candidate to merge into.
 *   - targetRoundId (optional): which round of the candidate this
 *           interview was for. Defaults to the target req's first
 *           active shared round when omitted.
 */
export interface LinkToExistingOptions {
  reqId: string;
  mode: 'new_candidate' | 'merge_existing';
  targetCandidateId?: string;
  targetRoundId?: string;
  /** Interviewer attached to the target round; drives "Send feedback request". */
  interviewerEmail?: string;
  interviewerName?: string;
  /** ISO date override for the interview; defaults to the captured event. */
  scheduledAt?: string;
}

export interface LinkToExistingResult {
  candidate: Candidate;
  untracked: UntrackedInterview;
  /** The target candidate_round id — used to send a feedback request or reprocess. */
  targetCandidateRoundId: string;
}

/**
 * Link an untracked interview to an existing role. Two product flows:
 *
 *   - "Add as new candidate": creates a fresh candidate in the target
 *     requisition, then overwrites that candidate's auto-created
 *     candidate_round (for the chosen target round) with the captured
 *     interview metadata + re-processed feedback packet.
 *   - "Merge with existing candidate": attaches the interview to an
 *     already-existing candidate in the target requisition. The selected
 *     round of that candidate gets the captured transcript + a fresh
 *     re-processed feedback packet against the target round's questions.
 *
 * Mirrors v1 `POST /api/v1/requisitions/{req_id}/untracked-interviews/{src}/import`
 * (target_round_id + auto-merge on email) but surfaces the new-vs-merge
 * choice explicitly so the UI doesn't have to guess.
 */
export async function linkToExistingRole(
  untrackedId: string,
  options: LinkToExistingOptions,
): Promise<LinkToExistingResult> {
  if (isV2ApiEnabled()) {
    const body: Record<string, string> = {
      requisition_id: options.reqId,
      mode: options.mode,
    };
    if (options.targetCandidateId) body.target_candidate_id = options.targetCandidateId;
    if (options.targetRoundId) body.target_round_id = options.targetRoundId;
    if (options.interviewerEmail) body.interviewer_email = options.interviewerEmail;
    if (options.interviewerName) body.interviewer_name = options.interviewerName;
    if (options.scheduledAt) body.scheduled_at = options.scheduledAt;
    const resp = await v2Client.post<{
      untracked_id: string;
      target_requisition_id: string;
      target_round_id: string;
      target_candidate_id: string;
      target_candidate_round_id: string;
      candidate_created: boolean;
    }>(`/api/v2/untracked-interviews/${untrackedId}/link-to-existing`, body);
    // The v2 list refetches via the `untracked:updated` event below; the
    // packet RPC refetches via `candidate_round:updated`. We don't have
    // the full candidate row from this response — surface what we know.
    const stub: Candidate = {
      id: resp.target_candidate_id,
      requisition_id: resp.target_requisition_id,
      name: '',
      email: '',
      phone: null,
      resume_url: null,
      avatar_initials: '',
      avatar_color: '',
      status: 'active',
      final_verdict: null,
      current_round_id: resp.target_round_id,
      tags: [],
      source: 'untracked_link',
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    emit('untracked:updated', { id: untrackedId });
    emit('candidate_round:updated', {
      candidate_id: resp.target_candidate_id,
      round_id: resp.target_round_id,
    });
    emit('feedback:submitted', {
      candidate_round_id: resp.target_candidate_round_id,
    });
    return {
      candidate: stub,
      untracked: {
        id: untrackedId,
        status: 'imported',
        imported_candidate_id: resp.target_candidate_id,
        imported_requisition_id: resp.target_requisition_id,
      } as unknown as UntrackedInterview,
      targetCandidateRoundId: resp.target_candidate_round_id,
    };
  }
  await simulate();
  const untracked = findUntrackedOrThrow(untrackedId);
  if (untracked.status !== 'available') {
    throw new ServiceError(
      'invalid_state',
      `Untracked ${untrackedId} is ${untracked.status}; cannot link.`,
    );
  }
  const db = getDb();
  const targetReq = db.requisitions.find((r) => r.id === options.reqId);
  if (!targetReq) {
    throw new ServiceError('not_found', `Requisition ${options.reqId} not found`);
  }
  // Resolve target round: caller's choice if provided, else first active shared.
  const candidateActiveRounds = targetReq.rounds.filter(
    (r) => !r.for_candidate_id && !r.removed_from_plan_at,
  );
  const targetRound = options.targetRoundId
    ? candidateActiveRounds.find((r) => r.id === options.targetRoundId)
    : candidateActiveRounds[0];
  if (!targetRound) {
    throw new ServiceError(
      'invalid_state',
      options.targetRoundId
        ? `Round ${options.targetRoundId} not active in ${targetReq.role_title}.`
        : `${targetReq.role_title} has no active rounds to import into.`,
    );
  }

  // Resolve target candidate based on the explicit mode (UI choice).
  let candidate: Candidate;
  if (options.mode === 'merge_existing') {
    if (!options.targetCandidateId) {
      throw new ServiceError(
        'validation',
        'targetCandidateId is required when mode=merge_existing',
      );
    }
    const existing = db.candidates.find(
      (c) => c.id === options.targetCandidateId && c.requisition_id === options.reqId,
    );
    if (!existing) {
      throw new ServiceError(
        'not_found',
        `Candidate ${options.targetCandidateId} not found in ${targetReq.role_title}.`,
      );
    }
    candidate = existing;
  } else {
    // New candidate. If a candidate with the same email already exists in
    // this req, surface a conflict — the user explicitly chose "new", so
    // silently merging would mask their intent. Use Merge mode to attach
    // to that existing row instead.
    const collision = db.candidates.find(
      (c) =>
        c.requisition_id === options.reqId &&
        c.email.toLowerCase() === untracked.candidate_email.toLowerCase(),
    );
    if (collision) {
      throw new ServiceError(
        'conflict',
        `${collision.name} (${collision.email}) already exists in ${targetReq.role_title}. Use "Merge with existing candidate" instead.`,
      );
    }
    candidate = await createCandidate(options.reqId, {
      name: untracked.candidate_name,
      email: untracked.candidate_email,
      source: 'untracked_link',
    });
  }

  // Find the candidate_round for the chosen target round. New-candidate
  // path always has one (createCandidate auto-creates pending CRs for
  // every active shared round). Merge path usually has one too, but it's
  // possible the candidate was created before this round existed — in
  // that case we materialize a fresh CR row here.
  let crIdx = db.candidate_rounds.findIndex(
    (cr) => cr.candidate_id === candidate.id && cr.round_id === targetRound.id,
  );
  if (crIdx === -1) {
    db.candidate_rounds.push({
      id: `${candidate.id}_${targetRound.id}`,
      candidate_id: candidate.id,
      round_id: targetRound.id,
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
    crIdx = db.candidate_rounds.length - 1;
  }
  const existingCr = db.candidate_rounds[crIdx];
  if (!existingCr) {
    throw new ServiceError(
      'internal',
      `Failed to materialize round ${targetRound.id} for candidate ${candidate.id}.`,
    );
  }
  const rating: RoundRating = 'yes';
  const question_summaries: Record<string, string> = {};
  targetRound.feedback_questions.forEach((q) => {
    question_summaries[String(q.question_number)] = synthesizeQuestionSummary(
      untracked.candidate_name,
      q.heading,
      rating,
    );
  });
  db.candidate_rounds[crIdx] = {
    ...existingCr,
    status: 'completed',
    scorecard_status: 'complete',
    rating,
    summary: synthesizeRoundSummary(untracked.candidate_name, targetRound.name, rating),
    question_summaries,
    scheduled_at: untracked.event_start,
    completed_at: untracked.event_start,
    interviewer_email: untracked.interviewer_email,
    interviewer_name: untracked.interviewer_email.split('@')[0]?.replace(/\./g, ' ') ?? null,
  };

  // Re-process: regenerate feedback entries against the target round's
  // questions. Drop any stale entries on this CR first.
  db.feedback_entries = db.feedback_entries.filter((f) => f.candidate_round_id !== existingCr.id);
  targetRound.feedback_questions.forEach((q, qIdx) => {
    const seedNum = candidate.id.charCodeAt(2) + qIdx;
    const variants = pickPointVariants(rating, seedNum);
    variants.forEach((status, pIdx) => {
      db.feedback_entries.push({
        id: `fb_${existingCr.id}_${q.id}_${pIdx}`,
        candidate_round_id: existingCr.id,
        feedback_question_id: q.id,
        feedback_text: synthesizePointText(untracked.candidate_name, q.heading, status, pIdx),
        evidence_status: status,
        evidence: synthesizeEvidence(q.heading, status, pIdx),
        source: 'bot',
        created_at: untracked.event_start,
      });
    });
  });

  // Copy the recording onto the new CR so Round Replay works in the target
  // role too. (The original synthetic CR keeps its recording — the source
  // packet stays viewable from the Untracked tab while the row is imported.)
  const srcCrId = untrackedCandidateRoundId(untracked.id);
  const srcRecording = db.recordings.find((r) => r.candidate_round_id === srcCrId);
  if (srcRecording) {
    const existingTargetIdx = db.recordings.findIndex(
      (r) => r.candidate_round_id === existingCr.id,
    );
    const copied = { ...srcRecording, candidate_round_id: existingCr.id };
    if (existingTargetIdx >= 0) {
      db.recordings[existingTargetIdx] = copied;
    } else {
      db.recordings.push(copied);
    }
  }

  untracked.status = 'imported';
  untracked.imported_candidate_id = candidate.id;
  untracked.imported_requisition_id = options.reqId;

  db.activity.unshift({
    id: generateId('act'),
    type: 'candidate:status_changed',
    title:
      options.mode === 'merge_existing'
        ? 'Untracked interview merged'
        : 'Untracked interview imported as new candidate',
    description: `${untracked.event_title} → ${candidate.name} · ${targetRound.name} (${targetReq.role_title}).`,
    actor_name: 'Nitin',
    requisition_id: options.reqId,
    candidate_id: candidate.id,
    created_at: nowIso(),
  });
  persist();
  emit('untracked:updated', untracked);
  emit('candidate_round:updated', {
    candidate_id: candidate.id,
    round_id: targetRound.id,
  });
  emit('feedback:submitted', { candidate_round_id: existingCr.id });
  emit('activity:created');
  return {
    candidate: structuredClone(candidate),
    untracked: structuredClone(untracked),
    targetCandidateRoundId: existingCr.id,
  };
}

/**
 * Mark an untracked interview as "Not an interview" — terminal state. The
 * mock list filters dismissed rows out (matches v2 backend semantics).
 */
export async function markNotInterview(untrackedId: string): Promise<UntrackedInterview> {
  if (isV2ApiEnabled()) throw notImplementedInV2('untracked.markNotInterview');
  await simulate();
  const row = findUntrackedOrThrow(untrackedId);
  row.status = 'dismissed';
  persist();
  emit('untracked:updated', row);
  return structuredClone(row);
}

/**
 * Undo an active association: the backend restores the prior round/scorecard,
 * disassociates the role, and returns the interview to 'available'.
 */
export async function undo(untrackedId: string): Promise<{ restored: boolean }> {
  if (isV2ApiEnabled()) {
    const resp = await v2Client.post<{
      untracked_id: string;
      target_candidate_round_id: string | null;
      restored_prior_scorecard: boolean;
    }>(`/api/v2/untracked-interviews/${untrackedId}/undo`);
    emit('untracked:updated', { id: untrackedId });
    emit('candidate_round:updated', {});
    emit('feedback:submitted', {});
    return { restored: resp.restored_prior_scorecard };
  }
  await simulate();
  const row = getDb().untracked.find((u) => u.id === untrackedId);
  if (row) {
    row.status = 'available';
    delete (row as { imported_candidate_id?: string }).imported_candidate_id;
    delete (row as { imported_requisition_id?: string }).imported_requisition_id;
    persist();
  }
  emit('untracked:updated', { id: untrackedId });
  return { restored: false };
}

// Synthesizers reused from the seed path so re-processing produces the same
// shape and tone as the pre-baked feedback packets. These don't need to be
// public; they live inline here to keep the link-to-existing flow self-
// contained without leaking generator internals from seed.ts.
function synthesizeRoundSummary(candName: string, roundName: string, rating: RoundRating): string {
  const first = candName.split(' ')[0] ?? candName;
  const lower = roundName.toLowerCase();
  switch (rating) {
    case 'strong_yes':
      return `${first} was a clear standout in the ${lower}. Showed independent ownership and crisp tradeoffs. Recommend moving fast.`;
    case 'yes':
      return `${first} cleared the bar in the ${lower}. Solid end-to-end ownership and real examples without prompting.`;
    case 'maybe':
      return `${first} was on-bar but inconsistent in the ${lower}. Strong on framework, weaker on specifics.`;
    case 'no':
      return `${first} did not clear the bar in the ${lower}. Examples felt high-level and self-assessment didn't match the depth claimed.`;
    case 'strong_no':
      return `${first} was well below bar in the ${lower}. Multiple claims contradicted themselves under follow-up.`;
    default:
      return `${first} completed the ${lower}.`;
  }
}

function synthesizeQuestionSummary(candName: string, heading: string, rating: RoundRating): string {
  const verdict =
    rating === 'strong_yes'
      ? 'Strongly demonstrated'
      : rating === 'yes'
        ? 'Clearly demonstrated'
        : rating === 'maybe'
          ? 'Partially demonstrated, mixed signals'
          : 'Did not meet the bar';
  const first = candName.split(' ')[0] ?? candName;
  return `${verdict} on "${heading.toLowerCase()}". ${first} backed answers with concrete examples; interviewer probed twice and the answers held up.`;
}

function pickPointVariants(rating: RoundRating, seedNum: number): EvidenceStatus[] {
  if (rating === 'strong_yes') return ['verified', 'verified', 'verified'];
  if (rating === 'yes') {
    return seedNum % 2 === 0
      ? ['verified', 'verified', 'partial']
      : ['verified', 'verified', 'verified'];
  }
  if (rating === 'maybe') {
    return seedNum % 2 === 0
      ? ['verified', 'partial', 'partial']
      : ['verified', 'partial', 'contradicted'];
  }
  return ['partial', 'contradicted', 'contradicted'];
}

function synthesizePointText(
  candName: string,
  heading: string,
  status: FeedbackEntry['evidence_status'],
  pointIdx: number,
): string {
  const first = candName.split(' ')[0] ?? candName;
  const claims = {
    supported: [
      `Strong answer on "${heading}". Walked through a concrete example end-to-end without prompting.`,
      `${first} cited measurable outcomes when probed on this dimension.`,
      `Demonstrated structured thinking; broke the problem into 3 explicit tradeoffs and committed to one.`,
    ],
    verified: [
      `Strong answer on "${heading}". Walked through a concrete example end-to-end without prompting.`,
      `${first} cited measurable outcomes when probed on this dimension.`,
      `Demonstrated structured thinking; broke the problem into 3 explicit tradeoffs and committed to one.`,
    ],
    partial: [
      `Answer was directionally right but lacked specifics. Needed two follow-ups to surface real numbers.`,
      `Framework was sound but example felt rehearsed; couldn't go beyond the canned story.`,
      `Got to the right conclusion but skipped the reasoning.`,
    ],
    contradicted: [
      `Self-assessment did not match the example given.`,
      `Claimed end-to-end ownership early, then walked it back later.`,
      `Numbers cited didn't pass a sanity check against the timeline described.`,
    ],
    none: [`Did not get to this in the time available.`],
  } as const;
  const list = claims[status];
  return list[pointIdx % list.length] ?? list[0] ?? '';
}

function synthesizeEvidence(
  heading: string,
  status: FeedbackEntry['evidence_status'],
  pointIdx: number,
): string[] {
  if (status === 'none') return [];
  const pool = {
    supported: [
      `"I led that effort end-to-end — I owned the rollout from week one." — on ${heading.toLowerCase()}`,
      `"We saw a 30% lift in activation in the first month after the change." — concrete metric`,
      `"Three tradeoffs: speed, observability, blast radius. We chose observability first." — structured framing`,
    ],
    verified: [
      `"I led that effort end-to-end — I owned the rollout from week one." — on ${heading.toLowerCase()}`,
      `"We saw a 30% lift in activation in the first month after the change." — concrete metric`,
      `"Three tradeoffs: speed, observability, blast radius. We chose observability first." — structured framing`,
    ],
    partial: [
      `"It worked out well overall." — vague, no specifics offered until probed`,
      `"We had a really good outcome." — couldn't quantify when asked`,
    ],
    contradicted: [
      `"I led the rollout end-to-end." — claim early in the round`,
      `"Actually my manager drove most of the execution; I supported." — said later`,
    ],
    none: [],
  } as const;
  const list: readonly string[] = pool[status];
  if (list.length === 0) return [];
  return [list[pointIdx % list.length] ?? (list[0] as string)];
}

// Round id used when synthesizing the untracked feedback packet — exported so
// callers (e.g. the rail-views card) can wire deep links into the drawer
// without knowing the seed module's internals.
export { UNTRACKED_GENERIC_ROUND_ID };
