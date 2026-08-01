import { beforeEach, describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { useRequisitionStore } from '@/stores';
import type { Requisition, Round } from '@/types';
import { RoundList } from './round-list';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkRound(id: string, n: number, name: string): Round {
  return {
    id,
    requisitionId: 'req-1',
    roundNumber: n,
    name,
    category: 'behavioral',
    durationMinutes: 45,
    description: '',
    skills: [],
    guidelines: [],
    feedbackQuestions: [],
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

describe('RoundList', () => {
  test('renders one row per round in order', () => {
    useRequisitionStore
      .getState()
      .upsertRequisition(seedReq([mkRound('a', 1, 'A'), mkRound('b', 2, 'B')]));
    const { container } = render(<RoundList id="rl" reqId="req-1" onSelect={() => {}} />);
    expect(defined(container.querySelector('#rl-row-a-name')).textContent).toBe('A');
    expect(defined(container.querySelector('#rl-row-b-name')).textContent).toBe('B');
  });

  test('add button appends a default round', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([]));
    const { container } = render(<RoundList id="rl" reqId="req-1" onSelect={() => {}} />);
    fireEvent.click(defined(container.querySelector('#rl-add')));
    const rounds = defined(useRequisitionStore.getState().requisitions['req-1']).rounds;
    expect(rounds.length).toBe(1);
  });

  test('move-up swaps row order', () => {
    useRequisitionStore
      .getState()
      .upsertRequisition(seedReq([mkRound('a', 1, 'A'), mkRound('b', 2, 'B')]));
    const { container } = render(<RoundList id="rl" reqId="req-1" onSelect={() => {}} />);
    fireEvent.click(defined(container.querySelector('#rl-row-b-up')));
    const rounds = defined(useRequisitionStore.getState().requisitions['req-1']).rounds;
    expect(defined(rounds[0]).id).toBe('b');
    expect(defined(rounds[1]).id).toBe('a');
  });

  test('clicking a row fires onSelect with id', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1, 'A')]));
    const received: string[] = [];
    const { container } = render(
      <RoundList id="rl" reqId="req-1" onSelect={(id) => received.push(id)} />,
    );
    fireEvent.click(defined(container.querySelector('#rl-row-a')));
    expect(received).toEqual(['a']);
  });
});
