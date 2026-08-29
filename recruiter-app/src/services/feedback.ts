import type {
  FeedbackEntry,
  FeedbackRequestInput,
  FeedbackSubmissionInput,
  RoundRecording,
} from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import { ServiceError } from './service-error';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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
  const match = (packet.rounds ?? []).find((r) => r.round?.id === roundId && r.candidate_round?.id);
  if (!match?.candidate_round?.id) {
    throw new ServiceError('not_found', `Candidate round for ${candidateId}/${roundId} not found`);
  }
  return match.candidate_round.id;
}

function findCr(reqId: string, candidateId: string, roundId: string) {
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const round = req.rounds.find((r) => r.id === roundId);
  if (!round) throw new ServiceError('not_found', `Round ${roundId} not found`);
  const cr = db.candidate_rounds.find(
    (x) => x.candidate_id === candidateId && x.round_id === roundId,
  );
  if (!cr) throw new ServiceError('not_found', 'CandidateRound not found');
  return { req, round, cr };
}

export async function getRoundFeedback(
  reqId: string,
  candidateId: string,
  roundId: string,
): Promise<FeedbackEntry[]> {
  if (isV2ApiEnabled()) {
    // No dedicated round-feedback GET; the packet RPC already embeds each
    // round's feedback entries under `feedback_questions[].feedback_entries`.
    // Read from there and flatten to the FeedbackEntry[] contract.
    type PacketRow = {
      round: { id: string };
      feedback_questions: Array<{ feedback_entries: FeedbackEntry[] | null }> | null;
    };
    const packet = await v2Client.get<{ rounds: PacketRow[] }>(
      `/api/v2/roles/${reqId}/candidates/${candidateId}/packet`,
    );
    const match = (packet.rounds ?? []).find((r) => r.round?.id === roundId);
    if (!match) {
      throw new ServiceError('not_found', 'CandidateRound not found');
    }
    return (match.feedback_questions ?? []).flatMap((q) => q.feedback_entries ?? []);
  }
  await simulate();
  const { cr } = findCr(reqId, candidateId, roundId);
  return structuredClone(getDb().feedback_entries.filter((f) => f.candidate_round_id === cr.id));
}

export async function submitFeedback(
  reqId: string,
  candidateId: string,
  roundId: string,
  input: FeedbackSubmissionInput,
): Promise<FeedbackEntry[]> {
  if (isV2ApiEnabled()) {
    // v2 body shape (spec §8.2): `{ entries: [{feedback_question_id,
    // feedback_text, evidence_status, evidence?}], rating, summary }`.
    // Per-entry `rating` and the `scorecard` array are UI-only and the
    // backend ignores them (no DB column yet). We forward only the fields
    // the backend persists.
    const crId = await resolveCrIdFromPacket(reqId, candidateId, roundId);
    const body = {
      entries: input.entries.map((e) => ({
        feedback_question_id: e.feedback_question_id,
        feedback_text: e.feedback_text,
        evidence_status: e.evidence_status,
      })),
      rating: input.overall_rating,
      summary: input.summary,
    };
    const result = await v2Client.post<{
      candidate_round: unknown;
      entries: FeedbackEntry[];
    }>(`/api/v2/candidate-rounds/${crId}/feedback`, body);
    emit('feedback:submitted', result.entries ?? []);
    emit('candidate_round:updated', result.candidate_round);
    return result.entries ?? [];
  }
  await simulate();
  const { round, cr } = findCr(reqId, candidateId, roundId);
  if (input.entries.length !== round.feedback_questions.length) {
    throw new ServiceError(
      'validation',
      `Expected ${round.feedback_questions.length} entries, got ${input.entries.length}`,
    );
  }
  const db = getDb();
  const now = nowIso();
  db.feedback_entries = db.feedback_entries.filter((f) => f.candidate_round_id !== cr.id);
  const entries: FeedbackEntry[] = input.entries.map((e) => ({
    id: generateId('fb'),
    candidate_round_id: cr.id,
    feedback_question_id: e.feedback_question_id,
    feedback_text: e.feedback_text,
    evidence_status: e.evidence_status,
    evidence: [],
    source: 'manual',
    created_at: now,
  }));
  db.feedback_entries.push(...entries);
  cr.status = 'completed';
  cr.scorecard_status = 'complete';
  cr.rating = input.overall_rating;
  cr.summary = input.summary;
  cr.completed_at = now;
  cr.scorecard = input.scorecard.map((s) => ({
    id: generateId('sc'),
    candidate_round_id: cr.id,
    dimension: s.dimension,
    rating: s.rating,
    notes: s.notes,
  }));
  db.activity.unshift({
    id: generateId('act'),
    type: 'feedback:submitted',
    title: 'Feedback submitted',
    description: `${round.name}: ${input.overall_rating}.`,
    actor_name: cr.interviewer_name ?? 'Interviewer',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: now,
  });
  persist();
  emit('feedback:submitted', entries);
  emit('candidate_round:updated', cr);
  emit('activity:created');
  return structuredClone(entries);
}

