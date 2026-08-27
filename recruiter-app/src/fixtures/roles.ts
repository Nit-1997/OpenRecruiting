export type RoleStatus = 'live' | 'draft' | 'paused';

export type RoleTabStatus = 'open' | 'pending' | 'closed';

export interface RoleFixture {
  id: string;
  title: string;
  loc: string;
  pipeline: string;
  status: RoleStatus;
  dept: string;
  owner: string;
  created_at: string;
  ready_to_debrief: boolean;
  must_have: string[];
  nice_to_have: string[];
}

const OPEN_STATUSES = new Set<RoleStatus>(['live']);
const PENDING_STATUSES = new Set<RoleStatus>(['draft']);
const CLOSED_STATUSES = new Set<RoleStatus>(['paused']);

export function roleTabStatus(status: RoleStatus): RoleTabStatus {
  if (PENDING_STATUSES.has(status)) return 'pending';
  if (CLOSED_STATUSES.has(status)) return 'closed';
  if (OPEN_STATUSES.has(status)) return 'open';
  return 'open';
}

export const REQS: RoleFixture[] = [
  {
    id: 'pm-sfo',
    title: 'Staff PM · Sunnyvale',
    loc: 'Sunnyvale',
    pipeline: '4 candidates awaiting decision',
    status: 'live',
    dept: 'Product',
    owner: 'Taylor',
    created_at: '2026-03-22T14:30:00Z',
    ready_to_debrief: true,
    must_have: ['Product strategy', 'Stakeholder mgmt', 'Metrics'],
    nice_to_have: ['Growth experience'],
  },
  {
    id: 'ios-sea',
    title: 'Senior iOS Eng',
    loc: 'Remote',
    pipeline: '2 debriefs drafted',
    status: 'live',
    dept: 'Engineering',
    owner: 'Taylor',
    created_at: '2026-03-29T10:15:00Z',
    ready_to_debrief: true,
    must_have: ['Swift', 'UIKit / SwiftUI', 'Testing'],
    nice_to_have: ['Combine', 'Metal'],
  },
  {
    id: 'des-ny',
    title: 'Design Engineer',
    loc: 'New York',
    pipeline: '1 panel to score',
    status: 'draft',
    dept: 'Design',
    owner: 'Sloane',
    created_at: '2026-04-13T09:00:00Z',
    ready_to_debrief: false,
    must_have: ['React', 'Motion', 'Tokens'],
    nice_to_have: ['3D / WebGL'],
  },
  {
    id: 'gr-mkt',
    title: 'Growth Marketer',
    loc: 'SF',
    pipeline: '3 new resumes to review',
    status: 'live',
    dept: 'Marketing',
    owner: 'Taylor',
    created_at: '2026-04-08T08:45:00Z',
    ready_to_debrief: false,
    must_have: ['SEO / SEM', 'Lifecycle', 'Attribution'],
    nice_to_have: ['Podcast', 'Creator'],
  },
  {
    id: 'be-atx',
    title: 'Backend Eng',
    loc: 'Austin',
    pipeline: 'Panel at 2:15 PM',
    status: 'live',
    dept: 'Engineering',
    owner: 'Alex',
    created_at: '2026-02-14T11:20:00Z',
    ready_to_debrief: true,
    must_have: ['Go', 'Postgres', 'Kafka'],
    nice_to_have: ['Rust'],
  },
  {
    id: 'ds-rem',
    title: 'Data Scientist',
    loc: 'Remote',
    pipeline: 'Sourcing paused',
    status: 'paused',
    dept: 'Data',
    owner: 'Taylor',
    created_at: '2026-01-31T16:00:00Z',
    ready_to_debrief: false,
    must_have: ['Python', 'SQL', 'Causal inference'],
    nice_to_have: ['LLM eval'],
  },
  {
    id: 'pmm-ny',
    title: 'Product Marketing Lead',
    loc: 'New York',
    pipeline: '5 candidates in loop',
    status: 'live',
    dept: 'Marketing',
    owner: 'Sloane',
    created_at: '2026-03-05T13:10:00Z',
    ready_to_debrief: true,
    must_have: ['Positioning', 'Launch', 'Analyst relations'],
    nice_to_have: ['B2B SaaS'],
  },
  {
    id: 'fe-rem',
    title: 'Staff Frontend Eng',
    loc: 'Remote',
    pipeline: 'Interviewing · round 3',
    status: 'live',
    dept: 'Engineering',
    owner: 'Alex',
    created_at: '2026-02-28T09:30:00Z',
    ready_to_debrief: true,
    must_have: ['React', 'TS', 'Perf'],
    nice_to_have: ['Canvas / WebGL'],
  },
  {
    id: 'sre-atl',
    title: 'SRE / Platform',
    loc: 'Atlanta',
    pipeline: '6 candidates sourced',
    status: 'live',
    dept: 'Engineering',
    owner: 'Alex',
    created_at: '2026-03-17T07:05:00Z',
    ready_to_debrief: false,
    must_have: ['K8s', 'Terraform', 'Observability'],
    nice_to_have: ['Rust'],
  },
  {
    id: 'rec-sfo',
    title: 'Senior Recruiter',
    loc: 'SF',
    pipeline: 'Kickoff pending',
    status: 'draft',
    dept: 'People',
    owner: 'Taylor',
    created_at: '2026-04-16T10:25:00Z',
    ready_to_debrief: false,
    must_have: ['Tech sourcing', 'Closing', 'Partner mgmt'],
    nice_to_have: ['Exec search'],
  },
  {
    id: 'des-ldn',
    title: 'Product Designer',
    loc: 'London',
    pipeline: '2 debriefs drafted',
    status: 'live',
    dept: 'Design',
    owner: 'Sloane',
    created_at: '2026-03-10T11:40:00Z',
    ready_to_debrief: true,
    must_have: ['Interaction', 'Systems', 'Prototyping'],
    nice_to_have: ['Motion'],
  },
  {
    id: 'ae-nyc',
    title: 'Enterprise AE',
    loc: 'New York',
    pipeline: '7 candidates screened',
    status: 'live',
    dept: 'Sales',
    owner: 'Jordan',
    created_at: '2026-03-25T15:55:00Z',
    ready_to_debrief: false,
    must_have: ['$1M+ quota', 'Multi-threaded', 'MEDDPICC'],
    nice_to_have: ['ATS vertical'],
  },
  {
    id: 'sc-sea',
    title: 'Solutions Consultant',
    loc: 'Seattle',
    pipeline: 'Panel at 4:00 PM',
    status: 'live',
    dept: 'Sales',
    owner: 'Jordan',
    created_at: '2026-03-01T13:35:00Z',
    ready_to_debrief: true,
    must_have: ['Pre-sales', 'Demo craft', 'Integrations'],
    nice_to_have: ['Greenhouse / Lever experience'],
  },
  {
    id: 'fin-rem',
    title: 'Senior FP&A',
    loc: 'Remote',
    pipeline: 'No activity in 6 days',
    status: 'paused',
    dept: 'Finance',
    owner: 'Taylor',
    created_at: '2026-02-02T09:00:00Z',
    ready_to_debrief: false,
    must_have: ['Modeling', 'SaaS metrics'],
    nice_to_have: ['IPO prep'],
  },
  {
    id: 'cs-ny',
    title: 'Customer Success Lead',
    loc: 'New York',
    pipeline: '4 candidates awaiting',
    status: 'live',
    dept: 'CS',
    owner: 'Sloane',
    created_at: '2026-03-19T14:00:00Z',
    ready_to_debrief: false,
    must_have: ['Renewals', 'Expansion', 'Playbooks'],
    nice_to_have: ['ATS vertical'],
  },
];

export function findRoleById(id: string): RoleFixture | null {
  return REQS.find((r) => r.id === id) ?? null;
}
