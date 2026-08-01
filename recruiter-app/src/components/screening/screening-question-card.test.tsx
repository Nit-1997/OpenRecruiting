import { describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import type { ScreeningQuestion } from '@/services/screening';
import { ScreeningQuestionCard } from './screening-question-card';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkQuestion(overrides: Partial<ScreeningQuestion> = {}): ScreeningQuestion {
  return {
    id: 'q1',
    orderIndex: 0,
    title: 'Metric ownership',
    prompt: 'Walk me through a metric you owned end to end.',
    probe: 'What did you do when it dipped?',
    signal: 'execution',
    dimension: 'ownership',
    durationMinutes: 5,
    ...overrides,
  };
}

describe('ScreeningQuestionCard', () => {
  test('renders zero-padded index, title, prompt, probe, footer', () => {
    const { container } = render(
      <ScreeningQuestionCard id="qc" index={0} question={mkQuestion()} onChange={() => {}} />,
    );
    expect(defined(container.querySelector('#qc-label')).textContent).toContain('Q01');
    expect(defined(container.querySelector('#qc-label')).textContent?.toUpperCase()).toContain(
      'METRIC OWNERSHIP',
    );
    expect(defined(container.querySelector('#qc-prompt')).textContent).toContain(
      'Walk me through a metric you owned end to end.',
    );
    expect(defined(container.querySelector('#qc-probe')).textContent).toContain(
      'What did you do when it dipped?',
    );
    const footer = defined(container.querySelector('#qc-footer')).textContent ?? '';
    expect(footer.toUpperCase()).toContain('5 MIN');
    expect(footer.toUpperCase()).toContain('EXECUTION');
  });

  test('pencil toggles edit mode and editing a field calls onChange', () => {
    const received: ScreeningQuestion[] = [];
    const { container } = render(
      <ScreeningQuestionCard
        id="qc"
        index={2}
        question={mkQuestion()}
        onChange={(q) => received.push(q)}
      />,
    );
    // Index is 1-based padded -> Q03.
    expect(defined(container.querySelector('#qc-label')).textContent).toContain('Q03');

    fireEvent.click(defined(container.querySelector('#qc-edit')));
    const titleInput = defined(container.querySelector('#qc-edit-title')) as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: 'Renamed' } });

    expect(received.length).toBeGreaterThan(0);
    expect(defined(received.at(-1)).title).toBe('Renamed');
  });
});
