import type { SourcingCriteria } from './sourcing-queries';

export type CandidateSource = 'linkedin' | 'github' | 'ats';

export interface SourcingCandidate {
  id: string;
  name: string;
  title: string;
  company: string;
  location: string;
  yoe: number;
  industry: string;
  skills: string[];
  source: CandidateSource;
  matchScore: number;
  avatar: string;
  color: string;
  headline: string;
  schoolAt: string;
}

export const SOURCING_CANDIDATES: SourcingCandidate[] = [
  {
    id: 's1',
    name: 'Mohammed Muzawar',
    title: 'Software Engineer',
    company: 'Augment',
    location: 'San Francisco',
    yoe: 6,
    industry: 'ai',
    skills: ['Python', 'Java', 'AWS', 'LLM', 'FastAPI'],
    source: 'linkedin',
    matchScore: 92,
    avatar: 'MM',
    color: '#D9E7F7',
    headline: 'Led agentic systems for logistics workflows at SV startups.',
    schoolAt: 'UC Riverside',
  },
  {
    id: 's2',
    name: 'Priya Desai',
    title: 'Staff Software Engineer',
    company: 'Stripe',
    location: 'San Francisco',
    yoe: 8,
    industry: 'fintech',
    skills: ['Python', 'Go', 'PostgreSQL', 'Kubernetes', 'AWS'],
    source: 'linkedin',
    matchScore: 96,
    avatar: 'PD',
    color: '#F7DDE4',
    headline: 'Self-healing agent framework for on-call response at Stripe.',
    schoolAt: 'IIT Bombay',
  },
  {
    id: 's3',
    name: 'Alex Chen',
    title: 'Senior Software Engineer',
    company: 'Cloudflare',
    location: 'San Francisco',
    yoe: 6,
    industry: 'infra',
    skills: ['Rust', 'Go', 'Python', 'Networking'],
    source: 'github',
    matchScore: 88,
    avatar: 'AC',
    color: '#DFEFDA',
    headline: 'Built in-house tracing agent used by 400+ engineers.',
    schoolAt: 'UC Berkeley',
  },
  {
    id: 's4',
    name: 'Neha Rao',
    title: 'Senior Backend Engineer',
    company: 'Ramp',
    location: 'New York',
    yoe: 5,
    industry: 'fintech',
    skills: ['Python', 'Java', 'PostgreSQL', 'Cassandra', 'gRPC'],
    source: 'linkedin',
    matchScore: 81,
    avatar: 'NR',
    color: '#F2E4C8',
    headline: 'Led migration to gRPC mesh at Ramp.',
    schoolAt: 'Columbia',
  },
  {
    id: 's5',
    name: 'Lorenzo Vitale',
    title: 'ML Platform Engineer',
    company: 'Anthropic',
    location: 'San Francisco',
    yoe: 7,
    industry: 'ai',
    skills: ['Python', 'FastAPI', 'Kubernetes', 'LLM', 'PyTorch'],
    source: 'github',
    matchScore: 94,
    avatar: 'LV',
    color: '#E4DAF5',
    headline: 'Maintainer of agent-harness for agentic evaluation.',
    schoolAt: 'Stanford',
  },
  {
    id: 's6',
    name: 'Amara Obi',
    title: 'Software Engineer',
    company: 'Waymo',
    location: 'Mountain View',
    yoe: 4,
    industry: 'ai',
    skills: ['C++', 'Python', 'Autonomy', 'Perception'],
    source: 'linkedin',
    matchScore: 72,
    avatar: 'AO',
    color: '#D8F3E4',
    headline: 'Ships perception agents for autonomy stack.',
    schoolAt: 'Carnegie Mellon',
  },
  {
    id: 's7',
    name: 'Jordan Park',
    title: 'Senior Software Engineer',
    company: 'Databricks',
    location: 'San Francisco',
    yoe: 6,
    industry: 'saas',
    skills: ['Scala', 'Python', 'Java', 'FastAPI', 'Kafka'],
    source: 'linkedin',
    matchScore: 85,
    avatar: 'JP',
    color: '#F6DCD5',
    headline: 'Lead for runtime autoscaler at Databricks.',
    schoolAt: 'Cornell',
  },
  {
    id: 's8',
    name: 'Harper Shah',
    title: 'Staff Engineer, Platform',
    company: 'Airbnb',
    location: 'San Francisco',
    yoe: 9,
    industry: 'saas',
    skills: ['Java', 'Kotlin', 'Python', 'PostgreSQL', 'Cassandra'],
    source: 'linkedin',
    matchScore: 90,
    avatar: 'HS',
    color: '#E3F1F6',
    headline: 'Led platform networking rearchitecture at Airbnb in 2023.',
    schoolAt: 'Georgia Tech',
  },
  {
    id: 's9',
    name: 'Devika Rao',
    title: 'ML Engineer',
    company: 'Nvidia',
    location: 'Santa Clara',
    yoe: 5,
    industry: 'ai',
    skills: ['CUDA', 'C++', 'Python', 'PyTorch'],
    source: 'github',
    matchScore: 78,
    avatar: 'DR',
    color: '#EEE1F8',
    headline: 'Specialist in GPU scheduling + inference optimization.',
    schoolAt: 'UT Austin',
  },
  {
    id: 's10',
    name: 'Tomás Reyes',
    title: 'Software Engineer II',
    company: 'Retool',
    location: 'San Francisco',
    yoe: 3,
    industry: 'saas',
    skills: ['TypeScript', 'Python', 'Go', 'FastAPI'],
    source: 'linkedin',
    matchScore: 70,
    avatar: 'TR',
    color: '#FDEBC9',
    headline: 'Built Retool AI actions — heavy LLM-agent integration.',
    schoolAt: 'USC',
  },
  {
    id: 's11',
    name: 'Yuki Morimoto',
    title: 'Principal Engineer',
    company: 'DataDog',
    location: 'New York',
    yoe: 12,
    industry: 'saas',
    skills: ['Go', 'Python', 'Rust', 'FastAPI', 'Kafka'],
    source: 'linkedin',
    matchScore: 93,
    avatar: 'YM',
    color: '#D6DFED',
    headline: 'Architected DataDog networking telemetry layer.',
    schoolAt: 'University of Tokyo',
  },
  {
    id: 's12',
    name: "Casey O'Neill",
    title: 'Software Engineer',
    company: 'Notion',
    location: 'San Francisco',
    yoe: 5,
    industry: 'saas',
    skills: ['TypeScript', 'Python', 'Rust', 'FastAPI'],
    source: 'github',
    matchScore: 76,
    avatar: 'CO',
    color: '#E1EEE1',
    headline: 'Notion AI — contributed to agent routing layer.',
    schoolAt: 'U. of Washington',
  },
  {
    id: 's13',
    name: 'Sofia Alvarez',
    title: 'Senior Product Manager',
    company: 'Figma',
    location: 'San Francisco',
    yoe: 7,
    industry: 'growth',
    skills: ['Product strategy', 'Stakeholder mgmt', 'Metrics', 'Analytics'],
    source: 'linkedin',
    matchScore: 95,
    avatar: 'SA',
    color: '#EDE0D8',
    headline: 'Led growth experimentation surface across Figma plans.',
    schoolAt: 'Wharton',
  },
  {
    id: 's14',
    name: 'Ben Kohler',
    title: 'Staff Product Manager',
    company: 'Netflix',
    location: 'Sunnyvale',
    yoe: 9,
    industry: 'growth',
    skills: ['Product analytics', 'Product strategy', 'Experimentation'],
    source: 'linkedin',
    matchScore: 97,
    avatar: 'BK',
    color: '#F0E1D6',
    headline: 'Ran Netflix onboarding surface, doubled 30-day retention.',
    schoolAt: 'Stanford GSB',
  },
  {
    id: 's15',
    name: 'Zara Patel',
    title: 'Senior PM, Growth',
    company: 'Duolingo',
    location: 'New York',
    yoe: 8,
    industry: 'growth',
    skills: ['Product analytics', 'Metrics', 'Stakeholder mgmt'],
    source: 'linkedin',
    matchScore: 88,
    avatar: 'ZP',
    color: '#EADFEC',
    headline: 'Growth PM for learner streaks at Duolingo.',
    schoolAt: 'Columbia',
  },
  {
    id: 's16',
    name: 'Marcus Wang',
    title: 'Senior iOS Engineer',
    company: 'Robinhood',
    location: 'Remote',
    yoe: 7,
    industry: 'fintech',
    skills: ['Swift', 'UIKit', 'SwiftUI', 'Combine'],
    source: 'linkedin',
    matchScore: 91,
    avatar: 'MW',
    color: '#D9EAE1',
    headline: 'Led Robinhood iOS performance work across 3 quarters.',
    schoolAt: 'UIUC',
  },
  {
    id: 's17',
    name: 'Aisha Mensah',
    title: 'iOS Engineer',
    company: 'Lyft',
    location: 'Remote',
    yoe: 6,
    industry: 'saas',
    skills: ['Swift', 'UIKit', 'SwiftUI', 'Testing'],
    source: 'ats',
    matchScore: 87,
    avatar: 'AM',
    color: '#E9DBE5',
    headline: 'Shipped rider app redesign, 25% faster launch time.',
    schoolAt: 'Penn',
  },
  {
    id: 's18',
    name: 'Dmitri Volkov',
    title: 'Backend Engineer',
    company: 'HashiCorp',
    location: 'Austin',
    yoe: 5,
    industry: 'infra',
    skills: ['Go', 'Postgres', 'Kafka', 'Terraform'],
    source: 'github',
    matchScore: 90,
    avatar: 'DV',
    color: '#DEE7F0',
    headline: 'Built event-sourcing layer for Terraform Cloud runs.',
    schoolAt: 'MIT',
  },
  {
    id: 's19',
    name: 'Elena Brooks',
    title: 'Senior Backend Engineer',
    company: 'Gusto',
    location: 'Austin',
    yoe: 6,
    industry: 'fintech',
    skills: ['Go', 'Postgres', 'Kafka', 'gRPC'],
    source: 'ats',
    matchScore: 84,
    avatar: 'EB',
    color: '#E4EADA',
    headline: 'Rewrote payroll runs onto Kafka streams.',
    schoolAt: 'UT Austin',
  },
  {
    id: 's20',
    name: 'Kenji Takahashi',
    title: 'ML Engineer',
    company: 'OpenAI',
    location: 'San Francisco',
    yoe: 7,
    industry: 'ai',
    skills: ['Python', 'PyTorch', 'LLM', 'FastAPI'],
    source: 'linkedin',
    matchScore: 96,
    avatar: 'KT',
    color: '#E0D8EE',
    headline: 'Safety evals for frontier models; author of 4 papers.',
    schoolAt: 'Kyoto University',
  },
  {
    id: 's21',
    name: 'Riya Iyer',
    title: 'ML Engineer',
    company: 'Scale AI',
    location: 'San Francisco',
    yoe: 6,
    industry: 'ai',
    skills: ['Python', 'PyTorch', 'LLM', 'Ray'],
    source: 'linkedin',
    matchScore: 89,
    avatar: 'RI',
    color: '#EFD8E0',
    headline: 'Data labeling infra + RLHF pipelines for Scale.',
    schoolAt: 'IIT Madras',
  },
  {
    id: 's22',
    name: 'Owen Fitzgerald',
    title: 'Frontend Engineer',
    company: 'Vercel',
    location: 'Remote',
    yoe: 6,
    industry: 'saas',
    skills: ['React', 'TypeScript', 'Perf', 'Next.js'],
    source: 'github',
    matchScore: 83,
    avatar: 'OF',
    color: '#D7E5EE',
    headline: 'Core contributor to Next.js App Router polish.',
    schoolAt: 'Dublin City U.',
  },
  {
    id: 's23',
    name: 'Maya Suzuki',
    title: 'Design Engineer',
    company: 'Linear',
    location: 'New York',
    yoe: 5,
    industry: 'saas',
    skills: ['React', 'Motion', 'Tokens', 'WebGL'],
    source: 'linkedin',
    matchScore: 86,
    avatar: 'MS',
    color: '#F2DEDA',
    headline: 'Built interaction model for Linear canvas.',
    schoolAt: 'SVA',
  },
  {
    id: 's24',
    name: 'Samir Khan',
    title: 'Product Designer',
    company: 'Airtable',
    location: 'New York',
    yoe: 7,
    industry: 'saas',
    skills: ['Interaction', 'Systems', 'Prototyping'],
    source: 'linkedin',
    matchScore: 80,
    avatar: 'SK',
    color: '#E8EAD8',
    headline: 'Systems lead for Airtable extensions platform.',
    schoolAt: 'RISD',
  },
];

