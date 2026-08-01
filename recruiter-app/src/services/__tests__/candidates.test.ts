import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import * as candidates from '../candidates';
import { clearDb } from '../mock-db';
import { create as createReq } from '../requisitions';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

async function makeReq() {
  return createReq({
    role_title: 'Test Role',
    role_location: '',
    department: 'Product',
    created_by: 'user_1',
    created_by_name: 'Nitin',
  });
}

describe('candidates service', () => {
  test('listForReq returns only candidates for that req', async () => {
    const req = await makeReq();
    const rows = await candidates.listForReq(req.id);
    expect(rows).toEqual([]);
  });

  test('create validates required fields', async () => {
    const req = await makeReq();
    await expect(candidates.create(req.id, { name: '', email: 'a@b.com' })).rejects.toThrow(/name/);
    await expect(candidates.create(req.id, { name: 'X', email: '' })).rejects.toThrow(/email/);
  });

  test('create rejects duplicate email within the same req', async () => {
    const req = await makeReq();
    await candidates.create(req.id, { name: 'Ada Lovelace', email: 'ada@ex.com' });
    await expect(
      candidates.create(req.id, { name: 'Ada L.', email: 'ada@ex.com' }),
    ).rejects.toThrow(/already/);
  });

  test('create seeds one candidate_round per requisition round', async () => {
    const req = await makeReq();
    const c = await candidates.create(req.id, { name: 'Ada Lovelace', email: 'ada@ex.com' });
    const rounds = await candidates.listRounds(req.id, c.id);
    expect(rounds.length).toBe(req.rounds.length);
    expect(rounds.every((r) => r.status === 'pending')).toBe(true);
  });

  test('setStatus enforces valid candidate transitions', async () => {
    const req = await makeReq();
    const c = await candidates.create(req.id, { name: 'Ada', email: 'ada@ex.com' });
    // active → hired allowed; hired → withdrawn is not.
    await candidates.setStatus(req.id, c.id, 'hired');
    await expect(candidates.setStatus(req.id, c.id, 'withdrawn')).rejects.toThrow(
      /hired to withdrawn/,
    );
  });

  test('remove cascades candidate_rounds', async () => {
    const req = await makeReq();
    const c = await candidates.create(req.id, { name: 'Ada', email: 'ada@ex.com' });
    await candidates.remove(req.id, c.id);
    await expect(candidates.listRounds(req.id, c.id)).rejects.toThrow(/not found/);
  });
});
