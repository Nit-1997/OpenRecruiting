import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import {
  candidates,
  clearDb,
  feedback,
  interviews,
  onServiceEvent,
  requisitions,
  seedDb,
} from '..';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

describe('end-to-end: role → candidate → schedule → feedback', () => {
  test('full happy path emits the right events and leaves consistent state', async () => {
    const events: string[] = [];
    onServiceEvent('requisition:created', () => events.push('req:created'));
    onServiceEvent('candidate:created', () => events.push('cand:created'));
    onServiceEvent('candidate_round:updated', () => events.push('cr:updated'));
    onServiceEvent('feedback:submitted', () => events.push('fb:submitted'));

    const req = await requisitions.create({
      role_title: 'Growth PM',
      role_location: 'Remote',
      department: 'Product',
      created_by: 'user_1',
      created_by_name: 'Nitin',
      round_template: 'staff_pm_4',
    });
    const updated = await requisitions.setStatus(req.id, 'planned');
    expect(updated.status).toBe('planned');

    const firstRound = req.rounds[0];
    if (!firstRound) throw new Error('expected rounds');
    const q = await requisitions.addQuestion(firstRound.id, {
      heading: 'Strategy',
      description: '',
    });

    const cand = await candidates.create(req.id, {
      name: 'Ada Lovelace',
      email: 'ada@ex.com',
    });
    const rounds = await candidates.listRounds(req.id, cand.id);
    expect(rounds.length).toBe(req.rounds.length);

    await interviews.schedule(req.id, cand.id, firstRound.id, {
      scheduled_at: '2026-05-01T17:00:00Z',
      interviewer_email: 'jordan@ex.com',
      interviewer_name: 'Jordan',
    });

    await feedback.submitFeedback(req.id, cand.id, firstRound.id, {
      entries: [
        {
          feedback_question_id: q.id,
          rating: 'yes',
          evidence_status: 'verified',
          feedback_text: 'ok',
        },
      ],
      scorecard: [{ dimension: 'Strategy', rating: 'yes', notes: '' }],
      overall_rating: 'yes',
      summary: 'Solid',
    });

    const finalRounds = await candidates.listRounds(req.id, cand.id);
    expect(finalRounds[0]?.status).toBe('completed');
    expect(finalRounds[0]?.rating).toBe('yes');

    expect(events).toEqual(
      expect.arrayContaining(['req:created', 'cand:created', 'cr:updated', 'fb:submitted']),
    );
  });
});
