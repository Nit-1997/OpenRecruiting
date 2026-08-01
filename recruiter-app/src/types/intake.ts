// 1:1 mirror of backend/app/api/v2/schemas/intake.py (verified
// against IntakeFormData, AnswerState, ProcessStage, IntakeSessionResponse,
// SessionListItem). Update both files together when the contract changes.

import type { PersonaSnapshot, ScreeningQuestion } from '@/services/screening';

export type IntakeSessionStatus =
  | 'created'
  | 'prefilling'
  | 'ready'
  | 'active'
  | 'submitted'
  | 'published'
  | 'abandoned';

export type IntakeModality = 'voice' | 'text';

export type AnswerStatus = 'untouched' | 'needs_probe' | 'discussed' | 'validated' | 'skipped';

export type Confidence = 'none' | 'low' | 'medium' | 'high';

export type ProcessStageStatus = 'pending' | 'running' | 'completed' | 'failed';

export type ProcessStatus = 'idle' | 'running' | 'failed';

// MUST stay in sync with intake-core/intake_core/questions.py INTAKE_QUESTIONS ids.
export type QuestionId =
  | 'q1_role_overview'
  | 'q2_rounds'
  | 'q3_focus_areas'
  | 'q4_must_haves'
  | 'q5_nice_to_haves'
  | 'q6_cultural_fit'
  | 'q7_team_structure'
  | 'q8_red_flags'
  | 'q9_anything_else';

export interface IntakeFormData {
  role_name: string;
  experience_min: number;
  // null = open-ended ("X+ years"). Mirrors the nullable requisitions column.
  // NEVER send 0 for a blank max — it trips the DB's max>=min CHECK.
  experience_max: number | null;
  location: string;
  jd_text: string | null;
}

export interface AnswerState {
  status: AnswerStatus;
  text: string | null;
  prefilled_text: string | null;
  extraction_confidence: Confidence;
  sources: string[];
  turns_addressed: number[];
  // Set by B2.1 (Phase 2 PATCH /answers); optional here so the type
  // round-trips both shapes.
  manual_edit?: boolean;
  edited_at?: string;
  edited_by?: string;
}

export type CurrentAnswers = Partial<Record<QuestionId, AnswerState>>;

export interface QuestionSnapshot {
  id: QuestionId;
  order: number;
  topic: string;
  default_text: string;
}

// Phase 1 does NOT render conversation turns. Type included so the session
// row shape matches the backend; downstream phases will populate it.
export interface Turn {
  idx: number;
  role: 'user' | 'assistant';
  content: string;
  modality: IntakeModality;
  timestamp: string;
  duration_ms?: number;
  stt_confidence?: number;
  audio_duration_ms?: number;
  tool_calls?: Array<{
    name: 'update_answer' | 'mark_status';
    args: Record<string, unknown>;
  }>;
}

export interface ProcessStage {
  name:
    | 'check_context'
    | 'parse_jd'
    | 'query_cortex'
    | 'synthesize'
    | 'scorecard_rounds'
    | 'scorecard_details';
  status: ProcessStageStatus;
  output: Record<string, unknown> | null;
  error: string | null;
  updated_at: string | null;
}

export type RoundCategory =
  | 'screening'
  | 'coding'
  | 'design'
  | 'behavioral'
  | 'domain'
  | 'culture'
  | 'panel'
  | 'assessment';

export interface Guideline {
  title: string;
  description: string;
}

export interface FeedbackQuestion {
  id: string;
  question_number: number;
  heading: string;
  description: string | null;
}

// Per-round screening config carried in the plan artifact pre-publish. Stored
// in camelCase (reuses the screening service types + components); mapped to the
// snake_case wire shape only at publish (see `roundScreeningToWire`). Backend
// materializes it at publish — see intake_publish_service._materialize_screening.
export interface RoundScreening {
  enabled: boolean;
  voice: string;
  followUpStyle: string;
  validityDays: number;
  questions: ScreeningQuestion[];
  // The derived persona snapshot (dimensions + composed runtime text), stored
  // verbatim from `derivePersonaDraft`. Absent until the recruiter derives one.
  personaSnapshot?: PersonaSnapshot;
}

export interface InterviewPlanRound {
  id: string;
  round_number: number;
  name: string;
  category: RoundCategory;
  duration_minutes: number;
  description: string;
  skills: string[];
  guidelines: Guideline[];
  feedback_questions: FeedbackQuestion[];
  // Optional pre-publish screening config (the editor sets this; publish
  // materializes it). Absent on rounds with no screening configured.
  screening?: RoundScreening;
}

export interface InterviewPlan {
  rounds: InterviewPlanRound[];
}

