import { beforeEach, describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { useArtifactStore, useRequisitionStore } from '@/stores';
import type { Requisition, Round } from '@/types';
import { RequisitionArtifact } from './requisition-artifact';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkRound(id: string, n: number, withQuestion = true): Round {
  return {
    id,
    requisitionId: 'req-1',
    roundNumber: n,
    name: `Round ${n}`,
    category: 'behavioral',
    durationMinutes: 45,
    description: '',
    skills: [],
    guidelines: [],
    feedbackQuestions: withQuestion
      ? [
          {
            id: `fq-${id}`,
            roundId: id,
            questionNumber: 1,
            heading: 'Heading',
            description: null,
          },
        ]
      : [],
  };
}

function seedReq(rounds: Round[]): Requisition {
  return {
    id: 'req-1',
    roleTitle: 'Staff Product Manager',
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
  useArtifactStore.getState().reset();
  useRequisitionStore.getState().reset();
});

describe('RequisitionArtifact', () => {
  test('renders nothing when requisition not in store', () => {
    const { container } = render(<RequisitionArtifact id="art" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders hero title, location, and rounds list', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(<RequisitionArtifact id="art" artifactId="req-1" />);
    expect(defined(container.querySelector('#art-hero-title')).textContent).toBe(
      'Staff Product Manager',
    );
    expect(defined(container.querySelector('#art-hero-sub')).textContent).toContain('Sunnyvale');
    expect(container.querySelector('#art-rounds')).not.toBeNull();
  });

  test('clicking a round pushes the detail view; back pops', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1)]));
    const { container } = render(<RequisitionArtifact id="art" artifactId="req-1" />);
    fireEvent.click(defined(container.querySelector('#art-rounds-row-a')));
    expect(container.querySelector('#art-detail')).not.toBeNull();
    expect(container.querySelector('#art-rounds')).toBeNull();

    fireEvent.click(defined(container.querySelector('#art-detail-back')));
    expect(container.querySelector('#art-detail')).toBeNull();
    expect(container.querySelector('#art-rounds')).not.toBeNull();
  });

  test('renders checklist while intake processing, hides rounds list', () => {
    const req = seedReq([]);
    req.intakeProcessingStatus = 'processing';
    req.intakeProcessingStage = 'building_plan';
    useRequisitionStore.getState().upsertRequisition(req);
    const { container } = render(<RequisitionArtifact id="art" artifactId="req-1" />);
    expect(container.querySelector('#art-checklist')).not.toBeNull();
    expect(container.querySelector('#art-rounds')).toBeNull();
    expect(defined(container.querySelector('#art-hero-status')).textContent).toBe('Drafting');
  });

  test('does not render its own publish button (lives in artifact head)', () => {
    useRequisitionStore.getState().upsertRequisition(seedReq([mkRound('a', 1, true)]));
    const { container } = render(<RequisitionArtifact id="art" artifactId="req-1" />);
    expect(container.querySelector('#art-publish')).toBeNull();
  });
});
