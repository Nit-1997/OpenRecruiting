import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { clearDb, generateId, getDb, nowIso, persist, resetDb } from '../mock-db';

beforeEach(() => clearDb());
afterEach(() => clearDb());

describe('mock-db', () => {
  test('getDb returns a usable empty shape when nothing seeded', () => {
    const db = getDb();
    expect(db.requisitions).toEqual([]);
    expect(db.candidates).toEqual([]);
    expect(db.billing.interview_total).toBe(25);
    expect(db.profile.name).toBe('Taylor');
  });

  test('resetDb replaces the working state', () => {
    const db = getDb();
    resetDb({ ...db, requisitions: [], _meta: { ...db._meta, seeded_at: '2026-01-01T00:00:00Z' } });
    expect(getDb()._meta.seeded_at).toBe('2026-01-01T00:00:00Z');
  });

  test('generateId produces unique prefixed ids', () => {
    const a = generateId('req');
    const b = generateId('req');
    expect(a).not.toEqual(b);
    expect(a.startsWith('req_')).toBe(true);
  });

  test('nowIso returns ISO string parseable back to Date', () => {
    const s = nowIso();
    expect(Number.isNaN(new Date(s).getTime())).toBe(false);
  });

  test('persist does not throw when window is unavailable', () => {
    expect(() => persist()).not.toThrow();
  });
});
