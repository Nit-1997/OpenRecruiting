import { describe, expect, test } from 'bun:test';
import { fuzzyScore, rankByFuzzy, tokenize } from './fuzzy-rank';

describe('tokenize', () => {
  test('lowercases, splits on non-alphanumerics, drops stopwords + 1-char tokens', () => {
    expect(tokenize('Video Interview with Shipt (Staff AI Engineer)')).toEqual([
      'shipt',
      'staff',
      'ai',
      'engineer',
    ]);
  });

  test('returns empty for all-stopword / empty input', () => {
    expect(tokenize('  the interview  ')).toEqual([]);
    expect(tokenize('')).toEqual([]);
  });
});

describe('fuzzyScore', () => {
  test('rewards exact token matches above substring matches', () => {
    const exact = fuzzyScore('Staff AI Engineer', 'AI Engineer');
    const none = fuzzyScore('Staff AI Engineer', 'Product Manager');
    expect(exact).toBeGreaterThan(none);
    expect(none).toBe(0);
  });

  test('more matched tokens scores higher', () => {
    const two = fuzzyScore('Staff AI Engineer', 'Staff Engineer');
    const one = fuzzyScore('Staff AI Engineer', 'Frontend Engineer');
    expect(two).toBeGreaterThan(one);
  });

  test('empty query scores zero (no false ranking signal)', () => {
    expect(fuzzyScore('   ', 'Anything')).toBe(0);
  });
});

describe('rankByFuzzy', () => {
  const titles = [
    'Product Manager',
    'Senior Frontend Engineer',
    'Senior Software Engineer',
    'Staff AI Engineer',
  ];

  test('ranks the closest title to the meeting first, manager last', () => {
    const ranked = rankByFuzzy(titles, 'Video Interview with Shipt (Staff AI Engineer)', (t) => t);
    expect(ranked[0]).toBe('Staff AI Engineer');
    expect(ranked[ranked.length - 1]).toBe('Product Manager');
  });

  test('is stable for equal scores (preserves input order)', () => {
    const ranked = rankByFuzzy(['B Engineer', 'A Engineer'], 'engineer', (t) => t);
    expect(ranked).toEqual(['B Engineer', 'A Engineer']);
  });

  test('does not mutate the input array', () => {
    const input = [...titles];
    rankByFuzzy(input, 'engineer', (t) => t);
    expect(input).toEqual(titles);
  });
});
