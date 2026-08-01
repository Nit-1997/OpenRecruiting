import type {
  CandidateRoundStatus,
  CandidateStatus,
  FinalVerdict,
  RoundRating,
  ScorecardStatus,
} from './enums';

export interface ScorecardItem {
  id: string;
  candidate_round_id: string;
  dimension: string;
  rating: RoundRating | null;
  notes: string;
}

// Structured candidate-authenticity signals computed after a screening call by
// the backend ScreeningFeedbackService and stored on
// candidate_rounds.authenticity_signals (migration 117). This is a DIRECTIONAL
// recruiter signal — NOT a pass/fail gate. Latency analysis is intentionally
// absent (the persisted transcript has no reliable per-turn timestamps yet).
export type AuthenticityOverall = 'likely_authentic' | 'some_concern' | 'high_concern';
export type AuthenticityLevel = 'low' | 'medium' | 'high';
export type AuthenticitySignalKind = 'specificity' | 'consistency' | 'read_aloud';

export interface AuthenticitySignal {
  kind: AuthenticitySignalKind;
  level: AuthenticityLevel;
  note: string;
}

export interface AuthenticitySignals {
  overall: AuthenticityOverall;
  confidence: number;
  signals: AuthenticitySignal[];
  summary: string;
}

// Backend canonical: candidate_rounds (id, candidate_id, round_id, status, scheduled_at,
//   completed_at, summary, rating, scorecard_status, question_summaries jsonb,
//   interviewer_email, interviewer_email_verified, scheduling_timezone, meeting_url,
//   bot_session_id, transcript_url, recording_url, processing_status,
//   outcome ('advance'|'reject'|'hold'), outcome_notes,
//   feedback_approved_at, feedback_approved_by_email).
//
// Notes:
// - interviewer_name is NOT a DB column; it's denormalized in the API response for display
//   (the schedule endpoint accepts it as input but it's stored alongside email-tied profile lookup).
// - interview_duration_minutes is NOT stored; derive from rounds.duration_minutes via the join.
// - scorecard is the denormalized list of candidate_feedback entries mapped to dimensions
//   (feedback_question.heading) for the UI; computed in the read response.
export interface CandidateRound {
  id: string;
  candidate_id: string;
  round_id: string;
  status: CandidateRoundStatus;
  scorecard_status: ScorecardStatus;
  rating: RoundRating | null;
  summary: string;
  question_summaries: Record<string, string>;
  // Structured screening authenticity signals (migration 117). Null for rounds
  // that aren't screening rounds or that haven't been processed yet.
  authenticity_signals: AuthenticitySignals | null;
  feedback_approved_at: string | null;
  feedback_approved_by_email: string | null;
  scheduled_at: string | null;
  // IANA timezone name persisted alongside scheduled_at so the drawer can
  // render the schedule back in the recruiter's chosen zone. Returned by
  // the packet RPC (migration 88). Null for pre-v2 rows.
  scheduling_timezone: string | null;
  completed_at: string | null;
  interviewer_email: string | null;
  interviewer_name: string | null;
  meeting_url: string | null;
  scorecard: ScorecardItem[];
}

// Structured candidate profile produced by ATS resume enrichment and stored on
// candidates.profile (JSONB). Populated only for ATS-imported candidates whose
// resume has been enriched — null for manual / not-yet-enriched candidates.
// Every sub-field is optional/nullable: the enrichment model fills what it can.
export interface ResumeWorkEntry {
  title: string | null;
  company: string | null;
  start: string | null;
  end: string | null;
  is_current: boolean;
  highlights: string[];
}

export interface ResumeEducationEntry {
  degree: string | null;
  field: string | null;
  institution: string | null;
  year: string | null;
}

export type ResumeSeniority = 'early' | 'mid' | 'senior' | 'staff' | 'principal';

export interface ResumeProfile {
  summary: string;
  headline: string | null;
  total_experience_years: number | null;
  seniority: ResumeSeniority | null;
  skills: string[];
  domains: string[];
  work_history: ResumeWorkEntry[];
  education: ResumeEducationEntry[];
  achievements: string[];
  certifications: string[];
  languages: string[];
}

export interface AtsScreeningAnswer {
  question: string;
  type: string;
  answer: string;
}

export interface AtsRejection {
  reason: string;
  rejected_at: string;
}

export interface AtsStage {
  id: string;
  name: string;
}

export interface AtsSignals {
  location: string | null;
  applied_at: string | null;
  screening_qa: AtsScreeningAnswer[];
  rejection: AtsRejection | null;
  stage: AtsStage | null;
}

