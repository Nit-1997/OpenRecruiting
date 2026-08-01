import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';

import * as api from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import { ReprocessAlreadyRunningError, type IntakeSession } from '@/types/intake';
import { useProcessTillNow } from './use-process-till-now';

// Drive the underlying useIntakeSession by stubbing the realtime subscription.
// Mocking '@/hooks/intake/use-intake-session' directly leaks across files
// because mock.module is global in bun:test, so we go one layer deeper.
let pushSession: ((s: IntakeSession) => void) | null = null;
mock.module('@/lib/intake/realtime', () => ({
  subscribeIntakeSession: (opts: { onChange: (s: IntakeSession) => void }) => {
    pushSession = opts.onChange;
    return { unsubscribe: () => {} };
  },
}));

mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, reprocessSession: mock() };
});

const reprocessSessionMock = (api as unknown as { reprocessSession: ReturnType<typeof mock> })
  .reprocessSession;

function fakeSession(overrides: Partial<IntakeSession> = {}): IntakeSession {
  return {
    id: 'abc',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'created',
    active_modality: null,
    entry_point: null,
    form_data: { role_name: 'r', experience_min: 0, experience_max: 5, location: 'NYC', jd_text: null },
    questions_version: 'v1',
    questions_snapshot: [],
    prefilled_answers: {},
    current_answers: {},
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

const baseStoreState = () => ({
  sessionId: 'abc',
  processTillNowRunId: null,
  diffPanelOpen: false,
  diffBaseAnswers: null,
  reprocessError: null,
  pendingTransition: null,
  pendingModality: null,
  voiceError: null,
  hasLiveWebRTC: false,
  error: null,
  switchError: null,
});

async function pushAndWait(session: IntakeSession) {
  await act(async () => {
    pushSession?.(session);
    await Promise.resolve();
  });
}

describe('useProcessTillNow', () => {
  beforeEach(() => {
    reprocessSessionMock.mockReset();
    useIntakeStore.setState(baseStoreState());
    pushSession = null;
  });

  afterEach(() => {
    reprocessSessionMock.mockReset();
  });

  it('runReprocess posts and stores processTillNowRunId on 202', async () => {
    reprocessSessionMock.mockResolvedValue({ session_id: 'abc', process_run_id: 'run-1' });
    const { result } = renderHook(() => useProcessTillNow());
    await pushAndWait(fakeSession({ process_status: 'idle' }));
    await act(async () => {
      await result.current.runReprocess();
    });
    expect(useIntakeStore.getState().processTillNowRunId).toBe('run-1');
  });

  it('runReprocess on 409 sets reprocessError={type:"already_running"}', async () => {
    reprocessSessionMock.mockRejectedValue(
      new ReprocessAlreadyRunningError('Reprocess already running for this session.'),
    );
    const { result } = renderHook(() => useProcessTillNow());
    await pushAndWait(fakeSession({ process_status: 'idle' }));
    await act(async () => {
      await result.current.runReprocess();
    });
    expect(useIntakeStore.getState().reprocessError?.type).toBe('already_running');
    expect(useIntakeStore.getState().processTillNowRunId).toBeNull();
  });

  it('opens diff panel when process_status flips running → idle and run_id is set', async () => {
    reprocessSessionMock.mockResolvedValue({ session_id: 'abc', process_run_id: 'run-1' });
    const { result } = renderHook(() => useProcessTillNow());
    await pushAndWait(
      fakeSession({
        process_status: 'running',
        current_answers: { q1_role_overview: { text: 'old' } as any },
      }),
    );
    await act(async () => {
      await result.current.runReprocess();
    });
    await pushAndWait(
      fakeSession({
        process_status: 'idle',
        prefilled_answers: { q1_role_overview: { text: 'new suggestion' } as any },
        current_answers: { q1_role_overview: { text: 'old' } as any },
      }),
    );
    await waitFor(() => {
      expect(useIntakeStore.getState().diffPanelOpen).toBe(true);
    });
    expect(useIntakeStore.getState().diffBaseAnswers).toEqual({
      q1_role_overview: { text: 'old' },
    } as any);
  });

  it('does NOT open diff panel when process_status flips to idle but no run_id', async () => {
    renderHook(() => useProcessTillNow());
    await pushAndWait(fakeSession({ process_status: 'running' }));
    await pushAndWait(fakeSession({ process_status: 'idle' }));
    expect(useIntakeStore.getState().diffPanelOpen).toBe(false);
  });

  it('sets reprocessError={type:"lambda_failed"} when process_status flips to failed', async () => {
    reprocessSessionMock.mockResolvedValue({ session_id: 'abc', process_run_id: 'run-1' });
    const { result } = renderHook(() => useProcessTillNow());
    await pushAndWait(fakeSession({ process_status: 'running' }));
    await act(async () => {
      await result.current.runReprocess();
    });
    await pushAndWait(
      fakeSession({ process_status: 'failed', process_error: 'synthesize stage timed out' }),
    );
    await waitFor(() => {
      expect(useIntakeStore.getState().reprocessError?.type).toBe('lambda_failed');
    });
    expect(useIntakeStore.getState().diffPanelOpen).toBe(false);
    expect(useIntakeStore.getState().processTillNowRunId).toBeNull();
  });

  it('isReprocessing true while POST in flight OR process_status===running with run_id', async () => {
    reprocessSessionMock.mockResolvedValue({ session_id: 'abc', process_run_id: 'run-1' });
    const { result } = renderHook(() => useProcessTillNow());
    await pushAndWait(fakeSession({ process_status: 'running' }));
    await act(async () => {
      await result.current.runReprocess();
    });
    expect(result.current.isReprocessing).toBe(true);
  });

  it('dismissDiffPanel clears panel open + base snapshot + run_id', async () => {
    useIntakeStore.setState({
      ...baseStoreState(),
      diffPanelOpen: true,
      diffBaseAnswers: {
        q1_role_overview: {
          status: 'untouched',
          text: 'old',
          prefilled_text: null,
          extraction_confidence: 'none',
          sources: [],
          turns_addressed: [],
        },
      } as any,
      processTillNowRunId: 'run-1',
    });
    const { result } = renderHook(() => useProcessTillNow());
    act(() => {
      result.current.dismissDiffPanel();
    });
    const s = useIntakeStore.getState();
    expect(s.diffPanelOpen).toBe(false);
    expect(s.diffBaseAnswers).toBeNull();
    expect(s.processTillNowRunId).toBeNull();
  });
});
