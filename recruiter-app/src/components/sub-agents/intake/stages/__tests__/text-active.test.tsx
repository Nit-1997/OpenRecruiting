import { describe, expect, it, mock } from 'bun:test';
import { render } from '@testing-library/react';
import type { IntakeSession } from '@/types/intake';
import { TextActiveStage } from '../text-active';

mock.module('@/hooks/intake/use-text-stream', () => ({
  useTextStream: () => ({
    status: 'idle',
    streamingText: '',
    error: null,
    lastDone: null,
    send: mock(),
    open: mock(async () => {}),
    cancel: mock(),
  }),
}));

mock.module('@/hooks/intake/use-manual-answer-edit', () => ({
  useManualAnswerEdit: () => ({
    savingQid: null,
    error: null,
    saveEdit: mock(),
    clearError: mock(),
  }),
}));

mock.module('@/hooks/intake/use-modality-switch', () => ({
  useModalitySwitch: () => ({ switchTo: mock(), isSwitching: null, clearSwitchError: mock() }),
}));

mock.module('@/hooks/intake/use-process-till-now', () => ({
  useProcessTillNow: () => ({
    runReprocess: mock(),
    dismissDiffPanel: mock(),
    isReprocessing: false,
  }),
}));

mock.module('@/lib/intake/api', () => {
  const a = require('@/lib/intake/api');
  return { ...a, endConversation: mock() };
});

const session: IntakeSession = {
  id: 'sess-1',
  requisition_id: 'r',
  user_id: 'u',
  organization_id: 'o',
  status: 'active',
  active_modality: 'text',
  entry_point: null,
  form_data: { role_name: 'X', experience_min: 1, experience_max: 2, location: '', jd_text: null },
  questions_version: 'v1',
  questions_snapshot: [],
  prefilled_answers: null,
  current_answers: null,
  turns: [],
  process_stages: [],
  process_status: 'idle',
  process_error: null,
  interview_plan: null,
  created_at: '',
  updated_at: '',
};

describe('TextActiveStage', () => {
  it('renders the 2-column centered layout: chat panel + coverage checklist', () => {
    render(<TextActiveStage session={session} />);
    expect(document.getElementById('v2-intake-stage-text-active')).not.toBeNull();
    expect(document.getElementById('v2-intake-stage-text-active-conv')).not.toBeNull();
    expect(document.getElementById('v2-intake-stage-text-active-hero')).not.toBeNull();
    expect(document.getElementById('v2-intake-coverage-table')).not.toBeNull();
    expect(document.getElementById('v2-intake-text-chat-panel')).not.toBeNull();
  });

  it('shows the Voice paused · chatting status and does NOT mount the live voice panel', () => {
    render(<TextActiveStage session={session} />);
    const status = document.getElementById('v2-intake-text-chat-panel-status');
    expect(status?.textContent).toContain('Voice paused');
    // VoiceCallPanel must NOT be mounted in text mode (it would auto-start a call).
    expect(document.getElementById('v2-intake-voice-panel')).toBeNull();
  });

  it('offers a Switch to voice control', () => {
    render(<TextActiveStage session={session} />);
    expect(
      document.getElementById('v2-intake-text-chat-panel-switch-voice-btn'),
    ).not.toBeNull();
  });
});
