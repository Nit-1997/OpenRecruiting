import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { SessionListItem } from '@/types/intake';

const listMock = mock(async () => ({ sessions: [] as SessionListItem[] }));

// Spread `...actual` so we only override `listIntakeSessions`. A full
// replacement of `@/lib/intake/api` is process-wide in bun and DECOUPLES the
// module's internal bindings (e.g. the `IntakeApiError` class that the real
// functions `throw`), corrupting the genuine api.*.test.ts suites that run in
// the same process. Keeping the real exports avoids that cross-file damage.
mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, listIntakeSessions: listMock };
});

beforeEach(() => {
  listMock.mockClear();
  listMock.mockImplementation(async () => ({ sessions: [] }));
});

describe('useIntakeSessionsList', () => {
  test('loads sessions on mount', async () => {
    const fake: SessionListItem = {
      session_id: 's1',
      requisition_id: 'r1',
      title: 'Intake: BE',
      display_status: 'incomplete',
      detail_status: 'created',
      last_activity_at: '2026-05-28T00:00:00Z',
      active_modality: null,
      resume_url: '/intake/sessions/s1',
      covered: 0,
      total: 9,
      rounds_count: 0,
      total_minutes: 0,
      candidates_count: 0,
    };
    listMock.mockImplementation(async () => ({ sessions: [fake] }));
    const { useIntakeSessionsList } = await import('./use-intake-sessions-list');
    const { result } = renderHook(() => useIntakeSessionsList());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.sessions).toEqual([fake]);
    expect(result.current.error).toBeNull();
  });

  test('captures error on failure', async () => {
    listMock.mockImplementation(async () => {
      throw new Error('boom');
    });
    const { useIntakeSessionsList } = await import('./use-intake-sessions-list');
    const { result } = renderHook(() => useIntakeSessionsList());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.sessions).toEqual([]);
    expect(result.current.error).not.toBeNull();
  });

  test('refetch() reloads from the API', async () => {
    listMock.mockImplementation(async () => ({ sessions: [] }));
    const { useIntakeSessionsList } = await import('./use-intake-sessions-list');
    const { result } = renderHook(() => useIntakeSessionsList());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listMock.mock.calls.length).toBe(1);
    await act(async () => {
      await result.current.refetch();
    });
    expect(listMock.mock.calls.length).toBe(2);
  });
});
