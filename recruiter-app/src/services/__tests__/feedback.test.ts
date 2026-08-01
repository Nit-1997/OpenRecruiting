import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { create as createCandidate, listRounds } from '../candidates';
import * as feedback from '../feedback';
import { clearDb } from '../mock-db';
import { addQuestion, create as createReq } from '../requisitions';
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
  const first = req.rounds[0];
  if (!first) throw new Error('expected rounds');
  const q = await addQuestion(first.id, { heading: 'Discovery', description: '' });
  const cand = await createCandidate(req.id, { name: 'Ada', email: 'ada@ex.com' });
  return { req, cand, questionId: q.id, firstRoundId: first.id };
}

describe('feedback service', () => {
  test('submitFeedback requires one entry per question', async () => {
    const { req, cand, firstRoundId } = await fixtures();
    await expect(
      feedback.submitFeedback(req.id, cand.id, firstRoundId, {
        entries: [],
        scorecard: [],
        overall_rating: 'yes',
        summary: 'ok',
      }),
    ).rejects.toThrow(/Expected/);
  });

  test('submitFeedback marks round completed and writes entries', async () => {
    const { req, cand, questionId, firstRoundId } = await fixtures();
    await feedback.submitFeedback(req.id, cand.id, firstRoundId, {
      entries: [
        {
          feedback_question_id: questionId,
          rating: 'yes',
          evidence_status: 'verified',
          feedback_text: 'strong',
        },
      ],
      scorecard: [{ dimension: 'Discovery', rating: 'yes', notes: '' }],
      overall_rating: 'yes',
      summary: 'ok',
    });
    const entries = await feedback.getRoundFeedback(req.id, cand.id, firstRoundId);
    expect(entries.length).toBe(1);
  });

  test('requestFeedback validates interviewer email', async () => {
    const { req, cand, firstRoundId } = await fixtures();
    await expect(
      feedback.requestFeedback(req.id, cand.id, firstRoundId, {
        interviewer_email: 'nope',
        interviewer_name: 'J',
        channel: 'email',
      }),
    ).rejects.toThrow(/interviewer_email/);
  });

  test('getRecording returns a stub and flags availability', async () => {
    const { req, cand, questionId, firstRoundId } = await fixtures();
    await feedback.submitFeedback(req.id, cand.id, firstRoundId, {
      entries: [
        {
          feedback_question_id: questionId,
          rating: 'yes',
          evidence_status: 'verified',
          feedback_text: '',
        },
      ],
      scorecard: [],
      overall_rating: 'yes',
      summary: '',
    });
    const crs = await listRounds(req.id, cand.id);
    const first = crs[0];
    if (!first) throw new Error('expected candidate rounds');
    const rec = await feedback.getRecording(first.id);
    expect(rec.available).toBe(true);
    expect(rec.duration_seconds).toBeGreaterThan(0);
  });
});