export const TOTAL_MATCH_COUNT_LABEL = '5.3k';

function normalize(value: string): string {
  return value.toLowerCase().trim();
}

function matchesLocation(candidateLoc: string, filterLoc: string): boolean {
  const a = normalize(candidateLoc);
  const b = normalize(filterLoc);
  if (!b) return true;
  if (a === b) return true;
  if (a.includes(b)) return true;
  if (b === 'sf' && a.includes('san francisco')) return true;
  if (b === 'san francisco' && a.includes('sf')) return true;
  if (b === 'nyc' && a.includes('new york')) return true;
  if (b === 'new york' && a.includes('nyc')) return true;
  return false;
}

function matchesTitle(candidateTitle: string, filterTitle: string): boolean {
  const a = normalize(candidateTitle);
  const b = normalize(filterTitle);
  if (!b) return true;
  if (a.includes(b)) return true;
  const head = b.split(/\s+/).filter((t) => t.length > 2);
  if (head.length === 0) return false;
  return head.every((t) => a.includes(t));
}

function matchesYoe(candidateYoe: number, filterYoe: string): boolean {
  const m = filterYoe.match(/(\d+)/);
  if (!m) return true;
  const min = Number.parseInt(m[1] ?? '0', 10);
  if (!Number.isFinite(min)) return true;
  return candidateYoe >= min;
}

