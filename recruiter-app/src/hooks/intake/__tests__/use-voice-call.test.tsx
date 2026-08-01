import { beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, renderHook } from '@testing-library/react';
import { useVoiceCall } from '@/hooks/intake/use-voice-call';
import { useIntakeStore } from '@/stores/intake-store';

// useVoiceCall is a THIN ADAPTER over IntakeCallProvider/useIntakeCall — the
// real WebRTC lifecycle lives in the provider (pipecat). The unit under test
// here is purely the adapter: how it maps call.status -> status, how it maps a
// thrown call.start() error -> voiceError.kind, and the mic/hangup pass-through.
// So we mock useIntakeCall with a controllable fake instead of mounting the
// real pipecat provider (which can't establish WebRTC in happy-dom and would
// always surface a generic 'WebRTC not supported' error, masking the very
// error-shape mapping these tests assert on).

interface FakeCall {
  status: 'idle' | 'connecting' | 'live' | 'paused' | 'ended';
  isMuted: boolean;
  start: (sessionId: string, meta: { role_name: string; status: string }) => Promise<void>;
  end: () => Promise<void>;
  toggleMute: () => void;
}

let fakeCall: FakeCall;

function makeFakeCall(overrides: Partial<FakeCall> = {}): FakeCall {
  return {
    status: 'idle',
    isMuted: false,
    start: mock(async function (this: FakeCall) {
      this.status = 'live';
    }),
    end: mock(async function (this: FakeCall) {
      this.status = 'ended';
    }),
    toggleMute: mock(function (this: FakeCall) {
      this.isMuted = !this.isMuted;
    }),
    ...overrides,
  };
}

mock.module('@/hooks/intake/use-intake-call', () => ({
  useIntakeCall: () => fakeCall,
}));

describe('useVoiceCall (thin adapter)', () => {
  beforeEach(() => {
    useIntakeStore.setState({ voiceError: null, hasLiveWebRTC: false });
    fakeCall = makeFakeCall();
  });

  it('initial status is idle', () => {
    const { result } = renderHook(() => useVoiceCall('sess-1'));
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('start() transitions to connecting or connected', async () => {
    // The provider drives status; the adapter just reflects it. Simulate the
    // provider flipping to 'live' while start resolves.
    fakeCall.start = mock(async () => {
      fakeCall.status = 'live';
    });
    const { result, rerender } = renderHook(() => useVoiceCall('sess-1'));
    await act(async () => {
      await result.current.start();
    });
    rerender();
    expect(['connecting', 'connected']).toContain(result.current.status);
  });

  it('start() sets voiceError on mic_denied (NotAllowedError)', async () => {
    const denied = new Error('Permission denied');
    denied.name = 'NotAllowedError';
    fakeCall.start = mock(async () => {
      throw denied;
    });
    const { result } = renderHook(() => useVoiceCall('sess-1'));
    await act(async () => {
      await result.current.start();
    });
    expect(useIntakeStore.getState().voiceError?.kind).toBe('mic_denied');
    expect(result.current.error).toBe('mic permission denied');
  });

  it('start() sets voiceError on 502 unreachable', async () => {
    fakeCall.start = mock(async () => {
      throw Object.assign(new Error('voice agent unreachable'), { status: 502 });
    });
    const { result } = renderHook(() => useVoiceCall('sess-1'));
    await act(async () => {
      await result.current.start();
    });
    expect(useIntakeStore.getState().voiceError?.kind).toBe('unreachable');
  });

  it('start() sets voiceError on 409 modality_conflict', async () => {
    fakeCall.start = mock(async () => {
      throw Object.assign(new Error('conflict'), { status: 409, code: 'modality_conflict' });
    });
    const { result } = renderHook(() => useVoiceCall('sess-1'));
    await act(async () => {
      await result.current.start();
    });
    expect(useIntakeStore.getState().voiceError?.kind).toBe('modality_conflict');
  });

  it('hangup() sets status=ended', async () => {
    fakeCall.end = mock(async () => {
      fakeCall.status = 'ended';
    });
    const { result, rerender } = renderHook(() => useVoiceCall('sess-1'));
    await act(async () => {
      result.current.hangup();
    });
    rerender();
    expect(result.current.status).toBe('ended');
  });

  it('toggleMic flips micEnabled', async () => {
    fakeCall.toggleMute = mock(() => {
      fakeCall.isMuted = !fakeCall.isMuted;
    });
    const { result, rerender } = renderHook(() => useVoiceCall('sess-1'));
    expect(result.current.micEnabled).toBe(true);
    act(() => {
      result.current.toggleMic();
    });
    rerender();
    expect(result.current.micEnabled).toBe(false);
    act(() => {
      result.current.toggleMic();
    });
    rerender();
    expect(result.current.micEnabled).toBe(true);
  });

  it('error clears on session change', async () => {
    fakeCall.start = mock(async () => {
      const denied = new Error('Permission denied');
      denied.name = 'NotAllowedError';
      throw denied;
    });
    const { result, rerender } = renderHook(({ id }: { id: string }) => useVoiceCall(id), {
      initialProps: { id: 'sess-1' },
    });
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.error).not.toBeNull();
    rerender({ id: 'sess-2' });
    await act(async () => {});
    expect(result.current.error).toBeNull();
  });
});
