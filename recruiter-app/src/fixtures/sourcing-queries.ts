export interface SourcingCriteria {
  title?: string;
  location?: string;
  yoe?: string;
  industry?: string;
  skills?: string[];
}

interface CriteriaMatcher {
  key: keyof SourcingCriteria;
  label: string;
  match: (q: string) => string | string[] | null;
}

const JOB_TITLE_PATTERN =
  /\b(staff pm|senior pm|staff product manager|principal engineer|staff engineer|software engineer|backend engineer|frontend engineer|ml engineer|ml platform engineer|data scientist|product manager|product designer|designer|recruiter|legal associate|engineer|pm|analyst)s?\b/i;
const LOCATION_PATTERN =
  /\b(?:in|near|based in|from)\s+((?:san\s+francisco|new york|nyc|london|berlin|bangalore|india|austin|seattle|boston|remote|sf|toronto|dublin|sunnyvale|mountain view|palo alto|oakland))\b/i;
const YOE_PATTERN = /(\d+)\s*(?:\+|-\s*\d+)?\s*(?:y(?:oe|rs?|ears?))/i;
const INDUSTRY_PATTERN =
  /\b(?:in|from)\s+(networking|fintech|saas|healthcare|edtech|ai|ml|crypto|legal|finance|retail|gaming|growth|infra|platform|product analytics)\b/i;
const SKILLS_PATTERN =
  /\b(?:using|skilled in|expertise in|stack of)\s+([a-zA-Z0-9+#.\s,\-/&]+?)(?=\s+(?:in|with|having|using|from|and more|please|only|today|now)\b|[.!?]|$)/i;

function normalizeSkills(raw: string): string[] {
  return raw
    .split(/\s*(?:,|and)\s*/i)
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && s.length < 48)
    .slice(0, 6);
}

const SOURCING_CRITERIA_MATCHERS: CriteriaMatcher[] = [
  {
    key: 'title',
    label: 'Job title',
    match: (q) => {
      const m = q.match(JOB_TITLE_PATTERN);
      return m ? m[0] : null;
    },
  },
  {
    key: 'location',
    label: 'Location',
    match: (q) => {
      const m = q.match(LOCATION_PATTERN);
      return m ? (m[1] ?? null) : null;
    },
  },
  {
    key: 'yoe',
    label: 'Years of experience',
    match: (q) => {
      const m = q.match(YOE_PATTERN);
      return m ? `${m[1]}+ years` : null;
    },
  },
  {
    key: 'industry',
    label: 'Industry',
    match: (q) => {
      const m = q.match(INDUSTRY_PATTERN);
      return m ? (m[1] ?? null) : null;
    },
  },
  {
    key: 'skills',
    label: 'Skills',
    match: (q) => {
      const m = q.match(SKILLS_PATTERN);
      if (!m?.[1]) return null;
      const skills = normalizeSkills(m[1]);
      return skills.length > 0 ? skills : null;
    },
  },
];

export const SOURCING_CRITERIA_LABELS: Record<keyof SourcingCriteria, string> = {
  title: 'Job title',
  location: 'Location',
  yoe: 'Years of experience',
  industry: 'Industry',
  skills: 'Skills',
};

export function parseQuery(text: string): SourcingCriteria {
  const out: SourcingCriteria = {};
  if (!text) return out;
  const normalized = text.trim();
  if (!normalized) return out;
  for (const matcher of SOURCING_CRITERIA_MATCHERS) {
    const hit = matcher.match(normalized);
    if (hit === null || hit === undefined) continue;
    if (matcher.key === 'skills') {
      if (Array.isArray(hit) && hit.length > 0) out.skills = hit;
    } else if (typeof hit === 'string' && hit.length > 0) {
      out[matcher.key] = hit;
    }
  }
  return out;
}

export function countCriteria(c: SourcingCriteria): number {
  let n = 0;
  if (c.title) n += 1;
  if (c.location) n += 1;
  if (c.yoe) n += 1;
  if (c.industry) n += 1;
  if (c.skills && c.skills.length > 0) n += 1;
  return n;
}

export function criteriaFromRole(role: { title: string; loc: string; must_have: string[] }): {
  text: string;
  criteria: SourcingCriteria;
} {
  const skills = (role.must_have ?? []).slice(0, 3);
  const locationSegment = role.loc.includes('·') ? (role.loc.split('·')[0] ?? '').trim() : role.loc;
  const cleanedLoc = locationSegment.toLowerCase() === 'remote' ? 'remote' : locationSegment;
  const skillsClause = skills.length > 0 ? ` using ${skills.join(', ')}` : '';
  const text = `${role.title} in ${cleanedLoc} with 7 years of experience${skillsClause}`.trim();
  const criteria = parseQuery(text);
  if (!criteria.title) criteria.title = role.title;
  if (!criteria.location && cleanedLoc) criteria.location = cleanedLoc;
  if (!criteria.skills && skills.length > 0) criteria.skills = skills;
  if (!criteria.yoe) criteria.yoe = '7+ years';
  return { text, criteria };
}

export const TRY_QUERIES: string[] = [
  'Staff PMs in Sunnyvale with 7 years of experience in growth using Product Analytics',
  'Senior iOS engineers in Remote with 6 years of experience using Swift, UIKit, SwiftUI',
  'Backend engineers in Austin with 5 years of experience using Go, Postgres, Kafka',
  'ML engineers in San Francisco with 7 years of experience using Python, PyTorch, LLM',
];
