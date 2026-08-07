import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { clearDb } from '../mock-db';
import { buildSeed, seedDb } from '../seed';

beforeEach(() => clearDb());
afterEach(() => clearDb());

describe('seed', () => {
  test('buildSeed returns non-empty requisitions + candidates + rounds', () => {
    const seed = buildSeed();
    expect(seed.requisitions.length).toBeGreaterThan(0);
    expect(seed.candidates.length).toBeGreaterThan(0);
    expect(seed.candidate_rounds.length).toBeGreaterThan(0);
  });

  test('every candidate has candidate_rounds matching its requisition rounds', () => {
    const seed = buildSeed();
    seed.candidates.forEach((c) => {
      const req = seed.requisitions.find((r) => r.id === c.requisition_id);
      expect(req).toBeDefined();
      const rounds = seed.candidate_rounds.filter((cr) => cr.candidate_id === c.id);
      if (req) expect(rounds.length).toBe(req.rounds.length);
    });
  });

  test('seedDb writes to the mock db', () => {
    const seed = seedDb();
    expect(seed._meta.version).toBe(1);
  });

  test('integrations list covers recall, untracked_bot', () => {
    const seed = buildSeed();
    const providers = seed.integrations.map((i) => i.provider).sort();
    expect(providers).toEqual(['recall', 'untracked_bot']);
  });
});
