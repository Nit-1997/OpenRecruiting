import type { ScorecardDimension } from './scorecard-dimensions';

export interface CandidateScore {
  value: number; // 1..4
  note?: string;
}

export interface CandidateScoreSet {
  prioritization: CandidateScore;
  stakeholder: CandidateScore;
  ownership: CandidateScore;
  systems: CandidateScore;
  strengths: string[];
  concerns: string[];
  total: number;
}

type DimensionId = ScorecardDimension['id'];

export const COMPARATIVE_SCORES: Record<string, CandidateScoreSet> = {
  c1: {
    prioritization: { value: 4, note: 'Used quantified trade-offs in every panel.' },
    stakeholder: { value: 3.5, note: 'Aligned 3 partners inside a single tense meeting.' },
    ownership: { value: 3.5, note: 'Shipped the Ads retention fix end-to-end.' },
    systems: { value: 3.5, note: 'Strongest systems thinker in the loop.' },
    strengths: ['Strongest systems thinker on the loop', 'Aligned 3 stakeholders in one meeting'],
    concerns: ['Less shipping velocity vs. peers'],
    total: 3.6,
  },
  c2: {
    prioritization: { value: 3.5, note: 'Clear rubric on cost/value/effort.' },
    stakeholder: { value: 3.5, note: 'Great cross-functional glue.' },
    ownership: { value: 3.5, note: 'Highest execution signal in the loop.' },
    systems: { value: 3, note: 'Less depth on ambiguous trade-offs.' },
    strengths: ['Highest execution signal', 'Strong cross-functional glue'],
    concerns: ['Less depth on ambiguous tradeoffs'],
    total: 3.4,
  },
  c3: {
    prioritization: { value: 3, note: 'Framed, but slow to decide.' },
    stakeholder: { value: 3, note: 'Strong craft of written comms.' },
    ownership: { value: 3, note: 'Led UX systems for 2 quarters.' },
    systems: { value: 2.5, note: 'Panel flagged speed-to-decision.' },
    strengths: ['Strong craft for complex UX', 'Good written comms'],
    concerns: ['Inconsistent on prioritization framing', 'Panel flagged speed-to-decision'],
    total: 2.9,
  },
  c4: {
    prioritization: { value: 3.5, note: 'Closed a $4M decision last role.' },
    stakeholder: { value: 3, note: 'Calm under challenge.' },
    ownership: { value: 3.5, note: 'Owned infra migration end-to-end.' },
    systems: { value: 3, note: 'Pending CV round.' },
    strengths: ['Closed a $4M decision in last role', 'Calm under challenge'],
    concerns: ['CV round still outstanding'],
    total: 3.2,
  },
  c5: {
    prioritization: { value: 3, note: 'Solid framing, clear bets.' },
    stakeholder: { value: 3.5, note: 'Best narrative and alignment.' },
    ownership: { value: 3, note: 'Consistent delivery cadence.' },
    systems: { value: 3, note: 'CV round outstanding.' },
    strengths: ['Best alignment & narrative'],
    concerns: ['Weaker systems signal', 'CV round outstanding'],
    total: 3.1,
  },
  c6: {
    prioritization: { value: 3, note: 'Early signal is promising.' },
    stakeholder: { value: 2.5, note: 'Limited data from screen alone.' },
    ownership: { value: 3, note: 'Not enough signal yet.' },
    systems: { value: 2.5, note: 'Only 1 scorecard in.' },
    strengths: ['Early signal is promising'],
    concerns: ['Only 1 scorecard in — not enough signal yet'],
    total: 2.7,
  },
  c7: {
    prioritization: { value: 3.5 },
    stakeholder: { value: 3.5 },
    ownership: { value: 3.5 },
    systems: { value: 3.5 },
    strengths: ['Strong across all rubric axes', 'Great calm under pressure'],
    concerns: ['None major'],
    total: 3.5,
  },
  c8: {
    prioritization: { value: 3 },
    stakeholder: { value: 3 },
    ownership: { value: 3 },
    systems: { value: 3 },
    strengths: ['Pending panel — looking promising'],
    concerns: ['Only 2 scorecards in'],
    total: 3.0,
  },
  c9: {
    prioritization: { value: 3 },
    stakeholder: { value: 2.5 },
    ownership: { value: 3 },
    systems: { value: 3 },
    strengths: ['Thoughtful under ambiguity'],
    concerns: ['Panel split — needs alignment call'],
    total: 2.9,
  },
  c10: {
    prioritization: { value: 3 },
    stakeholder: { value: 3 },
    ownership: { value: 3 },
    systems: { value: 3 },
    strengths: ['Promising screen signal'],
    concerns: ['Only recruiter screen completed'],
    total: 3.0,
  },
  c11: {
    prioritization: { value: 3 },
    stakeholder: { value: 3 },
    ownership: { value: 3 },
    systems: { value: 3 },
    strengths: ['Balanced rubric coverage'],
    concerns: ['CV round outstanding'],
    total: 3.0,
  },
  c12: {
    prioritization: { value: 3.5 },
    stakeholder: { value: 3 },
    ownership: { value: 3.5 },
    systems: { value: 3 },
    strengths: ['Strong execution record'],
    concerns: ['Less systems depth than top peers'],
    total: 3.3,
  },
  c13: {
    prioritization: { value: 2.5 },
    stakeholder: { value: 2.5 },
    ownership: { value: 2.5 },
    systems: { value: 2.5 },
    strengths: ['Early screen signal'],
    concerns: ['Only screen completed'],
    total: 2.5,
  },
  c14: {
    prioritization: { value: 3 },
    stakeholder: { value: 2.5 },
    ownership: { value: 3 },
    systems: { value: 2.5 },
    strengths: ['Panel completed'],
    concerns: ['Mixed signal'],
    total: 2.8,
  },
  c15: {
    prioritization: { value: 3 },
    stakeholder: { value: 3 },
    ownership: { value: 3 },
    systems: { value: 3 },
    strengths: ['Take-home submitted'],
    concerns: ['Waiting on rubric review'],
    total: 3.0,
  },
  c16: {
    prioritization: { value: 2.5 },
    stakeholder: { value: 2.5 },
    ownership: { value: 2.5 },
    systems: { value: 2.5 },
    strengths: ['Fresh outreach'],
    concerns: ['Sourced, not yet engaged'],
    total: 2.5,
  },
};

const DEFAULT_SCORE: CandidateScoreSet = {
  prioritization: { value: 3 },
  stakeholder: { value: 3 },
  ownership: { value: 3 },
  systems: { value: 3 },
  strengths: ['Balanced across rubric'],
  concerns: ['Limited signal'],
  total: 3.0,
};

export function getScoreForCandidate(candidateId: string): CandidateScoreSet {
  return COMPARATIVE_SCORES[candidateId] ?? DEFAULT_SCORE;
}

export function getScoreValue(candidateId: string, dimensionId: DimensionId): number {
  const scores = getScoreForCandidate(candidateId);
  if (dimensionId === 'prioritization') return scores.prioritization.value;
  if (dimensionId === 'stakeholder') return scores.stakeholder.value;
  if (dimensionId === 'ownership') return scores.ownership.value;
  if (dimensionId === 'systems') return scores.systems.value;
  return 0;
}