export interface IntakeSession {
  id: string;
  requisition_id: string;
  user_id: string;
  organization_id: string;
  status: IntakeSessionStatus;
  active_modality: IntakeModality | null;
  entry_point: string | null;
  form_data: IntakeFormData;
  questions_version: string;
  questions_snapshot: QuestionSnapshot[];
  prefilled_answers: CurrentAnswers | null;
  current_answers: CurrentAnswers | null;
  turns: Turn[];
  process_stages: ProcessStage[];
  process_status: ProcessStatus;
  process_error: string | null;
  interview_plan: InterviewPlan | null;
  created_at: string;
  updated_at: string;
}

export interface SessionListItem {
  session_id: string;
  requisition_id: string;
  title: string;
  display_status: 'incomplete' | 'submitted' | 'completed';
  detail_status: IntakeSessionStatus;
  last_activity_at: string;
  active_modality: IntakeModality | null;
  resume_url: string;
  role_name?: string | null;
  exp_min?: number | null;
  exp_max?: number | null;
  location?: string | null;
  // Hub enrichment — goal coverage for the "Continue pending" list
  covered: number;
  total: number;
  stopped_at?: string | null;
  // Hub enrichment — plan stats for the "Edit existing" list
  rounds_count: number;
  total_minutes: number;
  candidates_count: number;
}

export interface ListSessionsResponse {
  sessions: SessionListItem[];
}

export interface CreateSessionResponse {
  session_id: string;
  requisition_id: string;
}

// All stages enumerated for type-safety; Phase 1 ships only the first four
// (intake_form, prefilling, ready_choose_modality, prefill_failed) — the
// rest are defined so flow.ts deriveStage compiles cleanly and downstream
// phases plug in without changing this file.
export type IntakeStage =
  | 'lobby'
  | 'intake_form'
  | 'prefilling'
  | 'ready_choose_modality'
  | 'prefill_failed'
  | 'voice_active'
  | 'voice_reconnect'
  | 'text_active'
  | 'wrapping'
  | 'plan_generating'
  | 'plan_editing'
  | 'scorecard_failed'
  | 'published';

const _STAGES: ReadonlySet<IntakeStage> = new Set<IntakeStage>([
  'lobby',
  'intake_form',
  'prefilling',
  'ready_choose_modality',
  'prefill_failed',
  'voice_active',
  'voice_reconnect',
  'text_active',
  'wrapping',
  'plan_generating',
  'plan_editing',
  'scorecard_failed',
  'published',
]);

export function isIntakeStage(v: unknown): v is IntakeStage {
  return typeof v === 'string' && _STAGES.has(v as IntakeStage);
}

export function isProcessStage(v: unknown): v is ProcessStage {
  if (v === null || typeof v !== 'object') return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.name === 'string' && typeof r.status === 'string' && 'output' in r && 'error' in r
  );
}

export function isSessionListItem(v: unknown): v is SessionListItem {
  if (v === null || typeof v !== 'object') return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.session_id === 'string' &&
    typeof r.requisition_id === 'string' &&
    typeof r.title === 'string' &&
    typeof r.display_status === 'string' &&
    typeof r.resume_url === 'string'
  );
}

export type TextStreamEvent =
  | { type: 'text'; chunk: string }
  | { type: 'tool'; name: string; args: Record<string, unknown> }
  | {
      type: 'done';
      text: string;
      stop_reason: string | null;
      user_turn_idx: number;
      assistant_turn_idx: number;
    }
  | { type: 'error'; message: string; code?: string };

// ─── Phase 4: Handoff + Process Till Now ─────────────────────────────────────

export interface ModalityConflictBody {
  detail: string;
  held: 'voice' | 'text';
  requested: 'voice' | 'text';
}

export interface SwitchToTextResponse {
  active_modality: 'text';
  drained: {
    drained: boolean;
    already_idle?: boolean;
    duration_ms?: number;
    forced_cancel?: boolean;
  };
  session: IntakeSession | null;
}

export interface SwitchToVoiceResponse {
  active_modality: 'voice';
  next_step: 'voice_start';
}

export type SwitchModalityResponse = SwitchToTextResponse | SwitchToVoiceResponse;

// VoiceDrainFailedError + ReprocessAlreadyRunningError as runtime classes
// (these need to be exported from types so the api.ts consumer can throw them
// and tests can `instanceof` them).
export class VoiceDrainFailedError extends Error {
  readonly innerError: string | undefined;
  constructor(detail: string, innerError?: string) {
    super(detail);
    this.name = 'VoiceDrainFailedError';
    this.innerError = innerError;
  }
}

export interface ReprocessAcceptedResponse {
  session_id: string;
  process_run_id: string;
}

export class ReprocessAlreadyRunningError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = 'ReprocessAlreadyRunningError';
  }
}

export interface HeartbeatResponse {
  ok: true;
  last_heartbeat_at: string;
}
