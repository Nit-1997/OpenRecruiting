import type { RequisitionStatus, RoundCategory } from './enums';

// Backend canonical: feedback_questions (round_id, question_number, heading, description)
export interface FeedbackQuestion {
  id: string;
  round_id: string;
  question_number: number;
  heading: string;
  description: string;
}

// Backend canonical: rounds.guidelines JSONB array of {title, description}
export interface Guideline {
  title: string;
  description: string;
}

// UI-only screening agent state. No backend column yet — the v2 read API does not
// populate these. Plan-tab gracefully hides the section when undefined. When the
// feature is persisted, add columns: rounds.screening_agent_enabled, _voice, _questions.
export interface ScreeningAgentQuestion {
  id: string;
  order: number;
  dimension: string;
  question: string;
  probe: string;
  duration_minutes: number;
  signal: string;
}

// Backend canonical: rounds (id, requisition_id, round_number, name, category, duration_minutes,
//   description, skills text[], guidelines jsonb, deleted_at).
// v2 additions: for_candidate_id (custom rounds), removed_from_plan_at (soft-delete from plan).
// is_custom is a derived convenience flag = (for_candidate_id IS NOT NULL).
// feedback_questions is denormalized for read responses (separate table).
export interface Round {
  id: string;
  requisition_id: string;
  round_number: number;
  name: string;
  category: RoundCategory;
  duration_minutes: number;
  description?: string;
  skills: string[];
  guidelines: Guideline[];
  feedback_questions: FeedbackQuestion[];
  is_custom?: boolean;
  for_candidate_id?: string | null;
  removed_from_plan_at?: string | null;
  // UI-only screening agent fields; not persisted in v2. See ScreeningAgentQuestion.
  screening_agent_enabled?: boolean;
  screening_agent_voice?: string;
  screening_agent_questions?: ScreeningAgentQuestion[];
  // Screening eligibility from the plan-read API (`ai_screenable` /
  // `ai_screenable_reason`). Drives the dashboard "OpenRecruiting can take this round"
  // nudge. Mapped to camelCase at the requisitions service boundary so the rest
  // of the dashboard surface stays consistent with the intake `@/types` Round.
  aiScreenable?: boolean;
  aiScreenableReason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourcingStrategyRecord {
  id: string;
  version: number;
  owner_name: string;
  icp: string;
  target_companies: string;
  exclude: string;
  outreach_voice: string;
  sequence: string;
  user_preferences: string | null;
  candidate_count: number;
  total_profiles_label: string;
  created_at: string;
}

// Backend canonical: requisitions (id, organization_id, created_by, role_title, role_location,
//   experience_min_years, experience_max_years, status, intake_notes, job_description,
//   must_have_skills text[], good_to_have_skills text[], deleted_at).
// created_by_name is a derived display field joined from profiles for convenience.
// department is not a DB column; deferred until a migration adds it.
export interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string;
  department: string;
  created_by: string;
  created_by_name: string;
  experience_min_years: number;
  experience_max_years: number | null;
  status: RequisitionStatus;
  intake_notes: string;
  job_description: string;
  must_have_skills: string[];
  good_to_have_skills: string[];
  rounds: Round[];
  sourcing_strategies?: SourcingStrategyRecord[];
  created_at: string;
  updated_at: string;
  /** Provenance: 'openrecruiting' (default) or 'ats_sync' (imported via Knit). */
  source?: 'openrecruiting' | 'ats_sync';
  /** ATS the requisition was imported from (e.g. 'workable'), when ats_sync. */
  ats_provider?: string | null;
}

export type RoundTemplateKey = 'staff_pm_4' | 'senior_eng_5' | 'design_eng_4' | 'leader_6';

export interface RequisitionCreateInput {
  role_title: string;
  role_location: string;
  department: string;
  created_by: string;
  created_by_name: string;
  experience_min_years?: number;
  experience_max_years?: number | null;
  job_description?: string;
  must_have_skills?: string[];
  good_to_have_skills?: string[];
  round_template?: RoundTemplateKey;
}

export interface RequisitionUpdateInput {
  role_title?: string;
  role_location?: string;
  department?: string;
  created_by?: string;
  created_by_name?: string;
  experience_min_years?: number;
  experience_max_years?: number | null;
  intake_notes?: string;
  job_description?: string;
  must_have_skills?: string[];
  good_to_have_skills?: string[];
}

export interface RoundCreateInput {
  name: string;
  category: RoundCategory;
  duration_minutes: number;
  description?: string;
  skills?: string[];
  guidelines?: Guideline[];
  feedback_questions?: Array<{ heading: string; description: string }>;
  position?: number;
}

export interface CustomRoundCreateInput {
  name: string;
  category: RoundCategory;
  duration_minutes: number;
  description?: string;
  skills?: string[];
  guidelines?: Guideline[];
  feedback_questions?: Array<{ heading: string; description: string }>;
}

export interface RoundUpdateInput {
  name?: string;
  category?: RoundCategory;
  duration_minutes?: number;
  description?: string;
  skills?: string[];
  guidelines?: Guideline[];
}

export interface QuestionCreateInput {
  heading: string;
  description: string;
}

export interface QuestionUpdateInput {
  heading?: string;
  description?: string;
  question_number?: number;
}
