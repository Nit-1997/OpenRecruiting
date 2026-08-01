import { describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import type { FeedbackQuestion } from '@/types';
import { FeedbackQuestionRow } from './feedback-question-row';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

const Q: FeedbackQuestion = {
  id: 'q1',
  roundId: 'r1',
  questionNumber: 1,
  heading: 'Problem Decomposition',
  description: 'How they break a hard problem into sub-parts.',
};

describe('FeedbackQuestionRow', () => {
  test('renders heading + description', () => {
    const { container } = render(
      <FeedbackQuestionRow id="fq" question={Q} onSave={() => {}} onDelete={() => {}} />,
    );
    expect(defined(container.querySelector('#fq-q1-heading')).textContent).toBe(
      'Problem Decomposition',
    );
    expect(defined(container.querySelector('#fq-q1-description')).textContent).toBe(
      'How they break a hard problem into sub-parts.',
    );
  });

  test('clicking edit shows inputs, save fires onSave with patch', () => {
    const received: Array<{ heading: string; description: string | null }> = [];
    const { container } = render(
      <FeedbackQuestionRow
        id="fq"
        question={Q}
        onSave={(p) => received.push(p)}
        onDelete={() => {}}
      />,
    );
    fireEvent.click(defined(container.querySelector('#fq-q1-edit')));
    const input = defined(container.querySelector('#fq-q1-heading-input')) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Ownership' } });
    fireEvent.click(defined(container.querySelector('#fq-q1-save')));
    expect(received).toEqual([
      { heading: 'Ownership', description: 'How they break a hard problem into sub-parts.' },
    ]);
  });

  test('delete button fires onDelete with id', () => {
    const received: string[] = [];
    const { container } = render(
      <FeedbackQuestionRow
        id="fq"
        question={Q}
        onSave={() => {}}
        onDelete={(id) => received.push(id)}
      />,
    );
    fireEvent.click(defined(container.querySelector('#fq-q1-delete')));
    expect(received).toEqual(['q1']);
  });
});
