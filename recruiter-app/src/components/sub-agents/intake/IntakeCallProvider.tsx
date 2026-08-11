'use client';

import type { DeviceError, PipecatClient as PipecatClientType } from '@pipecat-ai/client-js';
import { PipecatClientAudio, PipecatClientProvider } from '@pipecat-ai/client-react';
import { createContext, type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { type AgentState, micShouldEnableOnResume } from '@/hooks/intake/voice-mic-policy';
import { postSessionHeartbeat } from '@/lib/intake/api';
import { trackIntake } from '@/lib/intake/telemetry';
import { useIntakeStore } from '@/stores/intake-store';
import { getRuntimeConfig } from '@/lib/runtime-config';

type CallStatus = 'idle' | 'connecting' | 'live' | 'paused' | 'ended';

export interface IntakeCallApi {
  status: CallStatus;
  agentState: AgentState;
  activeSessionId: string | null;
  pausedSessionMeta: { role_name: string; status: string } | null;
  pausedAt: number | null;
  isMuted: boolean;
  lastError: string | null;
  statusRef: { readonly current: CallStatus };
  start(sessionId: string, meta: { role_name: string; status: string }): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  end(): Promise<void>;
  toggleMute(): void;
}

export const IntakeCallContext = createContext<IntakeCallApi | null>(null);

const HEARTBEAT_LIVE_MS = 30_000;
const HEARTBEAT_PAUSED_MS = 60_000;
const ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
];

/**
 * Direct WebRTC offer URL for the v2 intake voice agent (voice-agent).
 * Mirrors recruiter-app v1's getIntakeOfferUrl — the pipecat SmallWebRTCTransport
 * connects straight to the agent (not through the backend), so it can do the
 * full SmallWebRTC handshake (offer + ICE-trickle PATCH). session_id rides in
 * the query string because the pipecat client only sends {sdp,type,pc_id}.
 */