function matchesIndustry(candidateIndustry: string, filterIndustry: string): boolean {
  const a = normalize(candidateIndustry);
  const b = normalize(filterIndustry);
  if (!b) return true;
  if (a === b) return true;
  // Loose alignment: "growth" & "product analytics" both imply saas/growth roles.
  if (b === 'growth' && (a === 'growth' || a === 'saas')) return true;
  if (b === 'product analytics' && (a === 'growth' || a === 'saas')) return true;
  if (b === 'platform' && (a === 'infra' || a === 'saas')) return true;
  if (b === 'ai' && a === 'ml') return true;
  if (b === 'ml' && a === 'ai') return true;
  return false;
}

function matchesSkills(candidateSkills: string[], filterSkills: string[]): boolean {
  if (!filterSkills || filterSkills.length === 0) return true;
  const set = new Set(candidateSkills.map((s) => normalize(s)));
  let hits = 0;
  for (const want of filterSkills) {
    const w = normalize(want);
    for (const have of set) {
      if (have.includes(w) || w.includes(have)) {
        hits += 1;
        break;
      }
    }
  }
  // at least 1 skill overlap, or at least half the requested skills
  return hits >= 1 || hits >= Math.ceil(filterSkills.length / 2);
}

export function filterByQuery(
  candidates: SourcingCandidate[],
  criteria: SourcingCriteria,
): SourcingCandidate[] {
  const any =
    Boolean(criteria.title) ||
    Boolean(criteria.location) ||
    Boolean(criteria.yoe) ||
    Boolean(criteria.industry) ||
    (criteria.skills && criteria.skills.length > 0);
  const filtered = candidates.filter((c) => {
    if (criteria.title && !matchesTitle(c.title, criteria.title)) return false;
    if (criteria.location && !matchesLocation(c.location, criteria.location)) return false;
    if (criteria.yoe && !matchesYoe(c.yoe, criteria.yoe)) return false;
    if (criteria.industry && !matchesIndustry(c.industry, criteria.industry)) return false;
    if (criteria.skills && !matchesSkills(c.skills, criteria.skills)) return false;
    return true;
  });
  // If criteria specified but no matches, fall back to top matchScore candidates so the
  // results surface is never empty in the demo.
  const source = any && filtered.length === 0 ? [...candidates] : filtered;
  return [...source].sort((a, b) => b.matchScore - a.matchScore);
}

export function findCandidate(id: string): SourcingCandidate | null {
  return SOURCING_CANDIDATES.find((c) => c.id === id) ?? null;
}
