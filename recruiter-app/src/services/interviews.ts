import type { CandidateRound, RescheduleInterviewInput, ScheduleInterviewInput } from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import { notImplementedInV2, ServiceError } from './service-error';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Opt-in handle so callers that already have the candidate_round id (the
// packet drawer does) can skip the extra GET /packet round-trip required
// to map (req, candidate, round) -> cr_id. Optional everywhere for
// backward compat with callers that don't have the cr_id at hand.
export interface V2CrIdOption {
  crId?: string;
}

// Shape of the v2 schedule response. Used to surface bot scheduling status
// and assessment access codes back to the recruiter (activity feed,
// future toast affordances). Both fields are nullable: bot is only created
// when meeting_url is supplied; assessment_instance only when the round
// has a template.
interface V2ScheduleResponse {
  candidate_round: CandidateRound;
  assessment_instance: {
    id?: string;
    access_code?: string;
    candidate_email?: string;
    expires_at?: string | null;
  } | null;
  bot: {
    id?: string;
    recall_bot_id?: string;
    status?: string;
    meeting_url?: string | null;
    scheduled_at?: string | null;
  } | null;
}

interface V2RescheduleResponse {
  candidate_round: CandidateRound;
  bot: V2ScheduleResponse['bot'];
}

function findCr(reqId: string, candidateId: string, roundId: string): CandidateRound {
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const cr = db.candidate_rounds.find(
    (x) => x.candidate_id === candidateId && x.round_id === roundId,
  );
  if (!cr) throw new ServiceError('not_found', 'CandidateRound not found');
  return cr;
}

// Resolve the `cr_id` for (reqId, candidateId, roundId) by reading the packet.
// Used only when the caller didn't pass `opts.crId` directly. The packet RPC
// returns rounds in the nested `{ round, candidate_round }` shape (per
// migrations 81 + 85).
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

async function resolveCrId(
  reqId: string,
  candidateId: string,
  roundId: string,
  opts?: V2CrIdOption,
): Promise<string> {
  if (opts?.crId) return opts.crId;
  return resolveCrIdFromPacket(reqId, candidateId, roundId);
}

// Push a local activity row so the recruiter's activity feed reflects the
// schedule/reschedule/cancel even though the v2 backend doesn't expose an
// activities API yet. Mirrors the structure the mock-DB path writes so the
// UI doesn't care which path produced the entry.
function appendLocalActivity(
  reqId: string,
  candidateId: string,
  entry: {
    type: 'interview:scheduled' | 'interview:rescheduled' | 'interview:cancelled';
    title: string;
    description: string;
  },
): void {
  try {
    const db = getDb();
    db.activity.unshift({
      id: generateId('act'),
      type: entry.type,
      title: entry.title,
      description: entry.description,
      actor_name: 'Nitin',
      requisition_id: reqId,
      candidate_id: candidateId,
      created_at: nowIso(),
    });
    persist();
    emit('activity:created');
  } catch {
    // Activity store is best-effort UX glue; never let it block a v2 mutation.
  }
}

function summariseBot(bot: V2ScheduleResponse['bot']): string | null {
  if (!bot || !bot.status) return null;
  if (bot.status === 'created' || bot.status === 'joining') {
    return 'Recording bot scheduled';
  }
  return `Recording bot status: ${bot.status}`;
}

function summariseAssessment(instance: V2ScheduleResponse['assessment_instance']): string | null {
  if (!instance?.access_code) return null;
  return `Assessment access code: ${instance.access_code}`;
}

export async function schedule(
  reqId: string,
  candidateId: string,
  roundId: string,
  input: ScheduleInterviewInput,
  opts?: V2CrIdOption,
): Promise<CandidateRound> {
  if (isV2ApiEnabled()) {
    const crId = await resolveCrId(reqId, candidateId, roundId, opts);
    const result = await v2Client.post<V2ScheduleResponse>(
      `/api/v2/candidate-rounds/${crId}/schedule`,
      input,
    );
    emit('candidate_round:updated', result.candidate_round);

    // Local activity feed entries — parity with the mock-DB path until the
    // v2 backend ships an activities API. One main "scheduled" row plus
    // optional follow-ups for the bot and the assessment access code.
    const whenLabel = new Date(input.scheduled_at).toLocaleString();
    appendLocalActivity(reqId, candidateId, {
      type: 'interview:scheduled',
      title: 'Interview scheduled',
      description: `${input.interviewer_name ?? input.interviewer_email} · ${whenLabel}.`,
    });
    const botMsg = summariseBot(result.bot);
    if (botMsg) {
      appendLocalActivity(reqId, candidateId, {
        type: 'interview:scheduled',
        title: botMsg,
        description: input.meeting_url ?? '',
      });
    }
    const assessmentMsg = summariseAssessment(result.assessment_instance);
    if (assessmentMsg) {
      appendLocalActivity(reqId, candidateId, {
        type: 'interview:scheduled',
        title: assessmentMsg,
        description: result.assessment_instance?.candidate_email
          ? `Sent to ${result.assessment_instance.candidate_email}`
          : '',
      });
    }
    return result.candidate_round;
  }
  await simulate();
  if (!input.scheduled_at || Number.isNaN(Date.parse(input.scheduled_at))) {
    throw new ServiceError('validation', 'scheduled_at must be a valid ISO timestamp', {
      field: 'scheduled_at',
    });
  }
  // interviewer_email is optional — only validate format when supplied.
  if (input.interviewer_email && !EMAIL_RE.test(input.interviewer_email)) {
    throw new ServiceError('validation', 'interviewer_email must be valid', {
      field: 'interviewer_email',
    });
  }
  const cr = findCr(reqId, candidateId, roundId);
  if (cr.status === 'completed') {
    throw new ServiceError('invalid_state', 'Cannot schedule a completed round');
  }
  cr.status = 'scheduled';
  cr.scheduled_at = input.scheduled_at;
  cr.interviewer_email = input.interviewer_email ?? null;
  cr.interviewer_name = input.interviewer_name ?? null;
  if (input.meeting_url !== undefined) cr.meeting_url = input.meeting_url;
  const db = getDb();
  db.activity.unshift({
    id: generateId('act'),
    type: 'interview:scheduled',
    title: 'Interview scheduled',
    description: `${input.interviewer_name ?? input.interviewer_email} · ${new Date(input.scheduled_at).toLocaleString()}.`,
    actor_name: 'Nitin',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: nowIso(),
  });
  persist();
  emit('candidate_round:updated', cr);
  emit('activity:created');
  return structuredClone(cr);
}

export async function reschedule(
  reqId: string,
  candidateId: string,
  roundId: string,
  input: RescheduleInterviewInput,
  opts?: V2CrIdOption,
): Promise<CandidateRound> {
  if (isV2ApiEnabled()) {
    const crId = await resolveCrId(reqId, candidateId, roundId, opts);
    const result = await v2Client.put<V2RescheduleResponse>(
      `/api/v2/candidate-rounds/${crId}/schedule`,
      input,
    );
    emit('candidate_round:updated', result.candidate_round);

    const whenLabel = input.scheduled_at ? new Date(input.scheduled_at).toLocaleString() : null;
    appendLocalActivity(reqId, candidateId, {
      type: 'interview:rescheduled',
      title: 'Interview rescheduled',
      description: whenLabel ? `Moved to ${whenLabel}.` : 'Interview details updated.',
    });
    const botMsg = summariseBot(result.bot);
    if (botMsg) {
      appendLocalActivity(reqId, candidateId, {
        type: 'interview:rescheduled',
        title: botMsg,
        description: input.meeting_url ?? '',
      });
    }
    return result.candidate_round;
  }
  await simulate();
  const cr = findCr(reqId, candidateId, roundId);
  if (cr.status !== 'scheduled') {
    throw new ServiceError('invalid_state', 'Only scheduled rounds can be rescheduled');
  }
  if (input.scheduled_at && Number.isNaN(Date.parse(input.scheduled_at))) {
    throw new ServiceError('validation', 'scheduled_at must be a valid ISO timestamp');
  }
  if (input.scheduled_at !== undefined) cr.scheduled_at = input.scheduled_at;
  if (input.interviewer_email !== undefined) cr.interviewer_email = input.interviewer_email;
  if (input.interviewer_name !== undefined) cr.interviewer_name = input.interviewer_name ?? null;
  if (input.meeting_url !== undefined) cr.meeting_url = input.meeting_url ?? null;
  const db = getDb();
  db.activity.unshift({
    id: generateId('act'),
    type: 'interview:rescheduled',
    title: 'Interview rescheduled',
    description: `${cr.interviewer_name ?? cr.interviewer_email ?? 'Interview'} moved to ${cr.scheduled_at ? new Date(cr.scheduled_at).toLocaleString() : 'TBD'}.`,
    actor_name: 'Nitin',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: nowIso(),
  });
  persist();
  emit('candidate_round:updated', cr);
  emit('activity:created');
  return structuredClone(cr);
}

export async function cancel(
  reqId: string,
  candidateId: string,
  roundId: string,
  opts?: V2CrIdOption,
): Promise<CandidateRound> {
  if (isV2ApiEnabled()) {
    const crId = await resolveCrId(reqId, candidateId, roundId, opts);
    const result = await v2Client.post<{ candidate_round: CandidateRound }>(
      `/api/v2/candidate-rounds/${crId}/cancel`,
    );
    emit('candidate_round:updated', result.candidate_round);
    appendLocalActivity(reqId, candidateId, {
      type: 'interview:cancelled',
      title: 'Interview cancelled',
      description: 'Interview removed from the schedule.',
    });
    return result.candidate_round;
  }
  await simulate();
  const cr = findCr(reqId, candidateId, roundId);
  if (cr.status === 'completed') {
    throw new ServiceError('invalid_state', 'Cannot cancel a completed round');
  }
  cr.status = 'cancelled';
  cr.scheduled_at = null;
  cr.interviewer_email = null;
  cr.interviewer_name = null;
  cr.meeting_url = null;
  const db = getDb();
  db.activity.unshift({
    id: generateId('act'),
    type: 'interview:cancelled',
    title: 'Interview cancelled',
    description: 'Interview removed from the schedule.',
    actor_name: 'Nitin',
    requisition_id: reqId,
    candidate_id: candidateId,
    created_at: nowIso(),
  });
  persist();
  emit('candidate_round:updated', cr);
  emit('activity:created');
  return structuredClone(cr);
}

export async function sendReminder(candidateRoundId: string): Promise<{ sent: true }> {
  if (isV2ApiEnabled()) throw notImplementedInV2('interviews.sendReminder');
  await simulate();
  const db = getDb();
  const cr = db.candidate_rounds.find((x) => x.id === candidateRoundId);
  if (!cr) throw new ServiceError('not_found', `CandidateRound ${candidateRoundId} not found`);
  if (cr.status !== 'scheduled') {
    throw new ServiceError('invalid_state', 'Reminders can only be sent for scheduled rounds');
  }
  db.activity.unshift({
    id: generateId('act'),
    type: 'interview:scheduled',
    title: 'Reminder sent',
    description: `Reminder delivered to ${cr.interviewer_email}.`,
    actor_name: 'Nitin',
    requisition_id: null,
    candidate_id: cr.candidate_id,
    created_at: nowIso(),
  });
  persist();
  emit('activity:created');
  return { sent: true };
}
