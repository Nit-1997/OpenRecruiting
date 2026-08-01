import { describe, expect, test } from 'bun:test';
import { render } from '@testing-library/react';
import type { AnswerState, QuestionSnapshot } from '@/types/intake';
import { PrefilledAnswerCard } from './prefilled-answer-card';

const Q: QuestionSnapshot = {
  id: 'q4_must_haves',
  order: 4,
  topic: 'Must-Have Skills & Experience',
  default_text: '...',
};

function answer(over: Partial<AnswerState> = {}): AnswerState {
  return {
    status: 'untouched',
    text: 'Python, Postgres',
    prefilled_text: 'Python, Postgres',
    extraction_confidence: 'medium',
    sources: ['jd'],
    turns_addressed: [],
    ...over,
  };
}

describe('PrefilledAnswerCard', () => {
  test('renders question topic, text, confidence pill, source list', () => {
    const { container } = render(<PrefilledAnswerCard id="card" question={Q} answer={answer()} />);
    expect(container.textContent).toContain('Must-Have Skills');
    expect(container.textContent).toContain('Python, Postgres');
    expect(document.getElementById('card-confidence')?.textContent).toContain('medium');
    expect(document.getElementById('card-sources')?.textContent).toContain('jd');
  });

  test('renders empty-state copy when text is null', () => {
    const { container } = render(
      <PrefilledAnswerCard id="card" question={Q} answer={answer({ text: null })} />,
    );
    expect(container.textContent ?? '').toMatch(/we'?ll cover this in conversation/i);
  });

  test('shows low-confidence badge variant', () => {
    render(
      <PrefilledAnswerCard
        id="card"
        question={Q}
        answer={answer({ extraction_confidence: 'low' })}
      />,
    );
    expect(document.getElementById('card-confidence')?.dataset.confidence).toBe('low');
  });
});
