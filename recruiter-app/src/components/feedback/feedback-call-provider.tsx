'use client';

import type {
  BotLLMTextData,
  DeviceError,
  PipecatClient as PipecatClientType,
  TranscriptData,
} from '@pipecat-ai/client-js';
import { PipecatClientAudio, PipecatClientProvider } from '@pipecat-ai/client-react';
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { appendBotTurn, appendUserTurn, type TranscriptTurn } from './feedback-transcript';

// WebRTC voice provider for the interviewer feedback portal. Cloned from the
// intake IntakeCallProvider but stripped of intake-only concerns (heartbeat,
// telemetry, intake-store, modality pause/resume). The browser connects
// DIRECTLY to the v2 voice agent (voice-agent, :8011) via the
// /voice-ws-v2 proxy — the same agent + proxy the intake flow uses — at the
// feedback offer path. The OpenRecruiting backend is not in this media path.

type CallStatus = 'idle' | 'connecting' | 'live' | 'ended';

export interface FeedbackCallApi {
  status: CallStatus;
  isMuted: boolean;
  lastError: string | null;
  statusRef: { readonly current: CallStatus };
  transcript: TranscriptTurn[];
  botInterim: string;
  start(voiceSessionToken: string): Promise<void>;
  end(): Promise<void>;
  toggleMute(): void;
}

const FeedbackCallContext = createContext<FeedbackCallApi | null>(null);

export function useFeedbackCall(): FeedbackCallApi {
  const ctx = useContext(FeedbackCallContext);
  if (!ctx) throw new Error('useFeedbackCall must be used within a FeedbackCallProvider');
  return ctx;
}

const ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
];

/**
 * Direct WebRTC offer URL for the v2 voice agent's FEEDBACK route
 * (`/api/offer/feedback/{voice_session_token}`). The token is a path segment
 * (not a query param) to match the agent route. Mirrors the intake offer-URL
 * resolution so prod/local hosts behave identically.
 */
function getFeedbackOfferUrl(voiceSessionToken: string): string {
  const override = process.env.NEXT_PUBLIC_FEEDBACK_VOICE_OFFER_URL;
  const base = (() => {
    if (override && override.length > 0) return override.replace(/\/$/, '');
    if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      if (host === 'localhost' || host === '127.0.0.1') {
        return 'http://127.0.0.1:8011/api/offer/feedback';
      }
      // Anywhere else, assume a reverse proxy exposes the voice agent
      // under /voice-ws-v2 on this same origin.
      return `${window.location.protocol}//${host}/voice-ws-v2/api/offer/feedback`;
    }
    return 'http://127.0.0.1:8011/api/offer/feedback';
  })();
  return `${base}/${encodeURIComponent(voiceSessionToken)}`;
}

export function FeedbackCallProvider({ children }: { children: ReactNode }) {
  const clientRef = useRef<PipecatClientType | null>(null);
  const statusRef = useRef<CallStatus>('idle');
  const intentionalEndRef = useRef(false);

  const [client, setClient] = useState<PipecatClientType | null>(null);
  const [status, setStatusState] = useState<CallStatus>('idle');
  const [isMuted, setIsMuted] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptTurn[]>([]);
  const [botInterim, setBotInterim] = useState('');
  const botInterimRef = useRef('');

  const setStatus = useCallback((s: CallStatus): void => {
    statusRef.current = s;
    setStatusState(s);
  }, []);

  const teardownClient = useCallback((): void => {
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
  }, []);

  const start = useCallback(
    async (voiceSessionToken: string): Promise<void> => {
      if (statusRef.current === 'connecting' || statusRef.current === 'live') return;
      intentionalEndRef.current = false;
      setLastError(null);
      setTranscript([]);
      setBotInterim('');
      botInterimRef.current = '';
      setStatus('connecting');

      const { PipecatClient } = await import('@pipecat-ai/client-js');
      const { SmallWebRTCTransport } = await import('@pipecat-ai/small-webrtc-transport');

      const transport = new SmallWebRTCTransport({ iceServers: ICE_SERVERS });
      const pc = new PipecatClient({
        transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            try {
              clientRef.current?.enableMic(true);
            } catch {
              /* no-op */
            }
            setStatus('live');
            setIsMuted(false);
          },
          onDisconnected: () => {
            // The agent ends the session when the scorecard is done, which drops
            // the transport. Treat any non-intentional drop while live as the
            // call finishing → the page transitions to processing.
            if (intentionalEndRef.current) return;
            setStatus('ended');
          },
          onError: (err) => {
            setLastError(typeof err === 'string' ? err : 'voice agent error');
            teardownClient();
            setStatus('ended');
          },
          onDeviceError: (err: DeviceError) => {
            setLastError(
              err.type === 'permissions'
                ? 'Microphone permission denied — enable it and try again.'
                : `Microphone error: ${err.message || err.type}`,
            );
          },
          onUserTranscript: (data: TranscriptData) => {
            if (!data.final) return;
            setTranscript((prev) => appendUserTurn(prev, data.text));
          },
          onBotLlmStarted: () => {
            botInterimRef.current = '';
            setBotInterim('');
          },
          onBotLlmText: (data: BotLLMTextData) => {
            botInterimRef.current += data.text;
            setBotInterim(botInterimRef.current);
          },
          onBotLlmStopped: () => {
            const finalText = botInterimRef.current;
            botInterimRef.current = '';
            setBotInterim('');
            setTranscript((prev) => appendBotTurn(prev, finalText));
          },
        },
      });

      clientRef.current = pc;
      setClient(pc);

      try {
        await pc.connect({ webrtcUrl: getFeedbackOfferUrl(voiceSessionToken) });
      } catch (err) {
        const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
        setLastError(msg);
        teardownClient();
        setStatus('ended');
        throw err;
      }
    },
    [setStatus, teardownClient],
  );

  const end = useCallback(async (): Promise<void> => {
    intentionalEndRef.current = true;
    teardownClient();
    setStatus('ended');
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
  }, []);

  const value: FeedbackCallApi = {
    status,
    isMuted,
    lastError,
    statusRef,
    transcript,
    botInterim,
    start,
    end,
    toggleMute,
  };

  // {children} MUST render at a STABLE tree position regardless of `client`.
  // If it were nested inside the conditional PipecatClientProvider, flipping
  // `client` from null -> non-null (which start() does mid-call via setClient)
  // would change the tree shape and REMOUNT the whole feedback page, wiping its
  // local `phase` state back to the intro/"Share feedback" screen while the call
  // keeps running. The children consume only FeedbackCallContext (not any
  // @pipecat-ai/client-react hook), so only PipecatClientAudio needs the
  // PipecatClientProvider — render it as a stable sibling, never wrapping children.
  return (
    <FeedbackCallContext.Provider value={value}>
      {client ? (
        <PipecatClientProvider
          client={client as unknown as React.ComponentProps<typeof PipecatClientProvider>['client']}
        >
          <PipecatClientAudio />
        </PipecatClientProvider>
      ) : null}
      {children}
    </FeedbackCallContext.Provider>
  );
}
