// Backend canonical: requisitions.status CHECK ('draft', 'intake_pending', 'planned', 'closed').
// 'draft' = the intake Hub's pre-submit working copy (never shown in the roles
// rail). ATS imports land directly at 'intake_pending' (migration 127).
export type RequisitionStatus = 'draft' | 'intake_pending' | 'planned' | 'closed';

// Backend canonical: candidates.status CHECK ('active', 'hired', 'rejected', 'withdrawn')
// Display labels like "screening", "interview", "offer" are derived in the UI from
// the candidate's progress through candidate_rounds, not stored on the row.
export type CandidateStatus = 'active' | 'hired' | 'rejected' | 'withdrawn';

// Backend canonical: rounds.category is a free-text VARCHAR(50). Keep a string alias
// instead of an enum so user-defined categories from intake flow round-trip cleanly.
export type RoundCategory = string;

// Common round categories the UI offers as dropdown defaults. The persisted column is
// free-text, so other strings are valid; this set is purely for editor convenience.
export type RoundType =
  | 'screening'
  | 'technical'
  | 'behavioral'
  | 'culture'
  | 'panel'
  | 'final';

// Backend canonical: candidate_rounds.status CHECK ('pending','scheduled','in_progress','completed','cancelled')
export type CandidateRoundStatus =
  | 'pending'
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'cancelled';

// Backend canonical: candidate_rounds.scorecard_status CHECK ('pending','processing','complete')
export type ScorecardStatus = 'pending' | 'processing' | 'complete';

// Backend canonical: candidate_rounds.rating CHECK ('strong_yes','yes','maybe','no','strong_no')
export type RoundRating = 'strong_yes' | 'yes' | 'maybe' | 'no' | 'strong_no';

// Backend canonical: candidate_feedback.evidence_status CHECK ('supported','verified','contradicted','partial','none')
export type EvidenceStatus =
  | 'supported'
  | 'verified'
  | 'contradicted'
  | 'partial'
  | 'none';

// Backend canonical: candidate_feedback.source CHECK ('manual', 'bot')
export type FeedbackSource = 'manual' | 'bot';

export type OrgRole = 'owner' | 'admin' | 'recruiter' | 'viewer';

export type PlanTier = 'starter' | 'growth' | 'scale' | 'enterprise';

export type IntegrationProvider = 'slack' | 'recall' | 'untracked_bot';

export type IntegrationStatus = 'connected' | 'available' | 'error' | 'disabled';

export type ActivityEventType =
  | 'role:created'
  | 'role:status_changed'
  | 'candidate:created'
  | 'candidate:status_changed'
  | 'interview:scheduled'
  | 'interview:rescheduled'
  | 'interview:cancelled'
  | 'feedback:submitted'
  | 'feedback:requested'
  | 'member:invited'
  | 'member:joined'
  | 'billing:plan_changed'
  | 'billing:credits_toppedup'
  | 'integration:connected'
  | 'integration:disconnected';

export type UntrackedStatus = 'available' | 'imported' | 'dismissed';

// Backend canonical: candidates.final_verdict CHECK ('strong_hire','hire','no_hire','strong_no_hire'),
// NULL allowed. UI should treat null as "no verdict yet".
export type FinalVerdict = 'strong_hire' | 'hire' | 'no_hire' | 'strong_no_hire';