export async function requestFeedback(
  reqId: string,
  candidateId: string,
  roundId: string,
  input: FeedbackRequestInput,
): Promise<{ sent: true }> {
  if (isV2ApiEnabled()) {
    const crId = await resolveCrIdFromPacket(reqId, candidateId, roundId);
    await v2Client.post<{ sent: true; request_id?: string }>(
      `/api/v2/candidate-rounds/${crId}/request-feedback`,
      input,
    );
    emit('feedback:requested');
    return { sent: true };
  }
  await simulate();
  findCr(reqId, candidateId, roundId);
  if (!EMAIL_RE.test(input.interviewer_email)) {
    throw new ServiceError('validation', 'interviewer_email must be valid', {
      field: 'interviewer_email',
    });
  }
  const db = getDb();
  db.activity.unshift({
    id: generateId('act'),
    type: 'feedback:requested',
    title: 'Feedback requested',
    description: `Sent to ${input.interviewer_email} via ${input.channel}.`,
    actor_name: 'Taylor',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: nowIso(),
  });
  persist();
  emit('feedback:requested');
  emit('activity:created');
  return { sent: true };
}

// Fetch only the pre-signed URL — lazy path used on Play click. v2 spec §7.
export async function getRecordingUrl(
  candidateRoundId: string,
): Promise<{ url: string; expires_at: string }> {
  if (isV2ApiEnabled()) {
    return v2Client.get<{ url: string; expires_at: string }>(
      `/api/v2/candidate-rounds/${candidateRoundId}/recording-url`,
    );
  }
  await simulate();
  const db = getDb();
  const cr = db.candidate_rounds.find((x) => x.id === candidateRoundId);
  if (!cr) throw new ServiceError('not_found', `CandidateRound ${candidateRoundId} not found`);
  return {
    url: `#recording/${candidateRoundId}`,
    expires_at: new Date(Date.now() + 3600_000).toISOString(),
  };
}

// Fetch the transcript only — used by View Transcript. v2 spec §7.
export async function getTranscript(candidateRoundId: string): Promise<{
  segments: Array<{ speaker: string; text: string; ts_start: number; ts_end: number }>;
  duration_seconds: number;
  word_count: number;
}> {
  if (isV2ApiEnabled()) {
    return v2Client.get<{
      segments: Array<{ speaker: string; text: string; ts_start: number; ts_end: number }>;
      duration_seconds: number;
      word_count: number;
    }>(`/api/v2/candidate-rounds/${candidateRoundId}/transcript`);
  }
  await simulate();
  const rec = await getRecording(candidateRoundId);
  return {
    segments: rec.transcript_segments.map((s) => ({
      speaker: s.speaker,
      text: s.text,
      ts_start: s.start_seconds,
      ts_end: s.end_seconds,
    })),
    duration_seconds: rec.duration_seconds,
    word_count: rec.transcript_segments.reduce((acc, s) => acc + s.text.split(/\s+/).length, 0),
  };
}

// Re-trigger the feedback Lambda for a completed candidate round. v2 spec §8.2.
export async function reprocess(
  candidateRoundId: string,
  force = false,
): Promise<{ candidate_round_id: string; processing_status: string; triggered_at: string }> {
  if (isV2ApiEnabled()) {
    const result = await v2Client.post<{
      candidate_round_id: string;
      processing_status: string;
      triggered_at: string;
    }>(`/api/v2/candidate-rounds/${candidateRoundId}/reprocess`, { force });
    emit('feedback:requested');
    return result;
  }
  // Mock-mode no-op: emit the event so subscribers refetch and pretend a
  // run started.
  await simulate();
  emit('feedback:requested');
  return {
    candidate_round_id: candidateRoundId,
    processing_status: 'processing',
    triggered_at: nowIso(),
  };
}

