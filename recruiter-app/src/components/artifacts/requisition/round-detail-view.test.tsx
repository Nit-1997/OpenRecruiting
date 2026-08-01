import { beforeEach, describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { useRequisitionStore } from '@/stores';
import type { Requisition, Round } from '@/types';
import { RoundDetailView } from './round-detail-view';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkRound(id: string, n: number, overrides: Partial<Round> = {}): Round {
  return {
    id,
    requisitionId: 'req-1',
    roundNumber: n,
    name: `Round ${n}`,
    category: 'behavioral',
    durationMinutes: 45,
    description: 'Assess something.',
    skills: ['communication'],
    guidelines: [{ title: 'G1', description: 'd1' }],
    feedbackQuestions: [
      {
        id: `fq-${id}-1`,
        roundId: id,
        questionNumber: 1,
        heading: 'Heading 1',
        description: 'Desc 1',
      },
    ],
    ...overrides,
  };
}

function seedReq(rounds: Round[]): Requisition {
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
    rounds,
    createdAt: '2026-04-19T00:00:00Z',
    updatedAt: '2026-04-19T00:00:00Z',
  };
}

beforeEach(() => {
  useRequisitionStore.getState().reset();
});

describe('RoundDetailView', () => {
  test('renders header with name, duration, back button', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(
      <RoundDetailView id="rd" reqId="req-1" roundId="a" onBack={() => {}} onNext={() => {}} />,
    );
    expect((defined(container.querySelector('#rd-name')) as HTMLInputElement).value).toBe(
      'Round 1',
    );
    expect((defined(container.querySelector('#rd-duration-input')) as HTMLInputElement).value).toBe(
      '45',
    );
    expect(container.querySelector('#rd-back')).not.toBeNull();
  });

  test('clicking back fires onBack', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    let backed = false;
    const { container } = render(
      <RoundDetailView
        id="rd"
        reqId="req-1"
        roundId="a"
        onBack={() => {
          backed = true;
        }}
        onNext={() => {}}
      />,
    );
    fireEvent.click(defined(container.querySelector('#rd-back')));
    expect(backed).toBe(true);
  });

  test('tabs switch between Edit Details and Guidelines panels', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(
      <RoundDetailView id="rd" reqId="req-1" roundId="a" onBack={() => {}} onNext={() => {}} />,
    );
    expect(container.querySelector('#rd-tab-details-panel')).not.toBeNull();
    expect(container.querySelector('#rd-tab-guidelines-panel')).toBeNull();

    fireEvent.click(defined(container.querySelector('#rd-tab-guidelines')));
    expect(container.querySelector('#rd-tab-details-panel')).toBeNull();
    expect(container.querySelector('#rd-tab-guidelines-panel')).not.toBeNull();
  });

  test('feedback questions list always visible', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(
      <RoundDetailView id="rd" reqId="req-1" roundId="a" onBack={() => {}} onNext={() => {}} />,
    );
    expect(container.querySelector('#rd-questions')).not.toBeNull();
  });

  test('Next button disabled on last round, enabled otherwise', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1), mkRound('b', 2)]));
    const { container: ctrlA } = render(
      <RoundDetailView id="rdA" reqId="req-1" roundId="a" onBack={() => {}} onNext={() => {}} />,
    );
    const nextA = defined(ctrlA.querySelector('#rdA-next')) as HTMLButtonElement;
    expect(nextA.disabled).toBe(false);

    const { container: ctrlB } = render(
      <RoundDetailView id="rdB" reqId="req-1" roundId="b" onBack={() => {}} onNext={() => {}} />,
    );
    const nextB = defined(ctrlB.querySelector('#rdB-next')) as HTMLButtonElement;
    expect(nextB.disabled).toBe(true);
  });

  test('Add question creates a question in the store', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(
      <RoundDetailView id="rd" reqId="req-1" roundId="a" onBack={() => {}} onNext={() => {}} />,
    );
    fireEvent.click(defined(container.querySelector('#rd-questions-add')));
    const round = defined(defined(useRequisitionStore.getState().requisitions['req-1']).rounds[0]);
    expect(round.feedbackQuestions.length).toBe(2);
  });
});
