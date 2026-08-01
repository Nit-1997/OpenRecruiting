import { afterEach, describe, expect, test } from 'bun:test';
import { render, waitFor } from '@testing-library/react';
import { useContext } from 'react';
import type { IntakeSession } from '@/types/intake';
import { IntakeSessionContext } from '../IntakeSessionProvider';

// Reads IntakeSessionContext DIRECTLY (not via useIntakeSession) so this test is
// immune to the process-wide mock.module('@/hooks/intake/use-intake-session')
// stubs other intake test files install (bun mock.module is last-writer-wins).
// The FE-J5 fan-out invariant is that all consumers share ONE context source;
// the "subscribe is called exactly once" half lives in use-intake-session.test
// (which owns the realtime mock). Together they prove the single-subscription
// hoist.

afterEach(() => {
  document.body.innerHTML = '';
});

function ContextConsumer({ tag }: { tag: string }) {
  const ctx = useContext(IntakeSessionContext);
  return <div id={`consumer-${tag}`}>{ctx?.session?.status ?? 'none'}</div>;
}

function ctxValue(session: IntakeSession | null) {
  return { sessionId: 'sess-1', session, isLoading: false, error: null };
}

function sharedSession(): IntakeSession {
  return {
    id: 'sess-1',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'ready',
    active_modality: null,
    entry_point: null,
    form_data: { role_name: 'r', experience_min: 0, experience_max: 5, location: 'NYC', jd_text: null },
    questions_version: 'v1',
    questions_snapshot: [],
    prefilled_answers: null,
    current_answers: null,
    turns: [],
    process_stages: [],
    process_status: 'idle',
    process_error: null,
    interview_plan: null,
    created_at: 'x',
    updated_at: 'y',
  } as IntakeSession;
}

describe('IntakeSessionProvider fan-out — one shared source (FE-J5)', () => {
  test('every consumer reads the one shared session from context', async () => {
    render(
      <IntakeSessionContext.Provider value={ctxValue(sharedSession())}>
        <ContextConsumer tag="a" />
        <ContextConsumer tag="b" />
        <ContextConsumer tag="c" />
      </IntakeSessionContext.Provider>,
    );
    await waitFor(() => {
      expect(document.getElementById('consumer-a')?.textContent).toBe('ready');
      expect(document.getElementById('consumer-b')?.textContent).toBe('ready');
      expect(document.getElementById('consumer-c')?.textContent).toBe('ready');
    });
  });

  test('a context update propagates to every consumer at once', async () => {
    const { rerender } = render(
      <IntakeSessionContext.Provider value={ctxValue(null)}>
        <ContextConsumer tag="a" />
        <ContextConsumer tag="b" />
      </IntakeSessionContext.Provider>,
    );
    await waitFor(() => {
      expect(document.getElementById('consumer-a')?.textContent).toBe('none');
      expect(document.getElementById('consumer-b')?.textContent).toBe('none');
    });
    rerender(
      <IntakeSessionContext.Provider value={ctxValue(sharedSession())}>
        <ContextConsumer tag="a" />
        <ContextConsumer tag="b" />
      </IntakeSessionContext.Provider>,
    );
    await waitFor(() => {
      expect(document.getElementById('consumer-a')?.textContent).toBe('ready');
      expect(document.getElementById('consumer-b')?.textContent).toBe('ready');
    });
  });
});
