import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, renderHook } from '@testing-library/react';
import { useIntakeStore } from '@/stores/intake-store';
import type { CurrentAnswers, IntakeSession, QuestionSnapshot } from '@/types/intake';
import { useSubmitIntake } from '../use-submit-intake';

// Mock fetch (NOT the api module) — see use-submit-intake.test.tsx for why.
const ORIGINAL_FETCH = globalThis.fetch;

function submitOkResponse(): Response {
  return new Response(JSON.stringify({ session_id: 'sess-1', status: 'submitted' }), {
    status: 202,
    headers: { 'content-type': 'application/json' },
  });
}

function countSubmitCalls(fetchMock: ReturnType<typeof mock>): number {
  return fetchMock.mock.calls.filter((c) => String(c[0] ?? '').includes('/submit')).length;
}

const QS: QuestionSnapshot[] = [
  { id: 'q1_role_overview', prompt: 'p', category: 'c', required: true } as unknown as QuestionSnapshot,
];

function answers(status: string): CurrentAnswers {
  return {
    q1_role_overview: { status, text: 'x' } as unknown as CurrentAnswers['q1_role_overview'],
  } as CurrentAnswers;
}

function fakeSession(over: Partial<IntakeSession> = {}): IntakeSession {
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
    questions_snapshot: QS,
    prefilled_answers: null,
    current_answers: answers('validated'),
    turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'now' } as never],
    process_stages: [],
    process_status: 'idle',
    process_error: null,
    interview_plan: null,
    created_at: 'x',
    updated_at: 'y',
    ...over,
  };
}

const initial = useIntakeStore.getState();

describe('useSubmitIntake auto-submit — stable primitives (FE-J5)', () => {
  beforeEach(() => {
    useIntakeStore.setState(initial, true);
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });

  test('auto-submits once when all goals resolved and no live call', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderHook(() => useSubmitIntake(fakeSession(), { auto: true, hasLiveWebRTC: false }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(1);
  });

  test('does NOT re-fire on an unrelated session tick (updated_at change only)', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { rerender } = renderHook(
      ({ s }: { s: IntakeSession }) => useSubmitIntake(s, { auto: true, hasLiveWebRTC: false }),
      { initialProps: { s: fakeSession({ updated_at: 't1' }) } },
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(1);
    await act(async () => {
      rerender({ s: fakeSession({ updated_at: 't2' }) });
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(1);
  });

  test('does NOT auto-submit while a live WebRTC call is in progress', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderHook(() => useSubmitIntake(fakeSession(), { auto: true, hasLiveWebRTC: true }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(0);
  });

  test('does NOT auto-submit when goals are still open', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderHook(() =>
      useSubmitIntake(fakeSession({ current_answers: answers('untouched') }), {
        auto: true,
        hasLiveWebRTC: false,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(0);
  });

  // Regression: a failed submit rolls status back to 'ready'. Auto-submit must NOT
  // re-fire on that — otherwise the failed→ready→auto-resubmit→fail cycle becomes an
  // infinite plan-regeneration loop. A failed submit is a user-driven Retry.
  test('does NOT auto-submit when process_status=failed (no auto-retry loop)', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderHook(() =>
      useSubmitIntake(fakeSession({ status: 'ready', process_status: 'failed' }), {
        auto: true,
        hasLiveWebRTC: false,
      }),
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(0);
  });
});
