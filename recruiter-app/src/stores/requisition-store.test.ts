import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import type {
  FeedbackQuestion,
  IntakeEvent,
  IntakeScreeningQuestion,
  Requisition,
  Round,
} from '@/types';
import { useRequisitionStore } from './requisition-store';

function defined<T>(x: T | undefined): T {
  if (x === undefined) throw new Error('expected defined');
  return x;
}

function baseReq(): Requisition {
  return {
    id: 'req-1',
    roleTitle: 'Staff PM',
    roleLocation: 'Sunnyvale',
    experienceMinYears: 5,
    experienceMaxYears: 8,
    status: 'intake_pending',
    intakeSummary: null,
    intakeProcessingStatus: null,
    intakeProcessingStage: null,
    rounds: [],
    createdAt: '2026-04-19T00:00:00Z',
    updatedAt: '2026-04-19T00:00:00Z',
  };
}

function mkRound(id: string, n: number): Round {
  return {
    id,
    requisitionId: 'req-1',
    roundNumber: n,
    name: `R${n}`,
    category: 'panel',
    durationMinutes: 45,
    description: '',
    skills: [],
    guidelines: [],
    feedbackQuestions: [],
  };
}

function mkQuestion(id: string, roundId: string, n: number, heading: string): FeedbackQuestion {
  return { id, roundId, questionNumber: n, heading, description: null };
}

beforeEach(() => {
  useRequisitionStore.getState().reset();
});

describe('requisition store — basics', () => {
  test('upsertRequisition adds + replaces', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).roleTitle).toBe(
      'Staff PM',
    );

    s.upsertRequisition({ ...baseReq(), roleTitle: 'Principal PM' });
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).roleTitle).toBe(
      'Principal PM',
    );
  });
});

describe('requisition store — applyEvent', () => {
  test('applies stage → intakeProcessingStage', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.applyEvent('req-1', { type: 'stage', stage: 'summarizing' });
    expect(
      defined(useRequisitionStore.getState().requisitions['req-1']).intakeProcessingStage,
    ).toBe('summarizing');
    expect(
      defined(useRequisitionStore.getState().requisitions['req-1']).intakeProcessingStatus,
    ).toBe('processing');
  });

  test('summary.delta appends to intakeSummary', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.applyEvent('req-1', { type: 'summary.delta', token: 'Hello ' });
    s.applyEvent('req-1', { type: 'summary.delta', token: 'world' });
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).intakeSummary).toBe(
      'Hello world',
    );
  });

  test('round.created pushes a round once (no duplicates)', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    const ev: IntakeEvent = { type: 'round.created', round: mkRound('r1', 1) };
    s.applyEvent('req-1', ev);
    s.applyEvent('req-1', ev);
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).rounds.length).toBe(1);
  });

  test('round.details merges guidelines + feedbackQuestions into round', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('r1', 1)] });
    s.applyEvent('req-1', {
      type: 'round.details',
      roundId: 'r1',
      guidelines: [{ title: 'G', description: 'D' }],
      feedbackQuestions: [mkQuestion('q1', 'r1', 1, 'H')],
    });
    const round = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(round.guidelines.length).toBe(1);
    expect(round.feedbackQuestions.length).toBe(1);
  });

  test('done sets status completed + stage completed', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.applyEvent('req-1', { type: 'done' });
    const r = defined(useRequisitionStore.getState().requisitions['req-1']);
    expect(r.intakeProcessingStatus).toBe('completed');
    expect(r.intakeProcessingStage).toBe('completed');
  });
});

describe('requisition store — mutations', () => {
  test('addRound appends with auto roundNumber', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.addRound('req-1', { name: 'New', category: 'behavioral' });
    const rounds = defined(useRequisitionStore.getState().requisitions['req-1']).rounds;
    expect(rounds.length).toBe(1);
    expect(defined(rounds[0]).roundNumber).toBe(1);
  });

  test('reorderRounds renumbers', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1), mkRound('b', 2)] });
    s.reorderRounds('req-1', ['b', 'a']);
    const rounds = defined(useRequisitionStore.getState().requisitions['req-1']).rounds;
    expect(defined(rounds[0]).id).toBe('b');
    expect(defined(rounds[0]).roundNumber).toBe(1);
    expect(defined(rounds[1]).id).toBe('a');
    expect(defined(rounds[1]).roundNumber).toBe(2);
  });

  test('updateRound patches a round', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    s.updateRound('a', { name: 'Updated', durationMinutes: 30 });
    const r = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(r.name).toBe('Updated');
    expect(r.durationMinutes).toBe(30);
  });

  test('deleteRound removes + renumbers', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1), mkRound('b', 2)] });
    s.deleteRound('a');
    const rounds = defined(useRequisitionStore.getState().requisitions['req-1']).rounds;
    expect(rounds.length).toBe(1);
    expect(defined(rounds[0]).id).toBe('b');
    expect(defined(rounds[0]).roundNumber).toBe(1);
  });

  test('addQuestion / updateQuestion / deleteQuestion', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    s.addQuestion('a', { heading: 'Ownership' });
    const q1 = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0])
      .feedbackQuestions[0];
    expect(defined(q1).heading).toBe('Ownership');

    s.updateQuestion(defined(q1).id, { heading: 'Leadership' });
    const q2 = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0])
      .feedbackQuestions[0];
    expect(defined(q2).heading).toBe('Leadership');

    s.deleteQuestion(defined(q1).id);
    const r = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(r.feedbackQuestions.length).toBe(0);
  });

  test('updateGuidelines replaces array', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    s.updateGuidelines('a', [{ title: 'G', description: 'D' }]);
    const r = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(r.guidelines.length).toBe(1);
  });
});

