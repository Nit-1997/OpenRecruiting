import type { Debrief, DebriefInsight, RoundRating } from '@/domain';
import { listCandidates, listPackets } from '@/lib/debrief/api';
import { isV2ApiEnabled } from '@/lib/env';
import { relativeTimeFrom } from '@/lib/relative-time';
import { simulate } from './latency';
import { getDb, nowIso } from './mock-db';
import { ServiceError } from './service-error';

const RATING_SCORE: Record<RoundRating, number> = {
  strong_yes: 5,
  yes: 4,
  maybe: 3,
  no: 2,
  strong_no: 1,
};

const RATING_BY_SCORE: Record<number, RoundRating> = {
  1: 'strong_no',
  2: 'no',
  3: 'maybe',
  4: 'yes',
  5: 'strong_yes',
};

function aggregate(candidateId: string): {
  overall: RoundRating | null;
  completed: number;
  total: number;
  strengths: string[];
  concerns: string[];
} {
  const db = getDb();
  const rounds = db.candidate_rounds.filter((cr) => cr.candidate_id === candidateId);
  const completed = rounds.filter((r) => r.status === 'completed');
  const scored = completed.filter((r) => r.rating);
  const avg = scored.length
    ? Math.round(
        scored.reduce((s, r) => s + (r.rating ? RATING_SCORE[r.rating] : 0), 0) / scored.length,
      )
    : 0;
  const overall = scored.length ? (RATING_BY_SCORE[avg] ?? null) : null;
  const strengths = completed.flatMap((r) =>
    r.scorecard
      .filter((s) => s.rating === 'strong_yes' || s.rating === 'yes')
      .map((s) => s.dimension),
  );
  const concerns = completed.flatMap((r) =>
    r.scorecard
      .filter((s) => s.rating === 'no' || s.rating === 'strong_no')
      .map((s) => s.dimension),
  );
  return { overall, completed: completed.length, total: rounds.length, strengths, concerns };
}

export async function get(reqId: string): Promise<Debrief> {
  if (isV2ApiEnabled()) {
    // Real data: the debrief candidate-picker endpoint returns each eligible
    // candidate with its rounds_completed/total. The legacy aggregate fields
    // (overall_rating / final_verdict / strengths / concerns) are NOT exposed
    // by that endpoint — they live in the full DebriefPacket (fetched per
    // packet). We surface only what the picker honestly knows and leave the
    // rest null/empty rather than fabricate. Consumers that need rich signal
    // read the real packet via the debrief flow.
    const items = await listCandidates(reqId);
    return {
      requisition_id: reqId,
      generated_at: nowIso(),
      candidates: items.map((c) => ({
        candidate_id: c.candidate_id,
        candidate_name: c.name,
        overall_rating: null,
        final_verdict: null,
        rounds_completed: c.rounds_completed,
        rounds_total: c.rounds_total,
        top_strengths: [],
        top_concerns: [],
      })),
    };
  }
  await simulate();
  const db = getDb();
  const req = db.requisitions.find((r) => r.id === reqId);
  if (!req) throw new ServiceError('not_found', `Requisition ${reqId} not found`);
  const candidates = db.candidates.filter((c) => c.requisition_id === reqId);
  return {
    requisition_id: reqId,
    generated_at: nowIso(),
    candidates: candidates.map((c) => {
      const agg = aggregate(c.id);
      return {
        candidate_id: c.id,
        candidate_name: c.name,
        overall_rating: agg.overall,
        final_verdict: c.final_verdict,
        rounds_completed: agg.completed,
        rounds_total: agg.total,
        top_strengths: agg.strengths.slice(0, 3),
        top_concerns: agg.concerns.slice(0, 3),
      };
    }),
  };
}

export async function getInsights(reqId: string): Promise<DebriefInsight> {
  if (isV2ApiEnabled()) {
    // Real data: derive the role-level insight summary from the newest debrief
    // packet (the packet list is newest-first). When no packet exists yet the
    // summary is a neutral prompt — never fabricated.
    const packets = await listPackets(reqId);
    const latest = packets[0] ?? null;
    return {
      requisition_id: reqId,
      summary: latest
        ? `Latest debrief packet generated ${relativeTimeFrom(
            latest.generated_at ?? latest.created_at,
          )}. Open it to review the recommendation.`
        : 'No debrief packets yet — compare two or more candidates to generate one.',
      strongest_candidate_id: latest?.candidate_ids[0] ?? null,
      risk_notes: [],
      recommended_next_steps: latest
        ? ['Open the latest debrief packet to review next steps.']
        : ['Compare two or more candidates in the Debrief agent to generate a packet.'],
    };
  }
  await simulate();
  const debrief = await get(reqId);
  const strongest = [...debrief.candidates]
    .filter((c) => c.overall_rating)
    .sort(
      (a, b) =>
        (a.overall_rating ? RATING_SCORE[a.overall_rating] : 0) -
        (b.overall_rating ? RATING_SCORE[b.overall_rating] : 0),
    )
    .reverse()[0];
  return {
    requisition_id: reqId,
    summary: strongest
      ? `${strongest.candidate_name} leads the pipeline with ${debrief.candidates.length} candidates evaluated.`
      : 'No completed evaluations yet.',
    strongest_candidate_id: strongest?.candidate_id ?? null,
    risk_notes: debrief.candidates
      .filter((c) => c.top_concerns.length)
      .map((c) => `${c.candidate_name}: ${c.top_concerns[0]}`),
    recommended_next_steps: strongest
      ? [`Move ${strongest.candidate_name} to offer stage.`, 'Close loop with panelists.']
      : ['Complete at least one full round to unlock insights.'],
  };
}
