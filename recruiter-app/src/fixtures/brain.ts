export type BrainNodeType = 'role' | 'interviewer' | 'signal';

export interface BrainNode {
  id: string;
  type: BrainNodeType;
  label: string;
  meta: string;
}

export interface BrainLink {
  source: string;
  target: string;
  kind: 'panel' | 'overload' | 'drift' | 'risk';
}

export type BrainStorySeverity = 'warn' | 'info' | 'danger';

export interface BrainStory {
  id: string;
  title: string;
  body: string;
  severity: BrainStorySeverity;
  targetIds: string[];
  elaboration: string;
  evidence: string[];
}

export const BRAIN_NODES: BrainNode[] = [
  {
    id: 'r-pm-sfo',
    type: 'role',
    label: 'Staff PM · SFO',
    meta: '14 in pipeline',
  },
  {
    id: 'r-ds-rem',
    type: 'role',
    label: 'Data Scientist · Remote',
    meta: 'Paused · 3d',
  },
  {
    id: 'r-se-nyc',
    type: 'role',
    label: 'Senior Eng · NYC',
    meta: '11 in pipeline',
  },
  {
    id: 'r-design',
    type: 'role',
    label: 'Design Engineer',
    meta: '7 in pipeline',
  },
  {
    id: 'i-sana',
    type: 'interviewer',
    label: 'Sana Reyes',
    meta: 'Senior PM',
  },
  {
    id: 'i-anand',
    type: 'interviewer',
    label: 'Anand Patel',
    meta: 'Tech lead',
  },
  {
    id: 'i-ben',
    type: 'interviewer',
    label: 'Ben Okafor',
    meta: 'Panel lead',
  },
  {
    id: 'i-mia',
    type: 'interviewer',
    label: 'Mia Chen',
    meta: 'Design lead',
  },
  {
    id: 's-drift',
    type: 'signal',
    label: 'Scoring drift',
    meta: 'Product Sense',
  },
  {
    id: 's-overload',
    type: 'signal',
    label: 'Panel overload',
    meta: 'This week',
  },
  {
    id: 's-pipeline-risk',
    type: 'signal',
    label: 'Pipeline at risk',
    meta: 'Data Scientist',
  },
];

export const BRAIN_LINKS: BrainLink[] = [
  { source: 'i-sana', target: 'r-pm-sfo', kind: 'panel' },
  { source: 'i-anand', target: 'r-pm-sfo', kind: 'panel' },
  { source: 'i-anand', target: 'r-se-nyc', kind: 'panel' },
  { source: 'i-ben', target: 'r-pm-sfo', kind: 'panel' },
  { source: 'i-ben', target: 'r-se-nyc', kind: 'panel' },
  { source: 'i-ben', target: 'r-design', kind: 'panel' },
  { source: 'i-ben', target: 'r-ds-rem', kind: 'panel' },
  { source: 'i-mia', target: 'r-design', kind: 'panel' },
  { source: 's-drift', target: 'r-pm-sfo', kind: 'drift' },
  { source: 's-drift', target: 'i-ben', kind: 'drift' },
  { source: 's-overload', target: 'i-ben', kind: 'overload' },
  { source: 's-overload', target: 'i-anand', kind: 'overload' },
  { source: 's-pipeline-risk', target: 'r-ds-rem', kind: 'risk' },
];

export const BRAIN_STORIES: BrainStory[] = [
  {
    id: 'story-scoring-drift',
    title: 'Scoring drift detected',
    body: 'Ben is scoring Product Sense 1.3 points below the panel on Staff PM candidates.',
    severity: 'warn',
    targetIds: ['s-drift', 'i-ben', 'r-pm-sfo'],
    elaboration:
      'Ben has scored 6 of the last 8 Product Sense rounds. His average is 2.7 versus the panel mean of 4.0. Recalibration suggested before the next Product Sense round on Thursday.',
    evidence: [
      'Sloane N. · Ben 2.5 · panel 3.8',
      'Marcus C. · Ben 2.8 · panel 4.1',
      'Yuki T. · Ben 3.0 · panel 4.0',
    ],
  },
  {
    id: 'story-panel-overload',
    title: 'Panel load imbalance',
    body: 'Ben is staffed on 4 roles this week — 11 panels. Anand is next at 7.',
    severity: 'info',
    targetIds: ['s-overload', 'i-ben', 'i-anand'],
    elaboration:
      'Ben has 11 interview slots Monday through Friday across four requisitions. Industry benchmark is 6. Recommend offloading two Staff PM panels to Sana, who has capacity.',
    evidence: [
      'Ben · 11 slots this week',
      'Anand · 7 slots this week',
      'Sana · 3 slots this week (capacity +4)',
    ],
  },
  {
    id: 'story-pipeline-risk',
    title: 'Pipeline at risk',
    body: 'Data Scientist · Remote has been paused for 3 days — 12 candidates stalling.',
    severity: 'danger',
    targetIds: ['s-pipeline-risk', 'r-ds-rem'],
    elaboration:
      'Data Scientist · Remote requisition has not advanced candidates since April 15. 12 applicants are awaiting review, 3 are past their 7-day SLA. Reactivate or reassign.',
    evidence: [
      '12 candidates awaiting review',
      '3 past the 7-day SLA',
      'Last touchpoint · April 15, 2026',
    ],
  },
  {
    id: 'story-design-velocity',
    title: 'Design Engineer moving fast',
    body: 'Design Engineer pipeline converted 3 candidates to onsite this week — 40% above baseline.',
    severity: 'info',
    targetIds: ['r-design', 'i-mia'],
    elaboration:
      'Mia is running a tight loop on Design Engineer. 3 onsite moves this week versus a 2.1 baseline. Worth capturing the panel playbook for the Staff PM role.',
    evidence: [
      '3 candidates to onsite · week of 4/13',
      'Baseline · 2.1 / week',
      'Loop owner · Mia Chen',
    ],
  },
];

export const BRAIN_TIME_RANGES = [
  { id: 'this-week', label: 'This week' },
  { id: 'last-2-weeks', label: 'Last 2 weeks' },
  { id: 'month', label: 'Month' },
  { id: 'quarter', label: 'Quarter' },
] as const;

export type BrainTimeRangeId = (typeof BRAIN_TIME_RANGES)[number]['id'];

export const BRAIN_DEFAULT_RANGE: BrainTimeRangeId = 'this-week';

export function findBrainStory(id: string): BrainStory | undefined {
  return BRAIN_STORIES.find((s) => s.id === id);
}

export function findBrainNode(id: string): BrainNode | undefined {
  return BRAIN_NODES.find((n) => n.id === id);
}

export function searchBrainNodes(input: string): BrainNode[] {
  const q = input.trim().toLowerCase();
  if (!q) return [];
  return BRAIN_NODES.filter(
    (n) => n.label.toLowerCase().includes(q) || n.meta.toLowerCase().includes(q),
  );
}
