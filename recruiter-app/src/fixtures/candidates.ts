export type CandidateStatus = 'ready' | 'waiting' | 'early';

/** Backend eligibility tier (spec §7). Carried alongside the derived
 *  `status` so the picker can gate selection on the canonical tier without
 *  reverse-mapping the display vocabulary. */
export type CandidateEligibility = 'ready' | 'awaiting_signal' | 'early_stage';

/** Per-candidate feedback signal (spec §7) — drives the "N scorecards ·
 *  M evidence-backed" line and the ready/not-ready reason. */
export interface CandidateSignal {
  feedback_count: number;
  evidence_backed_count: number;
}

export interface CandidateFixture {
  id: string;
  name: string;
  role: string;
  stage: string;
  rounds: number;
  scoresIn: number;
  avatar: string;
  color: string;
  flag: string;
  status: CandidateStatus;
  /** Canonical backend eligibility tier. Optional so mock-path fixtures (which
   *  predate this field) still type-check; the picker treats an absent tier as
   *  selectable when `status === 'ready'`. */
  eligibility?: CandidateEligibility;
  /** Feedback signal counts, when sourced from the backend. */
  signal?: CandidateSignal;
  /** Completed rounds carrying a rating (the debrief averages over these). The
   *  picker requires co-selected candidates to share this count. Optional so
   *  mock-path fixtures still type-check; the picker falls back to `scoresIn`. */
  ratedRounds?: number;
}

const PM_SFO_CANDIDATES: CandidateFixture[] = [
  {
    id: 'c1',
    name: 'Sloane Natarajan',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'PN',
    color: '#EADFD4',
    flag: 'Strong · 3.6/4',
    status: 'ready',
  },
  {
    id: 'c2',
    name: 'Marcus Chen',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'MC',
    color: '#D8EFE3',
    flag: 'Strong · 3.4/4',
    status: 'ready',
  },
  {
    id: 'c3',
    name: 'Rivka Sandoval',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'RS',
    color: '#E9DFF5',
    flag: 'Mixed · 2.9/4',
    status: 'ready',
  },
  {
    id: 'c4',
    name: 'David Kim',
    role: 'Staff PM',
    stage: 'HM + panel done',
    rounds: 4,
    scoresIn: 3,
    avatar: 'DK',
    color: '#F6E4DA',
    flag: 'Waiting on CV round',
    status: 'waiting',
  },
  {
    id: 'c5',
    name: 'Mei Lin',
    role: 'Staff PM',
    stage: 'HM + panel done',
    rounds: 4,
    scoresIn: 3,
    avatar: 'ML',
    color: '#DDE8F6',
    flag: 'Waiting on CV round',
    status: 'waiting',
  },
  {
    id: 'c6',
    name: 'Sarah Chen',
    role: 'Staff PM',
    stage: 'Recruiter screen',
    rounds: 4,
    scoresIn: 1,
    avatar: 'SC',
    color: '#F4E9D8',
    flag: 'Early — more signal needed',
    status: 'early',
  },
  {
    id: 'c7',
    name: 'Eleanor Whitfield',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'EW',
    color: '#EADFD4',
    flag: 'Strong · 3.5/4',
    status: 'ready',
  },
  {
    id: 'c8',
    name: 'Andre Okonkwo',
    role: 'Staff PM',
    stage: 'HM done',
    rounds: 4,
    scoresIn: 2,
    avatar: 'AO',
    color: '#D8EFE3',
    flag: 'Pending panel · Thu',
    status: 'waiting',
  },
  {
    id: 'c9',
    name: 'Hina Agarwal',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'HA',
    color: '#E9DFF5',
    flag: 'Mixed · needs alignment',
    status: 'ready',
  },
  {
    id: 'c10',
    name: 'Jon Park',
    role: 'Staff PM',
    stage: 'Recruiter screen',
    rounds: 4,
    scoresIn: 1,
    avatar: 'JP',
    color: '#F4E9D8',
    flag: 'Passed screen — promising',
    status: 'early',
  },
  {
    id: 'c11',
    name: 'Sofia Ramirez',
    role: 'Staff PM',
    stage: 'HM + panel done',
    rounds: 4,
    scoresIn: 3,
    avatar: 'SR',
    color: '#DDE8F6',
    flag: 'Waiting on CV round',
    status: 'waiting',
  },
  {
    id: 'c12',
    name: 'Tomás Vega',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'TV',
    color: '#F6E4DA',
    flag: 'Strong · 3.3/4',
    status: 'ready',
  },
  {
    id: 'c13',
    name: 'Yuki Tanaka',
    role: 'Staff PM',
    stage: 'HM scheduled',
    rounds: 4,
    scoresIn: 1,
    avatar: 'YT',
    color: '#EADFD4',
    flag: 'Early — screen passed',
    status: 'early',
  },
  {
    id: 'c14',
    name: 'Nadia Hassan',
    role: 'Staff PM',
    stage: 'Panel complete',
    rounds: 4,
    scoresIn: 4,
    avatar: 'NH',
    color: '#D8EFE3',
    flag: 'Mixed · 2.8/4',
    status: 'ready',
  },
  {
    id: 'c15',
    name: 'Oliver Mensah',
    role: 'Staff PM',
    stage: 'Take-home in review',
    rounds: 4,
    scoresIn: 2,
    avatar: 'OM',
    color: '#E9DFF5',
    flag: 'Waiting on rubric',
    status: 'waiting',
  },
  {
    id: 'c16',
    name: 'Priscilla Dubois',
    role: 'Staff PM',
    stage: 'Sourced',
    rounds: 4,
    scoresIn: 0,
    avatar: 'PD',
    color: '#F4E9D8',
    flag: 'Outreach sent',
    status: 'early',
  },
  {
    id: 'c17',
    name: 'Amara Valeri',
    role: 'Staff PM',
    stage: 'Recruiter screen',
    rounds: 4,
    scoresIn: 1,
    avatar: 'AV',
    color: '#F4CDB6',
    flag: 'Strong · recruiter screen passed',
    status: 'ready',
  },
];

const DEFAULT_CANDIDATES: CandidateFixture[] = [
  {
    id: 'd1',
    name: 'Noor Haidari',
    role: '—',
    stage: 'Panel complete',
    rounds: 3,
    scoresIn: 3,
    avatar: 'NH',
    color: '#E9DFF5',
    flag: 'Strong · 3.5/4',
    status: 'ready',
  },
  {
    id: 'd2',
    name: 'Jamie Wu',
    role: '—',
    stage: 'Panel complete',
    rounds: 3,
    scoresIn: 3,
    avatar: 'JW',
    color: '#D8EFE3',
    flag: 'Strong · 3.2/4',
    status: 'ready',
  },
  {
    id: 'd3',
    name: 'Kai Ishida',
    role: '—',
    stage: 'HM + panel',
    rounds: 3,
    scoresIn: 2,
    avatar: 'KI',
    color: '#EADFD4',
    flag: 'Mixed',
    status: 'waiting',
  },
];

export const CANDIDATES_BY_REQ: Record<string, CandidateFixture[]> = {
  'pm-sfo': PM_SFO_CANDIDATES,
};

export function getCandidatesForReq(reqId: string): CandidateFixture[] {
  return CANDIDATES_BY_REQ[reqId] ?? DEFAULT_CANDIDATES;
}

export function getCandidatesByIds(reqId: string, ids: string[]): CandidateFixture[] {
  const list = getCandidatesForReq(reqId);
  return list.filter((c) => ids.includes(c.id));
}