describe('requisition store — undo', () => {
  test('undo reverses last mutation', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.addRound('req-1', { name: 'New', category: 'behavioral' });
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).rounds.length).toBe(1);
    s.undo();
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).rounds.length).toBe(0);
  });

  test('undo is no-op when stack empty', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition(baseReq());
    s.undo();
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).rounds.length).toBe(0);
  });
});

describe('requisition store — screening agent (API-backed)', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function screeningWire(enabled: boolean) {
    return {
      round_id: 'a',
      enabled,
      voice: 'Aura · "Luna"',
      follow_up_style: 'adaptive',
      est_duration_minutes: 5,
      validity_days: 14,
      deploy_scope: 'all_resume_passed',
      questions: [
        {
          id: 'sq1',
          order_index: 0,
          title: 'Ownership',
          prompt: 'Ownership',
          probe: 'why?',
          signal: 'Execution',
          dimension: 'Ownership',
          duration_minutes: 5,
        },
      ],
    };
  }

  function mkScreeningQuestion(): IntakeScreeningQuestion {
    return {
      id: 'sq1',
      order: 0,
      dimension: 'Ownership',
      question: 'Ownership',
      probe: 'why?',
      durationMinutes: 5,
      signal: 'Execution',
    };
  }

  test('attachScreeningAgent calls the API and reflects enabled from the response', async () => {
    const calls: Array<{ url: string; method: string }> = [];
    globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      calls.push({ url, method: init?.method ?? 'GET' });
      // Both PUT (save) and POST (attach) return an enabled config in this flow.
      return new Response(JSON.stringify(screeningWire(true)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    await s.attachScreeningAgent('a', [mkScreeningQuestion()]);

    // PUT (save) then POST (attach) were both issued to the screening path.
    expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/rounds/a/screening'))).toBe(
      true,
    );
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/screening/attach'))).toBe(
      true,
    );

    const round = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(round.screeningAgentEnabled).toBe(true);
    expect(defined(round.screeningAgentQuestions)[0]?.question).toBe('Ownership');
  });

  test('detachScreeningAgent calls the detach endpoint and reflects enabled=false', async () => {
    const calls: Array<{ url: string; method: string }> = [];
    globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      calls.push({ url, method: init?.method ?? 'GET' });
      return new Response(JSON.stringify(screeningWire(false)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const rA = mkRound('a', 1);
    rA.screeningAgentEnabled = true;
    rA.screeningAgentQuestions = [mkScreeningQuestion()];
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [rA] });
    await s.detachScreeningAgent('a');

    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/screening/detach'))).toBe(
      true,
    );
    const round = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(round.screeningAgentEnabled).toBe(false);
  });
});

describe('requisition store — publish', () => {
  test('validatePublish returns errors when rounds lack questions', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    const result = s.validatePublish('req-1');
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors[0]).toMatchObject({ roundId: 'a', reason: 'no_questions' });
    }
  });

  test('validatePublish ok when every round has name + ≥1 question', () => {
    const s = useRequisitionStore.getState();
    const rA = mkRound('a', 1);
    rA.feedbackQuestions = [mkQuestion('q', 'a', 1, 'X')];
    s.upsertRequisition({ ...baseReq(), rounds: [rA] });
    const result = s.validatePublish('req-1');
    expect(result.ok).toBe(true);
  });

  test('publish transitions status when valid', () => {
    const s = useRequisitionStore.getState();
    const rA = mkRound('a', 1);
    rA.feedbackQuestions = [mkQuestion('q', 'a', 1, 'X')];
    s.upsertRequisition({ ...baseReq(), rounds: [rA] });
    const result = s.publish('req-1');
    expect(result.ok).toBe(true);
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).status).toBe('planned');
  });

  test('publish is no-op when invalid', () => {
    const s = useRequisitionStore.getState();
    s.upsertRequisition({ ...baseReq(), rounds: [mkRound('a', 1)] });
    const result = s.publish('req-1');
    expect(result.ok).toBe(false);
    expect(defined(useRequisitionStore.getState().requisitions['req-1']).status).toBe(
      'intake_pending',
    );
  });
});
