import type { FinalVerdict, RoundRating } from './enums';

export interface DebriefCandidateRow {
  candidate_id: string;
  candidate_name: string;
  overall_rating: RoundRating | null;
  final_verdict: FinalVerdict | null;
  rounds_completed: number;
  rounds_total: number;
  top_strengths: string[];
  top_concerns: string[];
}

export interface Debrief {
  requisition_id: string;
  generated_at: string;
  candidates: DebriefCandidateRow[];
}

export interface DebriefInsight {
  requisition_id: string;
  summary: string;
  strongest_candidate_id: string | null;
  risk_notes: string[];
  recommended_next_steps: string[];
}