function getV2IntakeOfferUrl(sessionId: string): string {
  const override = getRuntimeConfig().intakeVoiceOfferUrl;
  const base = (() => {
    if (override && override.length > 0) return override;
    if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      if (host === 'localhost' || host === '127.0.0.1') {
        return 'http://127.0.0.1:8011/v2/intake/offer';
      }
      // Anywhere else, assume a reverse proxy exposes the voice agent
      // under /voice-ws-v2 on this same origin.
      return `${window.location.protocol}//${host}/voice-ws-v2/v2/intake/offer`;
    }
    return 'http://127.0.0.1:8011/v2/intake/offer';
  })();
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}session_id=${encodeURIComponent(sessionId)}`;
}

export function IntakeCallProvider({ children }: { children: ReactNode }) {
  const clientRef = useRef<PipecatClientType | null>(null);
  const hbTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusRef = useRef<CallStatus>('idle');
  const intentionalEndRef = useRef(false);

  const [client, setClient] = useState<PipecatClientType | null>(null);
  const [status, setStatusState] = useState<CallStatus>('idle');
  const [agentState, setAgentState] = useState<AgentState>('listening');
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [pausedSessionMeta, setPausedSessionMeta] = useState<{
    role_name: string;
    status: string;
  } | null>(null);
  const [pausedAt, setPausedAt] = useState<number | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  // Mirror isMuted into a ref so resume() reads the LIVE mute intent without a
  // stale closure (resume is a stable useCallback that doesn't depend on isMuted).
  const isMutedRef = useRef(false);
  isMutedRef.current = isMuted;

  const setHasLiveWebRTC = useIntakeStore((s) => s.setHasLiveWebRTC);
  const setVoiceError = useIntakeStore((s) => s.setVoiceError);

  const setStatus = useCallback(
    (s: CallStatus): void => {
      statusRef.current = s;
      setStatusState(s);
      setHasLiveWebRTC(s === 'live');
    },
    [setHasLiveWebRTC],
  );

  const stopHeartbeat = useCallback((): void => {
    if (hbTimerRef.current) {
      clearInterval(hbTimerRef.current);
      hbTimerRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback(
    (sessionId: string, paused: boolean): void => {
      stopHeartbeat();
      const tick = async (): Promise<void> => {
        try {
          await postSessionHeartbeat(sessionId, paused);
        } catch {
          /* lock may have been released; UI reconciles via realtime */
        }
      };
      void tick();
      hbTimerRef.current = setInterval(tick, paused ? HEARTBEAT_PAUSED_MS : HEARTBEAT_LIVE_MS);
    },
    [stopHeartbeat],
  );

  const teardownClient = useCallback((): void => {
    stopHeartbeat();
    const c = clientRef.current;
    clientRef.current = null;
    if (c) {
      try {
        void c.disconnect();
      } catch {
        /* already gone */
      }
    }
    setClient(null);
  }, [stopHeartbeat]);

  const start = useCallback(
    async (sessionId: string, meta: { role_name: string; status: string }): Promise<void> => {
      if (statusRef.current === 'connecting' || statusRef.current === 'live') return;
      intentionalEndRef.current = false;
      setLastError(null);
      setStatus('connecting');
      setActiveSessionId(sessionId);
      setPausedSessionMeta(meta);

      const { PipecatClient } = await import('@pipecat-ai/client-js');
      const { SmallWebRTCTransport } = await import('@pipecat-ai/small-webrtc-transport');

      const transport = new SmallWebRTCTransport({ iceServers: ICE_SERVERS });
      const pc = new PipecatClient({
        transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            // Force the mic ON the moment we connect — exactly like v1's
            // IntakeVoiceProvider (which just connects with enableMic:true and
            // never touches it again). Without this, the agent's audio receiver
            // sat idle ("Disabling receiver for audio track ... idle") because
            // the mic track was never published / got disabled by the v2
            // pause/mute lifecycle → no inbound audio → no transcription.
            try {
              clientRef.current?.enableMic(true);
            } catch {
              /* no-op */
            }
            setStatus('live');
            setIsMuted(false);
            setAgentState('listening');
            startHeartbeat(sessionId, false);
            trackIntake('intake.session.opened', {
              session_id: sessionId,
              modality: 'voice',
              arrived_via: 'provider_start',
            });
          },
          // Wire the once-dead agentState off the real bot/user speaking signals.
          onBotStartedSpeaking: () => setAgentState('speaking'),
          onBotStoppedSpeaking: () => setAgentState('listening'),
          onBotLlmStarted: () => setAgentState('thinking'),
          onUserStartedSpeaking: () => setAgentState('listening'),
          onDisconnected: () => {
            // Intentional end (handoff/hangup) is handled by end(); only react
            // to unexpected drops so deriveStage can offer reconnect.
            if (intentionalEndRef.current) return;
            stopHeartbeat();
            setStatus('ended');
          },
          onError: (err) => {
            setLastError(typeof err === 'string' ? err : 'voice agent error');
            setVoiceError({ kind: 'pc_failed', message: 'voice connection failed' });
            // Tear down the dead peer connection and STOP the heartbeat. Without
            // this, the 30s heartbeat keeps firing against a session whose lock
            // gets cleared (drain / 5-min stale cleanup → active_modality=null),
            // producing a storm of 409 modality_lock_not_held. Mirrors the
            // connect-failure path below so the UI reconciles to 'ended'.
            teardownClient();
            setStatus('ended');
          },
          onDeviceError: (err: DeviceError) => {
            if (err.type === 'permissions') {
              setVoiceError({ kind: 'mic_denied', message: 'microphone permission denied' });
            } else {
              setVoiceError({
                kind: 'pc_failed',
                message: `microphone error: ${err.message || err.type}`,
              });
            }
          },
        },
      });

      clientRef.current = pc;
      setClient(pc);

      try {
        await pc.connect({ webrtcUrl: getV2IntakeOfferUrl(sessionId) });
      } catch (err) {
        const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
        setLastError(msg);
        setVoiceError({ kind: 'unreachable', message: 'voice agent unreachable' });
        teardownClient();
        setStatus('ended');
        throw err;
      }
    },
    [setStatus, startHeartbeat, stopHeartbeat, setVoiceError, teardownClient],
  );

  const pause = useCallback(async (): Promise<void> => {
    if (statusRef.current !== 'live' || !activeSessionId) return;
    // NOTE: do NOT disable the mic here. v1 has no pause concept and keeps the
    // mic live for the whole call. Auto-pause (canvas re-render / nav) was
    // killing the mic track mid-call → agent received no audio. Keep "pause"
    // purely a heartbeat/status hint; the WebRTC mic stays live.
    setStatus('paused');
    setPausedAt(performance.now());
    startHeartbeat(activeSessionId, true);
    trackIntake('intake.session.paused', { session_id: activeSessionId });
  }, [activeSessionId, startHeartbeat, setStatus]);

  const resume = useCallback(async (): Promise<void> => {
    if (statusRef.current !== 'paused' || !activeSessionId) return;
    // Honor the persisted mute intent — resuming must NOT silently un-mute a
    // recruiter who muted before pausing.
    try {
      clientRef.current?.enableMic(micShouldEnableOnResume(isMutedRef.current));
    } catch {
      /* no-op */
    }
    const duration = pausedAt != null ? performance.now() - pausedAt : 0;
    setStatus('live');
    setPausedAt(null);
    startHeartbeat(activeSessionId, false);
    trackIntake('intake.session.resumed', {
      session_id: activeSessionId,
      paused_for_ms: Math.round(duration),
    });
  }, [activeSessionId, pausedAt, startHeartbeat, setStatus]);

  const end = useCallback(async (): Promise<void> => {
    intentionalEndRef.current = true;
    teardownClient();
    setStatus('ended');
    setActiveSessionId(null);
    setPausedSessionMeta(null);
    setPausedAt(null);
    setIsMuted(false);
  }, [teardownClient, setStatus]);

  const toggleMute = useCallback((): void => {
    const next = !isMuted;
    try {
      clientRef.current?.enableMic(!next);
    } catch {
      /* no-op */
    }
    setIsMuted(next);
  }, [isMuted]);

  useEffect(() => {
    return () => {
      stopHeartbeat();
      const c = clientRef.current;
      clientRef.current = null;
      if (c) {
        try {
          void c.disconnect();
        } catch {
          /* already gone */
        }
      }
    };
  }, [stopHeartbeat]);

  const value: IntakeCallApi = {
    status,
    agentState,
    activeSessionId,
    pausedSessionMeta,
    pausedAt,
    isMuted,
    lastError,
    statusRef,
    start,
    pause,
    resume,
    end,
    toggleMute,
  };

  // {children} MUST render at a STABLE tree position regardless of `client`.
  // Nesting it inside the conditional PipecatClientProvider means flipping `client`
  // null↔non-null (start() → setClient(pc); end()/teardownClient()/onError →
  // setClient(null)) changes the tree shape and REMOUNTS the entire intake page —
  // the white flash on "Switch to chat" and the mid-call blink that drops an
  // in-flight transcript turn. The children consume only IntakeCallContext (not any
  // @pipecat-ai/client-react hook), so only PipecatClientAudio needs the
  // PipecatClientProvider — render it as a stable sibling, never wrapping children.
  // (Mirrors the same fix already shipped in feedback-call-provider.tsx.)
  return (
    <IntakeCallContext.Provider value={value}>
      {client ? (
        // Cast bridges a nominal type-skew between @pipecat-ai/client-js and the
        // copy of PipecatClient re-declared in @pipecat-ai/client-react — same
        // runtime instance, structurally identical.
        <PipecatClientProvider
          client={client as unknown as React.ComponentProps<typeof PipecatClientProvider>['client']}
        >
          <PipecatClientAudio />
        </PipecatClientProvider>
      ) : null}
      {children}
    </IntakeCallContext.Provider>
  );
}
