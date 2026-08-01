'use client';

import { MessageSquare, Mic, MicOff, PhoneOff } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Waveform } from '@/components/sub-agents/intake/primitives';
import { useIntakeCall } from '@/hooks/intake/use-intake-call';
import { useModalitySwitch } from '@/hooks/intake/use-modality-switch';
import { useVoiceCall } from '@/hooks/intake/use-voice-call';
import { useIntakeStore } from '@/stores/intake-store';

export type VoicePhase = 'idle' | 'connecting' | 'live' | 'error';

interface Props {
  sessionId: string;
  hasTurns: boolean;
  /** Lifts the connect phase to the panel so it can dim the transcript + set the header status. */
  onPhase: (phase: VoicePhase) => void;
}

// Voice-only footer. Mounted ONLY in voice mode so the voice hooks never run
// (and never auto-connect) while the recruiter is chatting in text. Owns the
// call lifecycle, mic, end→handoff, and the no-turns voice→text fallback.
export function VoiceDock({ sessionId, hasTurns, onPhase }: Props) {
  const { status, error, start, micEnabled, toggleMic } = useVoiceCall(sessionId);
  const call = useIntakeCall();
  const { switchTo } = useModalitySwitch();
  const setPendingTransition = useIntakeStore((s) => s.setPendingTransition);
  const clearPendingTransition = useIntakeStore((s) => s.clearPendingTransition);
  const voiceError = useIntakeStore((s) => s.voiceError);
  const clearVoiceError = useIntakeStore((s) => s.clearVoiceError);

  const isConnecting = status === 'connecting' || status === 'requesting_mic';
  const isIdle = status === 'idle' || status === 'ended';
  const isErrorState = status === 'error' || voiceError !== null;
  // 'connected' covers both live and the heartbeat-only "paused" micro-state
  // (the mic stays live through it). The recruiter is in the call → show it live.
  const isConnected = status === 'connected';
  const phase: VoicePhase = isErrorState
    ? 'error'
    : isConnected
      ? 'live'
      : isConnecting
        ? 'connecting'
        : 'idle';

  useEffect(() => {
    onPhase(phase);
  }, [phase, onPhase]);

  // Auto-start on mount — entering voice mode is a fresh user gesture, so
  // getUserMedia is allowed.
  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (autoStartedRef.current || !sessionId) return;
    autoStartedRef.current = true;
    void start();
  }, [sessionId, start]);

  const handleSwitchToChat = async (): Promise<void> => {
    if (call.status === 'live' || call.status === 'paused') {
      // Optimistic flip so the canvas shows text mode immediately (no
      // voice_reconnect flash) while the switch request is in flight.
      setPendingTransition('text_active', 30_000);
      await call.end();
    }
    await switchTo('text');
    if (useIntakeStore.getState().switchError) clearPendingTransition();
  };

  // Voice-first with text fallback: if the call can't come up and we have no
  // turns yet, fall back to text instead of trapping the user on a dead screen.
  const fellBackRef = useRef<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-shot fallback guarded by ref; handleSwitchToChat is stable enough here
  useEffect(() => {
    if (!voiceError || voiceError.kind === 'modality_conflict') return;
    if (hasTurns) return;
    if (fellBackRef.current === sessionId) return;
    fellBackRef.current = sessionId;
    clearVoiceError();
    void handleSwitchToChat();
  }, [voiceError, sessionId, hasTurns, clearVoiceError]);

  return (
    <>
      {isErrorState ? (
        <>
          <div className="mz-conv-switch">
            <button
              id="v2-intake-voice-panel-switch-chat-btn"
              data-testid="v2-intake-voice-panel-switch-chat-btn"
              type="button"
              onClick={() => void handleSwitchToChat()}
              className="mz-btn-switch mz-btn-switch-sm"
            >
              <MessageSquare size={14} color="currentColor" />
              Switch to chat
            </button>
          </div>
          <div
            id="v2-intake-voice-panel-error"
            data-testid="v2-intake-voice-panel-error"
            className="rounded-md p-3 text-sm"
            style={{ background: 'var(--danger-bg)', color: 'var(--danger-fg)' }}
          >
            {voiceError?.message ?? error ?? 'something went wrong'}
          </div>
        </>
      ) : isConnecting ? (
        <div
          id="v2-intake-voice-panel-connecting"
          data-testid="v2-intake-voice-panel-connecting"
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}
        >
          <span
            className="mz-btn-switch"
            style={{ justifyContent: 'center', pointerEvents: 'none', opacity: 0.85 }}
          >
            <span
              className="mz-gather-mark"
              style={{
                width: 14,
                height: 14,
                borderColor: 'var(--cortex-500)',
                borderTopColor: 'transparent',
                animation: 'mz-spin 0.9s linear infinite',
              }}
            />
            Connecting voice…
          </span>
          <div
            style={{
              width: '60%',
              height: 4,
              borderRadius: 999,
              background: 'var(--surface-accent)',
              overflow: 'hidden',
            }}
          >
            <span
              style={{
                display: 'block',
                height: '100%',
                width: '45%',
                borderRadius: 999,
                background: 'var(--cortex-500)',
                animation: 'mz-spin 1.4s linear infinite',
              }}
            />
          </div>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Spinning up the voice line…
          </span>
        </div>
      ) : (
        <>
          <div className="mz-conv-switch">
            <button
              id="v2-intake-voice-panel-switch-chat-btn"
              data-testid="v2-intake-voice-panel-switch-chat-btn"
              type="button"
              onClick={() => void handleSwitchToChat()}
              className="mz-btn-switch mz-btn-switch-sm"
            >
              <MessageSquare size={14} color="currentColor" />
              Switch to chat
            </button>
          </div>
          {isIdle ? (
            <div className="mz-conv-voicefoot" style={{ justifyContent: 'center' }}>
              <button
                id="v2-intake-voice-panel-start-btn"
                data-testid="v2-intake-voice-panel-start-btn"
                type="button"
                onClick={() => void start()}
                className="mz-btn-switch"
                style={{ justifyContent: 'center' }}
              >
                Start call
              </button>
            </div>
          ) : (
            <div id="v2-intake-voice-panel-controls" className="mz-conv-voicefoot">
              <button
                id="v2-intake-voice-panel-mic-btn"
                data-testid="v2-intake-voice-panel-mic-btn"
                type="button"
                onClick={toggleMic}
                disabled={!isConnected}
                className={micEnabled ? 'mz-ctl' : 'mz-ctl mz-ctl-off'}
                aria-label={micEnabled ? 'Mute' : 'Unmute'}
              >
                {micEnabled ? <Mic size={18} /> : <MicOff size={18} />}
              </button>
              <div className="mz-conv-wave">
                <Waveform
                  bars={26}
                  active={isConnected && micEnabled}
                  height={18}
                  color="var(--cortex-500)"
                />
              </div>
              <button
                id="v2-intake-voice-panel-hangup-btn"
                data-testid="v2-intake-voice-panel-hangup-btn"
                type="button"
                onClick={() => void handleSwitchToChat()}
                className="mz-ctl mz-ctl-end"
                aria-label="End voice, continue in chat"
              >
                <PhoneOff size={18} />
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
