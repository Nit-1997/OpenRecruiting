"use client";

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  createContext,
  useContext,
  type ReactNode,
} from "react";
import type {
  PipecatClient as PipecatClientType,
  DeviceError,
} from "@pipecat-ai/client-js";
import { PipecatClientProvider, PipecatClientAudio } from "@pipecat-ai/client-react";
import { getOfferUrl, ICE_SERVERS } from "@/lib/pipecat";

interface VoiceErrorContextValue {
  error: string | null;
  clearError: () => void;
}

const VoiceErrorContext = createContext<VoiceErrorContextValue>({
  error: null,
  clearError: () => {},
});

export function useVoiceError() {
  return useContext(VoiceErrorContext);
}

interface VoiceProviderProps {
  children: ReactNode;
  sessionToken: string;
}

export default function VoiceProvider({ children, sessionToken }: VoiceProviderProps) {
  const [client, setClient] = useState<PipecatClientType | null>(null);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const shouldReconnectRef = useRef(true);
  const reconnectAttemptsRef = useRef(0);
  const hasConnectedOnceRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const MAX_RECONNECT_ATTEMPTS = 3;

  const clearError = useCallback(() => {
    setDeviceError(null);
  }, []);

  const pipecatModuleRef = useRef<typeof import("@pipecat-ai/client-js") | null>(null);
  const transportModuleRef = useRef<typeof import("@pipecat-ai/small-webrtc-transport") | null>(null);

  useEffect(() => {
    import("@pipecat-ai/client-js").then(mod => { pipecatModuleRef.current = mod; });
    import("@pipecat-ai/small-webrtc-transport").then(mod => { transportModuleRef.current = mod; });
  }, []);

  useEffect(() => {
    let mounted = true;

    async function createClient() {
      const clientMod = pipecatModuleRef.current ?? await import("@pipecat-ai/client-js");
      const transportMod = transportModuleRef.current ?? await import("@pipecat-ai/small-webrtc-transport");
      const { PipecatClient } = clientMod;
      const { SmallWebRTCTransport } = transportMod;

      const offerUrl = getOfferUrl(sessionToken);
      console.log("[VoiceProvider] Offer URL:", offerUrl);

      const transport = new SmallWebRTCTransport({
        iceServers: ICE_SERVERS,
      });

      const pipecatClient = new PipecatClient({
        transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            console.log("[VoiceProvider] Connected via WebRTC");
            hasConnectedOnceRef.current = true;
            reconnectAttemptsRef.current = 0;
          },
          onDisconnected: () => {
            console.log("[VoiceProvider] Disconnected");
            if (hasConnectedOnceRef.current) {
              console.log("[VoiceProvider] Session ended, not reconnecting");
              return;
            }
            if (shouldReconnectRef.current && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
              const attempt = reconnectAttemptsRef.current;
              const delay = Math.min(2000 * Math.pow(1.5, attempt), 30000);
              console.log(`[VoiceProvider] Reconnecting in ${delay}ms (attempt ${attempt + 1}/${MAX_RECONNECT_ATTEMPTS})`);
              reconnectTimerRef.current = setTimeout(async () => {
                reconnectAttemptsRef.current = attempt + 1;
                try {
                  await pipecatClient.connect({ webrtcUrl: offerUrl });
                } catch (err) {
                  console.error("[VoiceProvider] Reconnect failed:", err);
                }
              }, delay);
            } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
              console.log("[VoiceProvider] Max reconnect attempts reached, giving up");
            }
          },
          onBotReady: () => {
            console.log("[VoiceProvider] Bot ready");
          },
          onError: (error) => {
            console.error("[VoiceProvider] Error:", error);
          },
          onDeviceError: (error: DeviceError) => {
            console.error("[VoiceProvider] Device error:", error.type, error.message);
            if (error.type === "permissions") {
              setDeviceError(
                "Microphone permission denied. Please allow microphone access and try again."
              );
            } else if (error.type === "not-found") {
              setDeviceError(
                "No microphone found. Please connect a microphone and try again."
              );
            } else {
              setDeviceError(
                `Microphone error: ${error.message || error.type}`
              );
            }
          },
        },
      });

      if (mounted) {
        setClient(pipecatClient);
        try {
          await pipecatClient.connect({ webrtcUrl: offerUrl });
        } catch (err) {
          console.error("[VoiceProvider] Initial connect failed:", err);
        }
      }
    }

    createClient();

    return () => {
      mounted = false;
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [sessionToken]);

  if (!client) {
    return (
      <div id="voice-provider-loading" className="fixed inset-0 flex items-center justify-center bg-[#090909]">
        <p className="text-gray-400 text-sm">Initializing voice client...</p>
      </div>
    );
  }

  return (
    <VoiceErrorContext.Provider value={{ error: deviceError, clearError }}>
      <div id="voice-provider-root" className="contents">
        <PipecatClientProvider client={client}>
          <PipecatClientAudio />
          {children}
        </PipecatClientProvider>
      </div>
    </VoiceErrorContext.Provider>
  );
}
