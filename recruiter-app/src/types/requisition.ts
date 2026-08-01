export type RequisitionStatus = 'intake_pending' | 'planned' | 'closed';

export type IntakeProcessingStatus = 'processing' | 'completed' | 'failed';

export type IntakeProcessingStage =
  | 'summarizing'
  | 'building_plan'
  | 'designing_rounds'
  | 'completed';

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
  roundId: string;
  questionNumber: number;
  heading: string;
  description: string | null;
}

export interface IntakeScreeningQuestion {
  id: string;
  order: number;
  dimension: string;
  question: string;
  probe: string;
  durationMinutes: number;
  signal: string;
}

export interface Round {
  id: string;
  requisitionId: string;
  roundNumber: number;
  name: string;
  category: RoundCategory;
  durationMinutes: number;
  description: string;
  skills: string[];
  guidelines: Guideline[];
  feedbackQuestions: FeedbackQuestion[];
  screeningAgentEnabled?: boolean;
  screeningAgentVoice?: string;
  screeningAgentQuestions?: IntakeScreeningQuestion[];
  /**
   * Backend eligibility flag from the plan read API (`ai_screenable`): true
   * when OpenRecruiting can host this round as a screening call. Drives the
   * "OpenRecruiting can take this round" nudge in RoundCard.
   */
  aiScreenable?: boolean;
  /** Human reason behind `aiScreenable` (`ai_screenable_reason`); shown as the nudge tooltip. */
  aiScreenableReason?: string | null;
}

export interface Requisition {
  id: string;
  roleTitle: string;
  roleLocation: string;
  experienceMinYears: number;
  experienceMaxYears: number | null;
  status: RequisitionStatus;
  intakeSummary: string | null;
  intakeProcessingStatus: IntakeProcessingStatus | null;
  intakeProcessingStage: IntakeProcessingStage | null;
  rounds: Round[];
  createdAt: string;
  updatedAt: string;
  /**
   * Id of the parallel requisition in the services layer (mock-db) that
   * backs the /view/roles dashboard. Populated once the intake flow
   * mirrors this draft to the dashboard on publish or save-as-draft.
   */
  dashboardRequisitionId?: string;
}

export type IntakeEvent =
  | { type: 'stage'; stage: IntakeProcessingStage }
  | { type: 'summary.delta'; token: string }
  | { type: 'round.created'; round: Round }
  | {
      type: 'round.details';
      roundId: string;
      guidelines: Guideline[];
      feedbackQuestions: FeedbackQuestion[];
    }
  | { type: 'done' }
  | { type: 'error'; message: string };
