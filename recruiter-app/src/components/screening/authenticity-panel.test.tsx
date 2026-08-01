// FE coverage for the candidate-authenticity scorecard panel.
//
// Presentational component: it renders the structured authenticity_signals dict
// the screening feedback service computes. The product stance is DIRECTIONAL —
// a recruiter-facing signal, never a pass/fail gate — so the test asserts the
// overall badge, per-signal rows, and the explicit "not a gate" disclaimer, and
// that nothing renders when signals are absent.

import { describe, expect, test } from 'bun:test';
import { render } from '@testing-library/react';
import type { AuthenticitySignals } from '@/domain/candidate';
import { AuthenticityPanel } from './authenticity-panel';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

const SIGNALS: AuthenticitySignals = {
  overall: 'some_concern',
  confidence: 0.6,
  signals: [
    { kind: 'specificity', level: 'low', note: 'Answers stayed generic.' },
    { kind: 'read_aloud', level: 'medium', note: 'Cadence felt scripted.' },
  ],
  summary: 'Directional: a couple of answers read as rehearsed.',
};

describe('AuthenticityPanel', () => {
  test('renders the overall badge, summary, per-signal rows, and disclaimer', () => {
    const { container } = render(<AuthenticityPanel id="ap" signals={SIGNALS} />);

    // Overall directional badge with a human label.
    expect(defined(container.querySelector('#ap-overall')).textContent).toContain('Some concern');

    // One-line directional summary.
    expect(defined(container.querySelector('#ap-summary')).textContent).toContain(
      'read as rehearsed',
    );

    // Per-signal rows: kind label + level + note.
    const row0 = defined(container.querySelector('#ap-signal-0'));
    expect(row0.textContent).toContain('Specificity');
    expect(row0.textContent).toContain('Low');
    expect(row0.textContent).toContain('Answers stayed generic.');

    const row1 = defined(container.querySelector('#ap-signal-1'));
    expect(row1.textContent).toContain('Read aloud');
    expect(row1.textContent).toContain('Medium');

    // Explicit "directional, not a pass/fail gate" disclaimer.
    expect(defined(container.querySelector('#ap-disclaimer')).textContent?.toLowerCase()).toContain(
      'not a pass/fail gate',
    );
  });

  test('renders nothing when signals are absent', () => {
    const { container } = render(<AuthenticityPanel id="ap" signals={null} />);
    expect(container.querySelector('#ap')).toBeNull();
  });

  test('renders the overall badge even when there are no individual signal rows', () => {
    const { container } = render(
      <AuthenticityPanel
        id="ap"
        signals={{
          overall: 'likely_authentic',
          confidence: 0.9,
          signals: [],
          summary: 'Answers were specific and consistent.',
        }}
      />,
    );
    expect(defined(container.querySelector('#ap-overall')).textContent).toContain(
      'Likely authentic',
    );
    expect(container.querySelector('#ap-signal-0')).toBeNull();
    expect(container.querySelector('#ap-disclaimer')).not.toBeNull();
  });
});
