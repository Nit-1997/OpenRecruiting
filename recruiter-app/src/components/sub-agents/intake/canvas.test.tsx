import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { render, waitFor } from '@testing-library/react';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession } from '@/types/intake';

let mockUseIntakeSession: () => {
  session: IntakeSession | null;
  isLoading: boolean;
  error: Error | null;
};
mock.module('@/hooks/intake/use-intake-session', () => ({
  useIntakeSession: () => mockUseIntakeSession(),
}));

mock.module('@/hooks/intake/use-intake-sessions-list', () => ({
  useIntakeSessionsList: () => ({
    sessions: [],
    isLoading: false,
    error: null,
    refetch: async () => {},
  }),
}));

// Use the REAL intake store (not a module mock). Its defaults (sessionId=null,
// no active modality, all flags false) are exactly the state these tests need,
// and the stage these tests assert is derived from the mocked session hook +
// the sessionId prop, not from store-specific values. We deliberately do NOT
// mock.module it: bun's mock.module is process-wide, so a stubbed store would
// leak into other intake test files — stripping the real setVoiceError/
// clearVoiceError behavior that use-voice-call's tests assert on. Reset in
// beforeEach so state another file left behind can't bleed in.
const intakeInitialState = useIntakeStore.getState();
beforeEach(() => {
  useIntakeStore.setState(intakeInitialState, true);
});

mock.module('@/hooks/intake/use-intake-call', () => ({
  useIntakeCall: () => ({
    status: 'idle' as const,
    agentState: 'listening' as const,
    activeSessionId: null,
    pausedSessionMeta: null,
    pausedAt: null,
    isMuted: false,
    statusRef: { current: 'idle' as const },
    start: async () => {},
    pause: async () => {},
    resume: async () => {},
    end: async () => {},
    toggleMute: () => {},
  }),
}));

function fakeSession(over: Partial<IntakeSession>): IntakeSession {
  return {
    id: 'sess-1',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'created',
    active_modality: null,
    entry_point: null,
    form_data: {
      role_name: 'r',
      experience_min: 0,
      experience_max: 5,
      location: 'NYC',
      jd_text: null,
    },
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
    ...over,
  };
}

import { IntakeCanvas } from './canvas';

describe('IntakeCanvas', () => {
  test('renders hub stage when sessionId prop is null', async () => {
    mockUseIntakeSession = () => ({ session: null, isLoading: false, error: null });
    render(<IntakeCanvas id="canvas" sessionId={null} />);
    await waitFor(() => expect(document.getElementById('canvas-stage-hub')).not.toBeNull());
  });

  test('renders prefilling stage when status=created', async () => {
    mockUseIntakeSession = () => ({
      session: fakeSession({ status: 'created' }),
      isLoading: false,
      error: null,
    });
    render(<IntakeCanvas id="canvas" sessionId="sess-1" />);
    await waitFor(() => expect(document.getElementById('canvas-stage-prefilling')).not.toBeNull());
  });

  test('renders prefill-failed when process_status=failed', async () => {
    mockUseIntakeSession = () => ({
      session: fakeSession({ status: 'prefilling', process_status: 'failed' }),
      isLoading: false,
      error: null,
    });
    render(<IntakeCanvas id="canvas" sessionId="sess-1" />);
    await waitFor(() =>
      expect(document.getElementById('canvas-stage-prefill-failed')).not.toBeNull(),
    );
  });

  test('renders error banner when hook surfaces error', async () => {
    mockUseIntakeSession = () => ({ session: null, isLoading: false, error: new Error('boom') });
    render(<IntakeCanvas id="canvas" sessionId="sess-1" />);
    await waitFor(() => {
      const banner = document.getElementById('canvas-error');
      expect(banner?.textContent ?? '').toContain('boom');
    });
  });

  test('renders loading skeleton when isLoading=true and no session yet', async () => {
    mockUseIntakeSession = () => ({ session: null, isLoading: true, error: null });
    render(<IntakeCanvas id="canvas" sessionId="sess-1" />);
    await waitFor(() => expect(document.getElementById('canvas-loading')).not.toBeNull());
  });
});
