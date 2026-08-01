import { describe, it, expect, beforeEach } from 'bun:test';
import { useIntakeStore } from '@/stores/intake-store';

describe('intake-store voice state (Phase 2)', () => {
  beforeEach(() => {
    useIntakeStore.setState({
      voiceError: null,
      hasLiveWebRTC: false,
      sessionId: null,
    });
  });

  it('setVoiceError sets the error', () => {
    useIntakeStore.getState().setVoiceError({ kind: 'mic_denied', message: 'permission denied' });
    expect(useIntakeStore.getState().voiceError?.kind).toBe('mic_denied');
  });

  it('clearVoiceError clears the error', () => {
    useIntakeStore.getState().setVoiceError({ kind: 'pc_failed', message: 'failed' });
    useIntakeStore.getState().clearVoiceError();
    expect(useIntakeStore.getState().voiceError).toBeNull();
  });

  it('setHasLiveWebRTC toggles the flag', () => {
    useIntakeStore.getState().setHasLiveWebRTC(true);
    expect(useIntakeStore.getState().hasLiveWebRTC).toBe(true);
    useIntakeStore.getState().setHasLiveWebRTC(false);
    expect(useIntakeStore.getState().hasLiveWebRTC).toBe(false);
  });

  it('setSessionId clears voiceError and hasLiveWebRTC', () => {
    useIntakeStore.getState().setVoiceError({ kind: 'unreachable', message: 'x' });
    useIntakeStore.getState().setHasLiveWebRTC(true);
    useIntakeStore.getState().setSessionId('new-sess-id');
    expect(useIntakeStore.getState().voiceError).toBeNull();
    expect(useIntakeStore.getState().hasLiveWebRTC).toBe(false);
  });
});
