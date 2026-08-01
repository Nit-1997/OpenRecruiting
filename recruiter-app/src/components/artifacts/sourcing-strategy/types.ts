export type SourcingStrategyPhase =
  | 'drafting'
  | 'scanning'
  | 'ranking'
  | 'awaiting_selection'
  | 'added';

export type SourcingStrategyTab = 'strategy' | 'candidates';

export interface SourcingChannel {
  id: string;
  name: string;
  statValue: number;
  statLabel: string;
  note: string;
  totalTarget: number;
  scanned: number;
  status: 'pending' | 'scanning' | 'done';
}

export type TrailStepStatus = 'pending' | 'running' | 'done';

export interface SourcingTrailStep {
  id: string;
  label: string;
  body: string;
  status: TrailStepStatus;
  detail?: string;
}

export interface SourcingStrategyCandidate {
  id: string;
  initials: string;
  color: string;
  name: string;
  title: string;
  company: string;
  location: string;
  yearsLabel: string;
  experienceYears: number;
  industry: string;
  sourceChannel: string;
  sourceLabel: string;
  highlights: string[];
  tags: string[];
  score: number;
  email: string;
  rank: number;
}

export interface TargetCompanyTier {
  tier: 'primary' | 'secondary' | 'tertiary';
  label: string;
  note: string;
  companies: string[];
}

export interface SourcingStrategyArtifactData {
  strategyId: string;
  version: number;
  roleId: string | null;
  roleTitle: string | null;
  ownerName: string;
  createdAtLabel: string;
  icp: string;
  /**
   * Role-calibration fields rendered as the ICP brief. `location`,
   * `seniority`, `experienceRequirements`, `mustHaves`, `niceToHaves`,
   * `targetCompanyTiers`, `redFlags`, and `calibrationNote` replace the
   * old "Outreach voice" + "Sequence" cards. `targetCompanies`, `exclude`,
   * `outreachVoice`, and `sequence` are retained for the persistence
   * payload in `saveSourcingStrategy` but are no longer rendered in the
   * artifact surface.
   */
  location: string;
  seniority: string;
  experienceRequirements: string[];
  mustHaves: string[];
  niceToHaves: string[];
  targetCompanyTiers: TargetCompanyTier[];
  redFlags: string[];
  calibrationNote: string;
  targetCompanies: string;
  exclude: string;
  outreachVoice: string;
  sequence: string;
  userPreferences: string | null;
  trailSteps: SourcingTrailStep[];
  trailVisible: boolean;
  channels: SourcingChannel[];
  candidates: SourcingStrategyCandidate[];
  selectedCandidateIds: string[];
  phase: SourcingStrategyPhase;
  activeTab: SourcingStrategyTab;
  addedCount: number;
  totalProfilesLabel: string;
  savedToRole: boolean;
  shareUrl: string | null;
}
