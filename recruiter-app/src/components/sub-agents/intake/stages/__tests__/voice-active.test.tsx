import { describe, expect, it, mock } from 'bun:test';
import { render } from '@testing-library/react';
import { VoiceActiveStage } from '@/components/sub-agents/intake/stages/voice-active';

mock.module('@/hooks/intake/use-intake-call', () => ({
  useIntakeCall: () => ({
    status: 'live',
    agentState: 'listening',
    activeSessionId: 'sess-1',
    pausedSessionMeta: null,
    pausedAt: null,
    isMuted: false,
    lastError: null,
    start: mock(),
    pause: mock(),
    resume: mock(),
    end: mock(),
    toggleMute: mock(),
  }),
}));

mock.module('@/hooks/intake/use-voice-call', () => ({
  useVoiceCall: () => ({
    status: 'connected',
    error: null,
    start: mock(),
    hangup: mock(),
    micEnabled: true,
    toggleMic: mock(),
    isLive: true,
  }),
}));

// Use the real intake-store (zustand) — VoiceActiveStage only reads default
// values on render (voiceError=null, etc.). Mocking the store here previously
// leaked process-wide and broke sibling suites that rely on the real store.

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

const session = {
  id: 'sess-1',
  requisition_id: 'r',
  user_id: 'u',
  organization_id: 'o',
  status: 'active',
  active_modality: 'voice',
  entry_point: null,
  form_data: {
    role_name: 'x',
    experience_min: 1,
    experience_max: 2,
    location: 'NYC',
    jd_text: null,
  },
  questions_version: '1',
  turns: [{ idx: 0, role: 'assistant', content: 'Hi', modality: 'voice', timestamp: 'now' }],
  current_answers: { q1_role_overview: { status: 'needs_probe', text: null } },
  prefilled_answers: null,
  questions_snapshot: [
    {
      id: 'q1_role_overview',
      order: 1,
      topic: 'Role overview',
      default_text: 'Tell me about the role',
    },
  ],
  process_stages: [],
  process_status: 'idle',
  process_error: null,
  interview_plan: null,
  created_at: '',
  updated_at: '',
  // biome-ignore lint/suspicious/noExplicitAny: test fixture intentionally partial shape
} as any;

describe('VoiceActiveStage', () => {
  it('renders the 2-column centered layout: conversation panel + coverage checklist', () => {
    render(<VoiceActiveStage session={session} />);
    expect(document.getElementById('v2-intake-stage-voice-active')).not.toBeNull();
    expect(document.getElementById('v2-intake-stage-voice-active-conv')).not.toBeNull();
    expect(document.getElementById('v2-intake-stage-voice-active-hero')).not.toBeNull();
    expect(document.getElementById('v2-intake-voice-panel-orb')).not.toBeNull();
    expect(document.getElementById('v2-intake-coverage-table')).not.toBeNull();
    expect(document.getElementById('v2-intake-coverage-row-q1_role_overview')).not.toBeNull();
  });

  it('renders the running transcript inside the conversation panel', () => {
    render(<VoiceActiveStage session={session} />);
    const panel = document.getElementById('v2-intake-voice-panel');
    expect(panel).not.toBeNull();
    expect(document.getElementById('v2-intake-voice-panel-thread')).not.toBeNull();
  });
});
