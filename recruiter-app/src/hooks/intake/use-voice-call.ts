'use client';

import { useCallback, useEffect, useState } from 'react';
import { useIntakeStore } from '@/stores/intake-store';
import { useIntakeCall } from './use-intake-call';

export type VoiceCallStatus =
  | 'idle'
  | 'requesting_mic'
  | 'connecting'
  | 'connected'
  | 'ended'
  | 'error';

interface UseVoiceCallResult {
  status: VoiceCallStatus;
  error: string | null;
  start: () => Promise<void>;
  hangup: () => void;
  micEnabled: boolean;
  toggleMic: () => void;
  isLive: boolean;
}

/**
 * Backwards-compat adapter over IntakeCallProvider.
 * Old call sites receive the same surface; the actual WebRTC
 * lifecycle lives in the provider above the route tree.
 */
export function useVoiceCall(sessionId: string | null): UseVoiceCallResult {
  const call = useIntakeCall();
  const [error, setError] = useState<string | null>(null);
  const setVoiceError = useIntakeStore((s) => s.setVoiceError);
  const clearVoiceError = useIntakeStore((s) => s.clearVoiceError);

  const status: VoiceCallStatus =
    call.status === 'connecting'
      ? 'connecting'
      : call.status === 'live'
        ? 'connected'
        : call.status === 'paused'
          ? 'connected'
          : call.status === 'ended'
            ? 'ended'
            : 'idle';

  const start = useCallback(async (): Promise<void> => {
    if (!sessionId) {
      setError('no session id');
      return;
    }
    clearVoiceError();
    setError(null);
    try {
      await call.start(sessionId, { role_name: '', status: '' });
    } catch (e: unknown) {
      const err = e as {
        name?: string;
        status?: number;
        code?: string;
        detail?: string;
        message?: string;
      };
      const name = typeof err?.name === 'string' ? err.name : '';
      const httpStatus = typeof err?.status === 'number' ? err.status : null;
      const code = typeof err?.code === 'string' ? err.code : null;
      const detail = err?.detail ?? err?.message ?? 'connection failed';

      if (name === 'NotAllowedError' || name === 'NotFoundError') {
        setVoiceError({
          kind: 'mic_denied',
          message: 'mic permission denied — switch to chat to continue',
        });
        setError('mic permission denied');
        return;
      }
      if (httpStatus === 409 || code === 'modality_conflict') {
        setVoiceError({
          kind: 'modality_conflict',
          message: 'another mode is currently active — refresh and try again',
        });
      } else if (httpStatus === 502) {
        setVoiceError({
          kind: 'unreachable',
          message: 'voice unavailable — switch to chat to continue',
        });
      } else {
        setVoiceError({
          kind: 'pc_failed',
          message: e instanceof Error ? e.message : 'connection failed',
        });
      }
      setError(typeof detail === 'string' ? detail : 'connection failed');
    }
  }, [sessionId, call, clearVoiceError, setVoiceError]);

  const hangup = useCallback((): void => {
    void call.end();
  }, [call]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: sessionId is a prop; reset error when it changes
  useEffect(() => {
    setError(null);
  }, [sessionId]);

  return {
    status,
    error,
    start,
    hangup,
    micEnabled: !call.isMuted,
    toggleMic: call.toggleMute,
    isLive: call.status === 'live',
  };
}
