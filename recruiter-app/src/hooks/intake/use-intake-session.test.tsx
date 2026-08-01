import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, render, renderHook, waitFor } from '@testing-library/react';
import { IntakeSessionProvider } from '@/components/sub-agents/intake/IntakeSessionProvider';
import type { IntakeSession } from '@/types/intake';

let registeredOnChange: ((s: IntakeSession) => void) | null = null;
let subscribeCalls = 0;
const unsubscribeMock = mock(() => {});

mock.module('@/lib/intake/realtime', () => ({
  subscribeIntakeSession: (opts: { onChange: (s: IntakeSession) => void }) => {
    subscribeCalls += 1;
    registeredOnChange = opts.onChange;
    return { unsubscribe: unsubscribeMock };
  },
}));

beforeEach(() => {
  registeredOnChange = null;
  subscribeCalls = 0;
  unsubscribeMock.mockClear();
});

function fakeSession(overrides: Partial<IntakeSession> = {}): IntakeSession {
  return {
    id: 'sess-1',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'created',
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
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
    ...overrides,
  };
}

describe('useIntakeSession', () => {
  test('returns null + isLoading=false when sessionId is null', async () => {
    const { useIntakeSession } = await import('./use-intake-session');
    const { result } = renderHook(() => useIntakeSession(null));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.session).toBeNull();
  });

  test('subscribes when sessionId is provided and updates on push', async () => {
    const { useIntakeSession } = await import('./use-intake-session');
    const { result } = renderHook(() => useIntakeSession('sess-1'));
    expect(registeredOnChange).not.toBeNull();
    act(() => registeredOnChange?.(fakeSession({ status: 'ready' })));
    await waitFor(() => expect(result.current.session?.status).toBe('ready'));
  });

  test('unsubscribes on unmount', async () => {
    const { useIntakeSession } = await import('./use-intake-session');
    const { unmount } = renderHook(() => useIntakeSession('sess-1'));
    unmount();
    expect(unsubscribeMock.mock.calls.length).toBe(1);
  });

  // FE-J5 fan-out: canvas + diff-panel + process-till-now used to each open their
  // own subscription. Under the IntakeSessionProvider, N consumers of the SAME
  // session id must collapse to ONE subscribeIntakeSession call.
  test('provider + 3 consumers open exactly ONE subscription', async () => {
    const { useIntakeSession } = await import('./use-intake-session');
    function Consumer({ tag }: { tag: string }) {
      const { session } = useIntakeSession('sess-1');
      return <div id={`fanout-${tag}`}>{session?.status ?? 'none'}</div>;
    }
    render(
      <IntakeSessionProvider sessionId="sess-1">
        <Consumer tag="a" />
        <Consumer tag="b" />
        <Consumer tag="c" />
      </IntakeSessionProvider>,
    );
    await waitFor(() => expect(subscribeCalls).toBeGreaterThan(0));
    expect(subscribeCalls).toBe(1);
  });
});
