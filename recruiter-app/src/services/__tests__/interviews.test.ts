import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { create as createCandidate } from '../candidates';
import * as interviews from '../interviews';
import { clearDb } from '../mock-db';
import { create as createReq } from '../requisitions';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

async function fixtures() {
  const req = await createReq({
    role_title: 'R',
    role_location: '',
    department: 'Product',
    created_by: 'user_1',
    created_by_name: 'Nitin',
  });
  const cand = await createCandidate(req.id, { name: 'Ada', email: 'ada@ex.com' });
  return { req, cand };
}

describe('interviews service', () => {
  test('schedule validates date + email', async () => {
    const { req, cand } = await fixtures();
    const first = req.rounds[0];
    if (!first) throw new Error('expected rounds');
    await expect(
      interviews.schedule(req.id, cand.id, first.id, {
        scheduled_at: 'not-a-date',
        interviewer_email: 'no',
        interviewer_name: 'Jordan',
      }),
    ).rejects.toThrow(/scheduled_at/);
  });

  test('schedule transitions round to scheduled', async () => {
    const { req, cand } = await fixtures();
    const first = req.rounds[0];
    if (!first) throw new Error('expected rounds');
    const cr = await interviews.schedule(req.id, cand.id, first.id, {
      scheduled_at: '2026-05-01T17:00:00Z',
      interviewer_email: 'jordan@ex.com',
      interviewer_name: 'Jordan',
    });
    expect(cr.status).toBe('scheduled');
    expect(cr.interviewer_email).toBe('jordan@ex.com');
  });

  test('reschedule requires scheduled state', async () => {
    const { req, cand } = await fixtures();
    const first = req.rounds[0];
    if (!first) throw new Error('expected rounds');
    await expect(
      interviews.reschedule(req.id, cand.id, first.id, {
        scheduled_at: '2026-05-02T17:00:00Z',
      }),
    ).rejects.toThrow(/scheduled/);
  });

  test('cancel clears schedule fields', async () => {
    const { req, cand } = await fixtures();
    const first = req.rounds[0];
    if (!first) throw new Error('expected rounds');
    await interviews.schedule(req.id, cand.id, first.id, {
      scheduled_at: '2026-05-01T17:00:00Z',
      interviewer_email: 'jordan@ex.com',
      interviewer_name: 'Jordan',
    });
    const cr = await interviews.cancel(req.id, cand.id, first.id);
    expect(cr.status).toBe('cancelled');
    expect(cr.interviewer_email).toBeNull();
  });

  test('sendReminder works for scheduled round', async () => {
    const { req, cand } = await fixtures();
    const first = req.rounds[0];
    if (!first) throw new Error('expected rounds');
    const cr = await interviews.schedule(req.id, cand.id, first.id, {
      scheduled_at: '2026-05-01T17:00:00Z',
      interviewer_email: 'jordan@ex.com',
      interviewer_name: 'Jordan',
    });
    const result = await interviews.sendReminder(cr.id);
    expect(result).toEqual({ sent: true });
  });
});
