import { describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import type { Round } from '@/types';
import { RoundCard } from './round-card';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkRound(overrides: Partial<Round> = {}): Round {
  return {
    id: 'r1',
    requisitionId: 'req-1',
    roundNumber: 2,
    name: 'Hiring Manager Interview',
    category: 'behavioral',
    durationMinutes: 45,
    description: '',
    skills: [],
    guidelines: [],
    feedbackQuestions: [],
    ...overrides,
  };
}

describe('RoundCard', () => {
  test('renders number, name, duration, category badge', () => {
    const { container } = render(<RoundCard id="rc" round={mkRound()} onSelect={() => {}} />);
    expect(defined(container.querySelector('#rc-row-r1-number')).textContent).toBe('2');
    expect(defined(container.querySelector('#rc-row-r1-name')).textContent).toBe(
      'Hiring Manager Interview',
    );
    expect(defined(container.querySelector('#rc-row-r1-duration')).textContent).toBe('45 min');
    expect(defined(container.querySelector('#rc-row-r1-badge')).getAttribute('data-category')).toBe(
      'behavioral',
    );
  });

  test('shows shimmer when isBuilding', () => {
    const { container } = render(
      <RoundCard id="rc" round={mkRound()} onSelect={() => {}} isBuilding />,
    );
    const shimmer = container.querySelector('#rc-row-r1-shimmer');
    expect(shimmer).not.toBeNull();
  });

  test('shows summary line when hydrated with questions + guidelines', () => {
    const { container } = render(
      <RoundCard
        id="rc"
        round={mkRound({
          guidelines: [{ title: 'g', description: 'd' }],
          feedbackQuestions: [
            {
              id: 'q',
              roundId: 'r1',
              questionNumber: 1,
              heading: 'x',
              description: null,
            },
          ],
        })}
        onSelect={() => {}}
      />,
    );
    const summary = defined(container.querySelector('#rc-row-r1-summary'));
    expect(summary.textContent).toContain('1 question');
    expect(summary.textContent).toContain('1 guideline');
  });

  test('shows the eligibility nudge when aiScreenable and not attached', () => {
    const { container } = render(
      <RoundCard
        id="rc"
        round={mkRound({
          aiScreenable: true,
          aiScreenableReason: 'Recruiter screen — OpenRecruiting can host this.',
        })}
        onSelect={() => {}}
      />,
    );
    const nudge = defined(container.querySelector('#rc-row-r1-ai-nudge'));
    expect(nudge.textContent).toContain('OpenRecruiting can take this round');
    expect(nudge.getAttribute('title')).toBe('Recruiter screen — OpenRecruiting can host this.');
  });

  test('hides the nudge once the screening agent is attached', () => {
    const { container } = render(
      <RoundCard
        id="rc"
        round={mkRound({ aiScreenable: true, screeningAgentEnabled: true })}
        onSelect={() => {}}
      />,
    );
    expect(container.querySelector('#rc-row-r1-ai-nudge')).toBeNull();
    expect(container.querySelector('#rc-row-r1-ai-badge')).not.toBeNull();
  });

  test('clicking the row fires onSelect with round id', () => {
    const received: string[] = [];
    const { container } = render(
      <RoundCard id="rc" round={mkRound()} onSelect={(id) => received.push(id)} />,
    );
    const row = defined(container.querySelector('#rc-row-r1'));
    fireEvent.click(row);
    expect(received).toEqual(['r1']);
  });
});
