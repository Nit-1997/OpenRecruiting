import { describe, it, expect, mock, beforeEach } from 'bun:test';
import { render, fireEvent, waitFor } from '@testing-library/react';

const useVoiceCallMock = mock(() => ({
  status: 'idle' as string,
  error: null as string | null,
  start: mock(),
  hangup: mock(),
  micEnabled: true,
  toggleMic: mock(),
  isLive: false,
}));
const switchModalityMock = mock();

mock.module('@/hooks/intake/use-voice-call', () => ({
  useVoiceCall: () => useVoiceCallMock(),
}));

mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, switchModality: switchModalityMock };
});

import { VoiceReconnectStage } from '@/components/sub-agents/intake/stages/voice-reconnect';
import { useIntakeStore } from '@/stores/intake-store';

const session = {
  id: 'sess-1', requisition_id: 'r', user_id: 'u', organization_id: 'o',
  status: 'active', active_modality: 'voice', entry_point: null,
  form_data: { role_name: 'x', experience_min: 1, experience_max: 2, location: 'NYC', jd_text: null },
  questions_version: '1', turns: [], current_answers: {}, prefilled_answers: null,
  questions_snapshot: [], process_stages: [], process_status: 'idle',
  process_error: null, interview_plan: null, created_at: '', updated_at: '',
} as any;

describe('VoiceReconnectStage', () => {
  beforeEach(() => {
    switchModalityMock.mockReset();
    useIntakeStore.setState({ pendingTransition: null });
  });

  it('renders modal with Rejoin + Switch-to-chat (both enabled in Phase 3)', () => {
    useVoiceCallMock.mockImplementation(() => ({
      status: 'idle', error: null, start: mock(), hangup: mock(), micEnabled: true, toggleMic: mock(), isLive: false,
    }));
    render(<VoiceReconnectStage session={session} />);
    expect(document.getElementById('v2-intake-voice-reconnect-modal')).not.toBeNull();
    expect(document.getElementById('v2-intake-voice-reconnect-rejoin-btn')).not.toBeNull();
    const switchBtn = document.getElementById('v2-intake-voice-reconnect-switch-btn') as HTMLButtonElement;
    expect(switchBtn).not.toBeNull();
    expect(switchBtn.disabled).toBe(false);
  });

  it('Rejoin triggers useVoiceCall.start', () => {
    const startMock = mock();
    useVoiceCallMock.mockImplementation(() => ({
      status: 'idle', error: null, start: startMock, hangup: mock(), micEnabled: true, toggleMic: mock(), isLive: false,
    }));
    render(<VoiceReconnectStage session={session} />);
    fireEvent.click(document.getElementById('v2-intake-voice-reconnect-rejoin-btn') as HTMLButtonElement);
    expect(startMock).toHaveBeenCalled();
  });

  it('Switch-to-chat happy path sets pendingTransition to text_active', async () => {
    switchModalityMock.mockResolvedValue({ active_modality: 'text' });
    render(<VoiceReconnectStage session={session} />);
    fireEvent.click(document.getElementById('v2-intake-voice-reconnect-switch-btn') as HTMLButtonElement);
    await waitFor(() => expect(useIntakeStore.getState().pendingTransition?.to).toBe('text_active'));
  });

  it('shows inline error on 502', async () => {
    const { IntakeApiError } = require('@/lib/intake/api');
    switchModalityMock.mockRejectedValue(new IntakeApiError(502, 'voice agent did not drain cleanly'));
    render(<VoiceReconnectStage session={session} />);
    fireEvent.click(document.getElementById('v2-intake-voice-reconnect-switch-btn') as HTMLButtonElement);
    await waitFor(() => {
      expect(document.getElementById('v2-intake-voice-reconnect-error')?.textContent ?? '').toContain('drain');
    });
  });
});