export interface CandidateProfileLinks {
  linkedin: string | null;
  github: string | null;
  portfolio: string | null;
}

export interface CandidateProfile {
  schema_version: number;
  resume: ResumeProfile | null;
  ats: AtsSignals | null;
  links: CandidateProfileLinks | null;
  extracted_at: string | null;
  model: string | null;
  source: string | null;
}

// Backend canonical: candidates (id, requisition_id, name, email, phone, resume_url,
//   status, final_verdict (nullable), profile (jsonb, nullable), deleted_at).
//
// Notes:
// - avatar_initials / avatar_color are derived in the API response from name; no column.
// - current_round_id is derived from the first non-completed candidate_round; no column.
// - tags and source are NOT in the DB today; deferred until columns are added. UI may
//   send `source` on create; backend ignores until column exists.
// - profile is the structured ATS resume-enrichment payload (JSONB). The packet RPC
//   serializes the whole candidates row, so it carries through to CandidatePacket.candidate.
//   Null for manual / non-ATS / not-yet-enriched candidates.
export interface Candidate {
  id: string;
  requisition_id: string;
  name: string;
  email: string;
  phone: string | null;
  resume_url: string | null;
  avatar_initials: string;
  avatar_color: string;
  status: CandidateStatus;
  final_verdict: FinalVerdict | null;
  current_round_id: string | null;
  tags: string[];
  source: string;
  // Structured ATS resume-enrichment payload (candidates.profile JSONB). Null
  // for manual / non-ATS / not-yet-enriched candidates. Optional so the mock-DB
  // path and pre-enrichment rows can omit it entirely.
  profile?: CandidateProfile | null;
  // Pipeline RPC (GET /roles/{id}/candidates) returns each candidate with its
  // ordered candidate_rounds *and* the round header embedded on each one. The
  // pipeline rail reads from this nested data so it can render custom rounds
  // (which aren't in the requisition's shared /plan response). Optional so the
  // mock-DB path and packet-only consumers can omit it.
  candidate_rounds?: PipelineCandidateRound[];
  created_at: string;
  updated_at: string;
}

// Embedded round header on each pipeline candidate_round entry. Matches the
// jsonb shape produced by get_role_pipeline (spec §6.1). Subset of `Round` —
// no skills/guidelines/feedback_questions, since the pipeline view doesn't
// need them.
export interface PipelineRoundHeader {
  id: string;
  round_number: number;
  name: string;
  category: string;
  duration_minutes: number;
  is_custom?: boolean;
  for_candidate_id?: string | null;
}

// candidate_round + embedded round header. Used only by the pipeline rail.
// The flat CandidateRound is preserved for everywhere else.
export interface PipelineCandidateRound extends CandidateRound {
  round: PipelineRoundHeader;
}

export interface CandidateCreateInput {
  name: string;
  email: string;
  phone?: string;
  resume_url?: string;
  source?: string;
  tags?: string[];
}

export interface CandidateUpdateInput {
  name?: string;
  email?: string;
  phone?: string;
  resume_url?: string;
  tags?: string[];
  status?: CandidateStatus;
  final_verdict?: FinalVerdict | null;
}

// Backend canonical: POST /candidate-rounds/{cr_id}/schedule accepts
//   scheduled_at (ISO-8601 with TZ offset, e.g. 2026-04-01T10:00:00-04:00),
//   interviewer_email, interviewer_name?, meeting_url?, scheduling_timezone?
//
// `scheduling_timezone` is the IANA name the recruiter picked (e.g.
// "America/New_York"). v1 persists it on candidate_rounds.scheduling_timezone
// (migration 23) and uses it to render the schedule back in the recruiter's
// chosen zone — v2 mirrors that contract per migration 88.
//
// duration_minutes was removed — it was never persisted (no candidate_rounds
// column) and the canonical duration lives on rounds.duration_minutes.
export interface ScheduleInterviewInput {
  scheduled_at: string;
  // Optional — v1/v2 contract: recruiters often schedule before they know
  // who's interviewing. The bot can still be created from `meeting_url`
  // alone; the email is used downstream for feedback reminders.
  interviewer_email?: string;
  interviewer_name?: string;
  // Required on the FE for interview rounds (the recording bot needs it);
  // optional in the type because the BE accepts assessment rounds with no
  // URL.
  meeting_url?: string;
  scheduling_timezone?: string;
}

export interface RescheduleInterviewInput {
  scheduled_at?: string;
  interviewer_email?: string;
  interviewer_name?: string;
  meeting_url?: string;
  scheduling_timezone?: string;
}
