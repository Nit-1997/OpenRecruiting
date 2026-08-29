import { REQS } from './roles';

export type PipelineStageKey = 'sourced' | 'screen' | 'hm' | 'panel' | 'offer';

export interface PipelineCounts {
  sourced: number;
  screen: number;
  hm: number;
  panel: number;
  offer: number;
}

export interface UpcomingRound {
  id: string;
  roundId: string;
  candidate: string;
  candidateAvatar: string;
  candidateColor: string;
  interviewer: string;
  when: string;
  mode: 'video' | 'phone' | 'in-person';
  status: 'confirmed' | 'pending';
}

export type StalledSeverity = 'low' | 'medium' | 'high';

export interface StalledSignal {
  id: string;
  label: string;
  severity: StalledSeverity;
}

export interface RecentActivity {
  id: string;
  kind: 'feedback' | 'interview' | 'candidate' | 'role';
  label: string;
  whenAgo: string;
}

export interface RoleOwner {
  name: string;
  avatar: string;
  color: string;
  role: string;
}

export interface RoleOverview {
  roleId: string;
  roleTitle: string;
  roleLocation: string;
  pipelineByStage: PipelineCounts;
  upcomingRounds: UpcomingRound[];
  stalledSignals: StalledSignal[];
  recentActivity: RecentActivity[];
  owner: RoleOwner;
  hiringManager: RoleOwner;
  lastUpdated: string;
  candidatesTotal: number;
}

function owner(name: string, avatar: string, color: string, role: string): RoleOwner {
  return { name, avatar, color, role };
}

function defaultRecent(): RecentActivity[] {
  return [
    {
      id: 'a1',
      kind: 'feedback',
      label: 'Sana Reyes submitted panel feedback',
      whenAgo: '14m ago',
    },
    {
      id: 'a2',
      kind: 'interview',
      label: 'Marcus Chen · HM scheduled Tue 2:00 PM',
      whenAgo: '1h ago',
    },
    {
      id: 'a3',
      kind: 'candidate',
      label: 'Sloane Natarajan advanced to panel',
      whenAgo: '3h ago',
    },
    {
      id: 'a4',
      kind: 'role',
      label: 'Compensation band updated to $280k–$360k',
      whenAgo: '1d ago',
    },
  ];
}

function makePipelineByOwner(seed: number): PipelineCounts {
  const base = Math.max(4, seed % 11);
  return {
    sourced: base + 6,
    screen: Math.max(2, base),
    hm: Math.max(1, Math.floor(base / 2)),
    panel: Math.max(1, Math.floor(base / 3)),
    offer: seed % 2,
  };
}

