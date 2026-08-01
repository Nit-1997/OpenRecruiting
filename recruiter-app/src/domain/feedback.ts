import type { EvidenceStatus, FeedbackSource, RoundRating } from './enums';

// Backend canonical: candidate_feedback (id, candidate_round_id, feedback_question_id,
//   feedback_text, evidence jsonb, evidence_status, source ('manual'|'bot'), created_at, updated_at)
export interface FeedbackEntry {
  id: string;
  candidate_round_id: string;
  feedback_question_id: string;
  feedback_text: string;
  evidence_status: EvidenceStatus;
  evidence: string[];
  source: FeedbackSource;
  created_at: string;
}

export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  speaker: string;
  text: string;
}

// Backend recording metadata; recording_url is fetched lazily on Play click via
// GET /candidate-rounds/{cr_id}/recording-url (Recall.ai pre-signed S3, expires).
export interface RoundRecording {
  candidate_round_id: string;
  recording_url: string;
  transcript_excerpt: string;
  transcript_segments: TranscriptSegment[];
  duration_seconds: number;
  feedback_start_seconds: number | null;
  available: boolean;
}

export interface FeedbackSubmissionEntry {
  feedback_question_id: string;
  rating: RoundRating;
  evidence_status: EvidenceStatus;
  feedback_text: string;
}

export interface FeedbackScorecardEntry {
  dimension: string;
  rating: RoundRating;
  notes: string;
}

export interface FeedbackSubmissionInput {
  entries: FeedbackSubmissionEntry[];
  scorecard: FeedbackScorecardEntry[];
  overall_rating: RoundRating;
  summary: string;
}

export interface FeedbackRequestInput {
  interviewer_email: string;
  interviewer_name?: string;
  channel: 'email' | 'slack' | 'both';
}
