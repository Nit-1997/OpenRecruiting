import { describe, expect, test } from 'bun:test';
import type { Round } from '@/domain';
import { getRoundsForCandidate, getSharedRounds, isCustomRound } from './rounds';

function makeRound(overrides: Partial<Round> = {}): Round {
  return {
    id: 'r1',
    requisition_id: 'req-1',
    name: 'Phone screen',
    round_number: 1,
    duration_minutes: 30,
    category: 'screening',
    description: null,
    skills: [],
    feedback_questions: [],
    is_custom: false,
    for_candidate_id: null,
    ...overrides,
  } as Round;
}

describe('isCustomRound', () => {
  test('true when is_custom flag is set', () => {
    expect(isCustomRound(makeRound({ is_custom: true }))).toBe(true);
  });

  test('true when for_candidate_id is set (candidate-specific round)', () => {
    expect(isCustomRound(makeRound({ for_candidate_id: 'cand-1' }))).toBe(true);
  });

  test('false when neither flag is set (shared plan round)', () => {
    expect(isCustomRound(makeRound())).toBe(false);
  });

  test('handles a minimal pick shape (only the two fields it consults)', () => {
    expect(isCustomRound({ is_custom: true, for_candidate_id: null })).toBe(true);
    expect(isCustomRound({ is_custom: false, for_candidate_id: null })).toBe(false);
  });
});

describe('getSharedRounds', () => {
  test('filters out custom + candidate-specific rounds, keeps shared rounds in order', () => {
    const rounds = [
      makeRound({ id: 'shared-1', round_number: 1 }),
      makeRound({ id: 'custom-1', is_custom: true, round_number: 2 }),
      makeRound({ id: 'cand-only', for_candidate_id: 'c-7', round_number: 3 }),
      makeRound({ id: 'shared-2', round_number: 4 }),
    ];
    const out = getSharedRounds(rounds);
    expect(out.map((r) => r.id)).toEqual(['shared-1', 'shared-2']);
  });

  test('returns empty when every round is custom', () => {
    const rounds = [makeRound({ is_custom: true }), makeRound({ for_candidate_id: 'c-1' })];
    expect(getSharedRounds(rounds)).toEqual([]);
  });

  test('returns empty for empty input', () => {
    expect(getSharedRounds([])).toEqual([]);
  });
});

describe('getRoundsForCandidate', () => {
  test('returns shared rounds plus the candidate-specific custom rounds', () => {
    const rounds = [
      makeRound({ id: 's1' }),
      makeRound({ id: 'c1-custom', is_custom: true, for_candidate_id: 'c-1' }),
      makeRound({ id: 'c2-custom', is_custom: true, for_candidate_id: 'c-2' }),
      makeRound({ id: 's2' }),
    ];
    const c1 = getRoundsForCandidate(rounds, 'c-1');
    expect(c1.map((r) => r.id)).toEqual(['s1', 'c1-custom', 's2']);
  });

  test('omits other candidates’ custom rounds', () => {
    const rounds = [
      makeRound({ id: 'c1', is_custom: true, for_candidate_id: 'c-1' }),
      makeRound({ id: 'c2', is_custom: true, for_candidate_id: 'c-2' }),
    ];
    expect(getRoundsForCandidate(rounds, 'c-1').map((r) => r.id)).toEqual(['c1']);
  });
});