export const ROLE_OVERVIEWS: Record<string, RoleOverview> = {
  'pm-sfo': {
    roleId: 'pm-sfo',
    roleTitle: 'Staff PM · Sunnyvale',
    roleLocation: 'Sunnyvale · Product',
    pipelineByStage: { sourced: 16, screen: 7, hm: 4, panel: 3, offer: 1 },
    upcomingRounds: [
      {
        id: 'u1',
        roundId: 'ps',
        candidate: 'Sloane Natarajan',
        candidateAvatar: 'SN',
        candidateColor: '#EADFD4',
        interviewer: 'Sana Reyes',
        when: 'Today · 2:30 PM',
        mode: 'video',
        status: 'confirmed',
      },
      {
        id: 'u2',
        roundId: 'hm',
        candidate: 'Marcus Chen',
        candidateAvatar: 'MC',
        candidateColor: '#D8EFE3',
        interviewer: 'David Woo',
        when: 'Tue · 2:00 PM',
        mode: 'video',
        status: 'pending',
      },
      {
        id: 'u3',
        roundId: 'cv',
        candidate: 'David Kim',
        candidateAvatar: 'DK',
        candidateColor: '#F6E4DA',
        interviewer: 'Anand Patel',
        when: 'Wed · 10:00 AM',
        mode: 'video',
        status: 'confirmed',
      },
    ],
    stalledSignals: [
      { id: 's1', label: 'Panel unscheduled 5 days', severity: 'high' },
      { id: 's2', label: '2 scorecards overdue', severity: 'medium' },
      { id: 's3', label: '3 sourced leads not contacted', severity: 'low' },
    ],
    recentActivity: defaultRecent(),
    owner: owner('Jess Lin', 'JL', '#EADFD4', 'Recruiter'),
    hiringManager: owner('David Woo', 'DW', '#D8EFE3', 'Hiring manager'),
    lastUpdated: '2026-04-17T22:45:00Z',
    candidatesTotal: 16,
  },
  'ios-sea': {
    roleId: 'ios-sea',
    roleTitle: 'Senior iOS Eng',
    roleLocation: 'Remote · Engineering',
    pipelineByStage: { sourced: 11, screen: 5, hm: 2, panel: 2, offer: 0 },
    upcomingRounds: [
      {
        id: 'u1',
        roundId: 'hm',
        candidate: 'Mei Lin',
        candidateAvatar: 'ML',
        candidateColor: '#DDE8F6',
        interviewer: 'Anand Patel',
        when: 'Mon · 1:30 PM',
        mode: 'video',
        status: 'confirmed',
      },
      {
        id: 'u2',
        roundId: 'ps',
        candidate: 'Sofia Ramirez',
        candidateAvatar: 'SR',
        candidateColor: '#DDE8F6',
        interviewer: 'Sana Reyes',
        when: 'Thu · 11:00 AM',
        mode: 'video',
        status: 'pending',
      },
    ],
    stalledSignals: [
      { id: 's1', label: '1 candidate waiting 4 days', severity: 'medium' },
      { id: 's2', label: 'Take-home rubric pending', severity: 'low' },
    ],
    recentActivity: defaultRecent(),
    owner: owner('Jess Lin', 'JL', '#EADFD4', 'Recruiter'),
    hiringManager: owner('Anand Patel', 'AP', '#DDE8F6', 'Hiring manager'),
    lastUpdated: '2026-04-17T16:12:00Z',
    candidatesTotal: 11,
  },
  'des-ny': {
    roleId: 'des-ny',
    roleTitle: 'Design Engineer',
    roleLocation: 'New York · Design',
    pipelineByStage: { sourced: 8, screen: 3, hm: 1, panel: 0, offer: 0 },
    upcomingRounds: [
      {
        id: 'u1',
        roundId: 'hm',
        candidate: 'Noor Haidari',
        candidateAvatar: 'NH',
        candidateColor: '#E9DFF5',
        interviewer: 'Sloane Shah',
        when: 'Fri · 10:00 AM',
        mode: 'video',
        status: 'pending',
      },
    ],
    stalledSignals: [
      { id: 's1', label: 'Requisition draft 3 days old', severity: 'medium' },
      { id: 's2', label: 'No interviewers assigned to round 2', severity: 'high' },
    ],
    recentActivity: defaultRecent(),
    owner: owner('Sloane Shah', 'SS', '#E9DFF5', 'Recruiter'),
    hiringManager: owner('Sloane Shah', 'SS', '#E9DFF5', 'Hiring manager'),
    lastUpdated: '2026-04-16T08:00:00Z',
    candidatesTotal: 8,
  },
};

export function getRoleOverview(roleId: string): RoleOverview {
  const existing = ROLE_OVERVIEWS[roleId];
  if (existing) return existing;
  const role = REQS.find((r) => r.id === roleId);
  const seed = roleId.length;
  return {
    roleId,
    roleTitle: role?.title ?? 'Role',
    roleLocation: role?.loc ?? '—',
    pipelineByStage: makePipelineByOwner(seed),
    upcomingRounds: [
      {
        id: 'u1',
        roundId: 'rs',
        candidate: 'Jamie Wu',
        candidateAvatar: 'JW',
        candidateColor: '#D8EFE3',
        interviewer: 'Jess Lin',
        when: 'Mon · 11:00 AM',
        mode: 'phone',
        status: 'confirmed',
      },
    ],
    stalledSignals: [{ id: 's1', label: 'Awaiting first interview', severity: 'low' }],
    recentActivity: defaultRecent(),
    owner: owner(role?.owner ?? 'Taylor', (role?.owner ?? 'N')[0] ?? 'N', '#EADFD4', 'Recruiter'),
    hiringManager: owner('David Woo', 'DW', '#D8EFE3', 'Hiring manager'),
    lastUpdated: new Date().toISOString(),
    candidatesTotal: makePipelineByOwner(seed).sourced,
  };
}

export function humanizeStageKey(k: PipelineStageKey): string {
  switch (k) {
    case 'sourced':
      return 'Sourced';
    case 'screen':
      return 'Recruiter screen';
    case 'hm':
      return 'Hiring manager';
    case 'panel':
      return 'Panel';
    case 'offer':
      return 'Offer';
  }
}
