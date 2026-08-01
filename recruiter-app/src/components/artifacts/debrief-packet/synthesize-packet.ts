// Packet synthesis for the comparative debrief artifact. Extracted out of the
// view component so `DebriefPacketArtifact` is presentational: this module owns
// the pure ranking + decision-matrix + verdict math, fed by the candidate and
// score fixtures. No React here — it is a plain, testable transform.

import { getCandidatesByIds } from '@/fixtures/candidates';
import { type CandidateScoreSet, getScoreForCandidate } from '@/fixtures/comparative-scores';
import type {
  DebriefCandidateSnapshot,
  DebriefDecisionRow,
  DebriefPacket,
  DebriefVerdict,
} from '@/fixtures/debrief-packets';
import { SCORECARD_DIMENSIONS } from '@/fixtures/scorecard-dimensions';

function verdictFromTotal(total: number): DebriefVerdict {
  if (total >= 3.5) return 'strong_hire';
  if (total >= 3.0) return 'hire';
  if (total >= 2.5) return 'mixed';
  return 'no_hire';
}

function shortHeadline(scores: CandidateScoreSet): string {
  if (scores.strengths[0]) return scores.strengths[0];
  return `Weighted ${scores.total.toFixed(1)} / 4 across the rubric.`;
}

export function synthesizePacket(reqId: string, candidateIds: string[]): DebriefPacket | null {
  const cands = getCandidatesByIds(reqId, candidateIds);
  if (cands.length === 0) return null;

  const ranked = [...cands].sort((a, b) => {
    const sa = getScoreForCandidate(a.id).total;
    const sb = getScoreForCandidate(b.id).total;
    return sb - sa;
  });

  const snapshots: DebriefCandidateSnapshot[] = ranked.map((c, idx) => {
    const scores = getScoreForCandidate(c.id);
    return {
      candidate_id: c.id,
      name: c.name,
      initials: c.avatar,
      color: c.color,
      rank: idx + 1,
      aggregate_score: scores.total,
      score_scale: 4,
      rounds_completed: c.scoresIn,
      rounds_total: c.rounds,
      verdict: verdictFromTotal(scores.total),
      headline: shortHeadline(scores),
      top_strengths: scores.strengths.slice(0, 3),
      top_concerns: scores.concerns.slice(0, 3),
      recommendation:
        idx === 0
          ? 'Advance to offer with a values-anchored closer in week one.'
          : scores.total >= 3
            ? 'Keep warm — viable backup if the top candidate declines.'
            : 'Do not advance — debrief the gap with the hiring manager.',
      panel_votes: [],
    };
  });

  const decision_matrix: DebriefDecisionRow[] = SCORECARD_DIMENSIONS.map((dim) => {
    const scores: Record<string, number> = {};
    for (const c of ranked) {
      const set = getScoreForCandidate(c.id);
      const cell = set[dim.id as keyof CandidateScoreSet];
      if (cell && typeof cell === 'object' && 'value' in cell) {
        scores[c.id] = (cell as { value: number }).value;
      }
    }
    const vals = Object.values(scores);
    const maxScore = vals.length > 0 ? Math.max(...vals) : 0;
    const winner_ids = Object.entries(scores)
      .filter(([, v]) => v === maxScore)
      .map(([k]) => k);
    return {
      dimension: dim.title,
      note: dim.description,
      scores,
      winner_ids,
    };
  });

  const top = ranked[0];
  const topScores = top ? getScoreForCandidate(top.id) : null;

  const packet: DebriefPacket = {
    id: `synth-${reqId}-${candidateIds.join('-')}`,
    requisition_id: reqId,
    role_title: 'Comparative debrief',
    title: 'Comparative debrief',
    subtitle: `${snapshots.length} candidates · ${SCORECARD_DIMENSIONS.length} rubric axes`,
    generated_at: new Date().toISOString(),
    generated_by: 'OpenRecruiting debrief agent',
    status: 'fresh',
    panel_members: [],
    candidates: snapshots,
    headline_recommendation: top
      ? `Advance ${top.name.split(' ')[0]} to offer — strongest aggregate signal across ${SCORECARD_DIMENSIONS.length} axes.`
      : 'No candidates selected.',
    verdict: topScores ? verdictFromTotal(topScores.total) : 'mixed',
    confidence:
      topScores && topScores.total >= 3.4
        ? 'high'
        : topScores && topScores.total >= 3
          ? 'medium'
          : 'low',
    source_stats: {
      scorecards: snapshots.reduce((s, c) => s + c.rounds_completed, 0),
      transcripts: snapshots.length,
    },
    themes: [
      { label: 'Execution signal', evidence_count: 4, weight: 3, tone: 'pos' },
      { label: 'Ambiguous tradeoffs', evidence_count: 2, weight: 2, tone: 'neg' },
      { label: 'Stakeholder alignment', evidence_count: 3, weight: 3, tone: 'pos' },
    ],
    decision_matrix,
    risks:
      topScores && topScores.total < 3.5
        ? [
            `Top candidate is ${topScores.total.toFixed(1)} / 4 — confirm one more reference before offer.`,
          ]
        : [],
    next_steps: [
      { label: 'Schedule offer committee review', owner: 'Recruiter' },
      { label: 'Request one back-channel reference', owner: 'Hiring manager' },
    ],
  };
  return packet;
}
