// Phase 2 Task 2.5 — the debrief confirm card (presentational).
//
// Renders a ProposedAction with Confirm / Dismiss and reflects its status. No
// store, no network — the flow owns the execute call; this asserts the card's
// own contract (text, unique ids, callbacks, pending/done states).

import { afterEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import type { ProposedAction } from '@/types/sub-agent';
import { ConfirmCard } from '../confirm-card';

afterEach(() => cleanup());

const ACTION: ProposedAction = {
  kind: 'propose_add_round',
  input: {
    candidate_ids: ['c1'],
    summary: 'Add a System design round',
    rationale: 'The panel never probed architecture depth for Sloane.',
    name: 'System design',
  },
};

const LOG_INSIGHT: ProposedAction = {
  kind: 'propose_log_insight',
  input: {
    candidate_ids: [],
    summary: 'Remember that we value async communication for staff roles',
    rationale: 'You called this out twice across the debrief.',
    insight_kind: 'recruiter_preference',
    text: 'We value async communication for staff engineering roles.',
  },
};

describe('ConfirmCard', () => {
  test('renders summary + rationale + Confirm/Dismiss with unique ids', () => {
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="pending"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );

    expect(container.querySelector('#cc-title')?.textContent).toBe('Add a System design round');
    expect(container.querySelector('#cc-rationale')?.textContent).toContain('architecture depth');
    expect(container.querySelector('#cc-confirm')?.textContent).toContain('Confirm');
    expect(container.querySelector('#cc-dismiss')?.textContent).toContain('Dismiss');

    // Every element with an id is unique across the whole subtree (project rule).
    const ids = Array.from(container.querySelectorAll('[id]')).map((el) => el.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('clicking Confirm calls onConfirm exactly once', () => {
    const onConfirm = mock(() => {});
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="pending"
        onConfirm={onConfirm}
        onDismiss={() => {}}
      />,
    );
    fireEvent.click(container.querySelector('#cc-confirm') as HTMLButtonElement);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  test('clicking Dismiss calls onDismiss', () => {
    const onDismiss = mock(() => {});
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="pending"
        onConfirm={() => {}}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(container.querySelector('#cc-dismiss') as HTMLButtonElement);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test('executing state disables Confirm and shows Applying…', () => {
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="executing"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );
    const confirm = container.querySelector('#cc-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(confirm.textContent).toContain('Applying');
  });

  test('done state replaces the buttons with an applied note', () => {
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="done"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(container.querySelector('#cc-confirm')).toBeNull();
    expect(container.querySelector('#cc-actions')).toBeNull();
    expect(container.querySelector('#cc-status')?.textContent).toContain('Applied');
  });

  test('failed state surfaces a could-not-apply note', () => {
    const { container } = render(
      <ConfirmCard
        id="cc"
        action={ACTION}
        status="failed"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(container.querySelector('#cc-status')?.textContent).toContain('Could not apply');
  });

  test('log_insight kind shows a "Log to Cortex" badge; other kinds do not', () => {
    const insight = render(
      <ConfirmCard
        id="li"
        action={LOG_INSIGHT}
        status="pending"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(insight.container.querySelector('#li-kind')?.textContent).toContain('Log to Cortex');
    // The insight summary/rationale still render as the card's body.
    expect(insight.container.querySelector('#li-title')?.textContent).toContain(
      'async communication',
    );
    expect(insight.container.querySelector('#li-rationale')?.textContent).toContain('twice');
    cleanup();

    // A packet-mutating kind shows NO brain badge.
    const round = render(
      <ConfirmCard
        id="ar"
        action={ACTION}
        status="pending"
        onConfirm={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(round.container.querySelector('#ar-kind')).toBeNull();
  });
});
