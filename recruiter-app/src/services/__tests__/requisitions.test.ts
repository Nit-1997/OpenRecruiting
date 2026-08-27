import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { clearDb } from '../mock-db';
import {
  addQuestion,
  addRound,
  create,
  deleteQuestion,
  deleteRound,
  get,
  getPlan,
  list,
  reorderRounds,
  setStatus,
  update,
  updateIntake,
  updateQuestion,
  updateRound,
} from '../requisitions';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

const baseInput = {
  role_location: '',
  department: 'Product',
  created_by: 'user_1',
  created_by_name: 'Taylor',
};

describe('requisitions service', () => {
  test('list returns seeded requisitions as paged response', async () => {
    const page = await list();
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.page).toBe(1);
    expect(page.total).toBeGreaterThanOrEqual(page.items.length);
    expect(page.status_counts).toBeDefined();
  });

  test('get returns one requisition by id', async () => {
    const page = await list();
    const first = page.items[0];
    if (!first) throw new Error('expected at least one seeded req');
    const r = await get(first.id);
    expect(r.id).toBe(first.id);
  });

  test('get throws not_found for missing id', async () => {
    await expect(get('nope')).rejects.toThrow(/not found/);
  });

  test('create requires a role_title', async () => {
    await expect(create({ ...baseInput, role_title: '  ' })).rejects.toThrow(/role_title/);
  });

  test('create returns an intake_pending requisition with template rounds', async () => {
    const r = await create({
      ...baseInput,
      role_title: 'Senior iOS Eng',
      round_template: 'senior_eng_5',
    });
    expect(r.status).toBe('intake_pending');
    expect(r.rounds.length).toBe(5);
  });

  test('setStatus enforces valid transitions', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const planned = await setStatus(r.id, 'planned');
    expect(planned.status).toBe('planned');
    await setStatus(r.id, 'closed');
    // closed → planned is allowed (reopen); closed → intake_pending is not.
    await expect(setStatus(r.id, 'intake_pending')).rejects.toThrow(
      /closed to intake_pending/,
    );
  });

  test('update patches non-status fields', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const patched = await update(r.id, { role_title: 'Y' });
    expect(patched.role_title).toBe('Y');
  });

  test('updateIntake writes intake_notes', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const patched = await updateIntake(r.id, 'heavy on discovery');
    expect(patched.intake_notes).toBe('heavy on discovery');
  });

  test('getPlan returns ordered rounds', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const rounds = await getPlan(r.id);
    expect(rounds.map((x) => x.round_number)).toEqual([1, 2, 3, 4]);
  });

  test('addRound inserts at position and renumbers', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const inserted = await addRound(r.id, {
      name: 'Bar raiser',
      category: 'behavioral',
      duration_minutes: 45,
      position: 2,
    });
    const plan = await getPlan(r.id);
    expect(plan[2]?.id).toBe(inserted.id);
    expect(plan.map((p) => p.round_number)).toEqual([1, 2, 3, 4, 5]);
  });

  test('updateRound patches a round', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const plan = await getPlan(r.id);
    const first = plan[0];
    if (!first) throw new Error('expected rounds');
    const patched = await updateRound(first.id, { name: 'Renamed' });
    expect(patched.name).toBe('Renamed');
  });

  test('deleteRound removes and renumbers', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const plan = await getPlan(r.id);
    const first = plan[0];
    if (!first) throw new Error('expected rounds');
    await deleteRound(first.id);
    const next = await getPlan(r.id);
    expect(next.length).toBe(3);
    expect(next.map((p) => p.round_number)).toEqual([1, 2, 3]);
  });

  test('reorderRounds rotates and renumbers', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const plan = await getPlan(r.id);
    const reversed = [...plan].reverse().map((p) => p.id);
    const rotated = await reorderRounds(r.id, reversed);
    expect(rotated.map((p) => p.id)).toEqual(reversed);
    expect(rotated.map((p) => p.round_number)).toEqual([1, 2, 3, 4]);
  });

  test('question CRUD works against a round', async () => {
    const r = await create({ ...baseInput, role_title: 'X' });
    const plan = await getPlan(r.id);
    const first = plan[0];
    if (!first) throw new Error('expected rounds');
    const q = await addQuestion(first.id, { heading: 'Metrics sense', description: 'AARRR' });
    const updated = await updateQuestion(q.id, { heading: 'Metrics intuition' });
    expect(updated.heading).toBe('Metrics intuition');
    await deleteQuestion(q.id);
    const fresh = await getPlan(r.id);
    expect(fresh[0]?.feedback_questions.find((x) => x.id === q.id)).toBeUndefined();
  });
});