export async function getRecording(candidateRoundId: string): Promise<RoundRecording> {
  if (isV2ApiEnabled()) {
    // Compose URL + transcript into the legacy RoundRecording shape so existing
    // callers keep working. Recording metadata (status, has_transcript) lives
    // in the packet response — callers that want it should switch to using
    // the packet directly.
    const [urlRes, tx] = await Promise.allSettled([
      v2Client.get<{ url: string; expires_at: string }>(
        `/api/v2/candidate-rounds/${candidateRoundId}/recording-url`,
      ),
      v2Client.get<{
        segments: Array<{ speaker: string; text: string; ts_start: number; ts_end: number }>;
        duration_seconds: number | null;
        word_count: number | null;
        // Surfaced by the backend from recall_bots.feedback_started_at
        // minus joined_at; drives the interview ↔ feedback segment toggle
        // in the drawer's Round Replay tab.
        feedback_start_seconds?: number | null;
      }>(`/api/v2/candidate-rounds/${candidateRoundId}/transcript`),
    ]);
    const url = urlRes.status === 'fulfilled' ? urlRes.value.url : '';
    const transcript = tx.status === 'fulfilled' ? tx.value : null;
    const segments = transcript
      ? transcript.segments.map((s) => ({
          start_seconds: s.ts_start,
          end_seconds: s.ts_end,
          speaker: s.speaker,
          text: s.text,
        }))
      : [];
    return {
      candidate_round_id: candidateRoundId,
      recording_url: url,
      transcript_excerpt: segments
        .slice(0, 2)
        .map((s) => s.text)
        .join(' ')
        .slice(0, 240),
      transcript_segments: segments,
      duration_seconds: transcript?.duration_seconds ?? 0,
      feedback_start_seconds: transcript?.feedback_start_seconds ?? null,
      available: Boolean(url),
    };
  }
  await simulate();
  const db = getDb();
  const cr = db.candidate_rounds.find((x) => x.id === candidateRoundId);
  if (!cr) throw new ServiceError('not_found', `CandidateRound ${candidateRoundId} not found`);
  const existing = db.recordings.find((r) => r.candidate_round_id === candidateRoundId);
  if (existing) return structuredClone(existing);

  const isComplete = cr.status === 'completed';
  // Derive duration from the joined round; CandidateRound doesn't store it directly.
  const round = db.requisitions.flatMap((r) => r.rounds).find((r) => r.id === cr.round_id);
  const totalSeconds = round?.duration_minutes ? round.duration_minutes * 60 : 2700;
  const feedbackStart = isComplete ? Math.max(0, totalSeconds - 240) : null;
  const interviewerName = cr.interviewer_name ?? 'Interviewer';
  const candidateName = db.candidates.find((c) => c.id === cr.candidate_id)?.name ?? 'Candidate';

  const stub: RoundRecording = {
    candidate_round_id: candidateRoundId,
    recording_url: `#recording/${candidateRoundId}`,
    transcript_excerpt: isComplete
      ? 'We walked through a product teardown of Stripe Billing. Strong grasp of tradeoffs between usage-based and seat-based pricing; some hesitation on SRE pushback.'
      : '',
    transcript_segments: isComplete
      ? buildSyntheticTranscript(
          totalSeconds,
          feedbackStart ?? totalSeconds,
          candidateName,
          interviewerName,
        )
      : [],
    feedback_start_seconds: feedbackStart,
    duration_seconds: totalSeconds,
    available: isComplete,
  };
  db.recordings.push(stub);
  persist();
  return structuredClone(stub);
}

function buildSyntheticTranscript(
  totalSeconds: number,
  feedbackStart: number,
  candidateName: string,
  interviewerName: string,
): RoundRecording['transcript_segments'] {
  const segs: RoundRecording['transcript_segments'] = [];

  const interviewLines: Array<[string, string]> = [
    [
      interviewerName,
      "Thanks for jumping on. Walk me through what you've been working on most recently.",
    ],
    [
      candidateName,
      'Sure — I led an end-to-end rollout of our billing system migration. Owned scoping, stakeholder buy-in, and the rollout plan.',
    ],
    [interviewerName, 'What was the hardest tradeoff you had to make?'],
    [
      candidateName,
      'Probably between speed and observability. We chose to ship the migration in two phases so we could instrument before fully cutting over.',
    ],
    [interviewerName, 'What metrics did you watch?'],
    [
      candidateName,
      'Activation funnel weekly, billing-error rate daily, and a custom revenue-protection dashboard for the cutover window.',
    ],
    [interviewerName, 'How did you handle pushback from the SRE team?'],
    [
      candidateName,
      'I built a shared runbook with them up front and gave them veto on the rollout schedule. We rehearsed the cutover twice in staging.',
    ],
    [interviewerName, 'Tell me about a time you missed a deadline.'],
    [
      candidateName,
      'On the Q3 launch — we underscoped the migration testing. I owned the slip publicly and we shipped two weeks late but with zero incidents in prod.',
    ],
    [interviewerName, 'What would you do differently next time?'],
    [
      candidateName,
      'Spec out the test matrix earlier. We treated it as a checklist instead of a design problem. That cost us.',
    ],
  ];

  const feedbackLines: Array<[string, string]> = [
    [interviewerName, 'Yes, I can give feedback now.'],
    [
      interviewerName,
      'Strong on ownership signals — clear examples, measured tradeoffs, accountable on the slip.',
    ],
    [
      interviewerName,
      'Wanted more on cross-functional conflict; the SRE example was good but a bit rehearsed.',
    ],
    [interviewerName, "Verdict: yes. I'd want to see one more round on system design depth."],
  ];

  const interviewSpan = feedbackStart;
  const interviewStep = interviewSpan / interviewLines.length;
  interviewLines.forEach(([speaker, text], i) => {
    const start = Math.floor(i * interviewStep);
    const end = Math.min(interviewSpan, Math.floor((i + 1) * interviewStep));
    segs.push({ start_seconds: start, end_seconds: end, speaker, text });
  });

  if (feedbackStart < totalSeconds) {
    const feedbackSpan = totalSeconds - feedbackStart;
    const feedbackStep = feedbackSpan / feedbackLines.length;
    feedbackLines.forEach(([speaker, text], i) => {
      const start = Math.floor(feedbackStart + i * feedbackStep);
      const end = Math.min(totalSeconds, Math.floor(feedbackStart + (i + 1) * feedbackStep));
      segs.push({ start_seconds: start, end_seconds: end, speaker, text });
    });
  }

  return segs;
}
