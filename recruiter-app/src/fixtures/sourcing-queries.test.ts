import { describe, expect, test } from 'bun:test';
import { countCriteria, criteriaFromRole, parseQuery, TRY_QUERIES } from './sourcing-queries';
import { filterByQuery, SOURCING_CANDIDATES } from './sourcing-results';

describe('parseQuery', () => {
  test('extracts title', () => {
    const c = parseQuery('I need a software engineer');
    expect(c.title?.toLowerCase()).toContain('software engineer');
  });

  test('extracts location after "in"', () => {
    const c = parseQuery('Staff PMs in Sunnyvale please');
    expect(c.location?.toLowerCase()).toContain('sunnyvale');
  });

  test('extracts yoe with plus and years variants', () => {
    const c1 = parseQuery('5+ years of experience');
    expect(c1.yoe).toBe('5+ years');
    const c2 = parseQuery('7 yrs');
    expect(c2.yoe).toBe('7+ years');
  });

  test('extracts industry token', () => {
    const c = parseQuery('Product manager in growth');
    expect(c.industry).toBe('growth');
  });

  test('extracts a comma-separated skill list after "using"', () => {
    const c = parseQuery('Engineers using Python, Go, Rust');
    expect(c.skills?.length).toBeGreaterThan(0);
    expect(c.skills?.map((s) => s.toLowerCase())).toContain('python');
  });

  test('returns empty for empty / nonsense input', () => {
    expect(parseQuery('')).toEqual({});
    expect(parseQuery('   ')).toEqual({});
    expect(parseQuery('hello world')).toEqual({});
  });

  test('TRY_QUERIES all parse with 3+ criteria', () => {
    for (const q of TRY_QUERIES) {
      const c = parseQuery(q);
      expect(countCriteria(c)).toBeGreaterThanOrEqual(3);
    }
  });
});

describe('criteriaFromRole', () => {
  test('derives a natural-language query + criteria from a role fixture', () => {
    const { text, criteria } = criteriaFromRole({
      title: 'Staff PM · Sunnyvale',
      loc: 'Full-time · Product',
      must_have: ['Product strategy', 'Stakeholder mgmt', 'Metrics'],
    });
    expect(text.length).toBeGreaterThan(0);
    expect(criteria.title).toBeDefined();
    expect(criteria.yoe).toBeDefined();
    expect((criteria.skills ?? []).length).toBeGreaterThan(0);
  });
});

describe('filterByQuery', () => {
  test('no criteria returns all candidates sorted by matchScore', () => {
    const out = filterByQuery(SOURCING_CANDIDATES, {});
    expect(out.length).toBe(SOURCING_CANDIDATES.length);
    expect(out[0]?.matchScore).toBeGreaterThanOrEqual(out[out.length - 1]?.matchScore ?? 0);
  });

  test('location filter narrows candidates', () => {
    const out = filterByQuery(SOURCING_CANDIDATES, { location: 'Austin' });
    expect(out.length).toBeGreaterThan(0);
    for (const c of out) {
      expect(c.location.toLowerCase()).toContain('austin');
    }
  });

  test('title filter matches roughly by token overlap', () => {
    const out = filterByQuery(SOURCING_CANDIDATES, { title: 'Senior PM' });
    expect(out.length).toBeGreaterThan(0);
  });

  test('skills filter counts at least one overlap', () => {
    const out = filterByQuery(SOURCING_CANDIDATES, { skills: ['Python'] });
    expect(out.length).toBeGreaterThan(0);
    expect(out.every((c) => c.skills.some((s) => s.toLowerCase().includes('python')))).toBe(true);
  });

  test('falls back to top matches when no candidates match', () => {
    const out = filterByQuery(SOURCING_CANDIDATES, {
      location: 'Antarctica',
      skills: ['PunchCards'],
    });
    expect(out.length).toBeGreaterThan(0);
  });
});
