import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, renderHook } from '@testing-library/react';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession } from '@/types/intake';
import { useSubmitIntake } from '../use-submit-intake';

// Mock fetch (NOT mock.module('@/lib/intake/api')) so we don't leak a module
// stub across files — test-setup.ts restores globalThis.fetch after every test.
// submitSession → request → intakeFetch → fetch, so counting POSTs to the submit
// endpoint is an accurate "how many submits fired" assertion.
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
    ...over,
  };
}

const initial = useIntakeStore.getState();

describe('useSubmitIntake — single in-flight guard (FE-J5)', () => {
  beforeEach(() => {
    useIntakeStore.setState(initial, true);
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });

  test('rapid double submit() results in exactly ONE submit network call', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useSubmitIntake(fakeSession()));
    await act(async () => {
      await Promise.all([result.current.submit(), result.current.submit()]);
    });
    expect(countSubmitCalls(fetchMock)).toBe(1);
  });

  test('two hook instances (canvas + wrapping) share ONE guard', async () => {
    let release: (() => void) | null = null;
    const fetchMock = mock(
      () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(submitOkResponse());
        }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const a = renderHook(() => useSubmitIntake(fakeSession()));
    const b = renderHook(() => useSubmitIntake(fakeSession()));
    await act(async () => {
      void a.result.current.submit();
      void b.result.current.submit();
      await Promise.resolve();
    });
    expect(countSubmitCalls(fetchMock)).toBe(1);
    await act(async () => {
      release?.();
      await Promise.resolve();
    });
  });

  test('a fresh submit is allowed after the prior one settles', async () => {
    const fetchMock = mock(async () => submitOkResponse());
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useSubmitIntake(fakeSession()));
    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      await result.current.submit();
    });
    expect(countSubmitCalls(fetchMock)).toBe(2);
  });
});
