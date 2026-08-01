"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  useRTVIClientEvent,
  usePipecatClientTransportState,
} from "@pipecat-ai/client-react";
import { RTVIEvent } from "@pipecat-ai/client-js";
import type { BotLLMTextData } from "@pipecat-ai/client-js";
import VoiceOrb from "./VoiceOrb";
import type { OrbState } from "./VoiceOrb";
import { useVoiceError } from "./VoiceProvider";

// Speech-to-text sometimes renders the agent's name phonetically. Only clearly
// non-word spellings are corrected: "Scott" and "scoot" are deliberately NOT in
// here, because rewriting a real name a candidate said would corrupt the
// transcript.
const STT_NAME_FIXUPS = /\b(?:skout|scowt|skowt|scaut|skaut)\b/gi;

export default function VoiceSession() {
  const [botMessages, setBotMessages] = useState<string[]>([]);
  const [botInterimText, setBotInterimText] = useState("");
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const transportState = usePipecatClientTransportState();
  const { error } = useVoiceError();
  const scrollRef = useRef<HTMLDivElement>(null);

  const isConnecting =
    transportState === "connecting" ||
    transportState === "initializing" ||
    transportState === "authenticating";

  const onUserStartedSpeaking = useCallback(() => setOrbState("listening"), []);
  const onUserStoppedSpeaking = useCallback(() => setOrbState("processing"), []);
  const onBotStartedSpeaking = useCallback(() => setOrbState("speaking"), []);
  const onBotStoppedSpeaking = useCallback(() => setOrbState("idle"), []);

  useRTVIClientEvent(RTVIEvent.UserStartedSpeaking, onUserStartedSpeaking);
  useRTVIClientEvent(RTVIEvent.UserStoppedSpeaking, onUserStoppedSpeaking);
  useRTVIClientEvent(RTVIEvent.BotStartedSpeaking, onBotStartedSpeaking);
  useRTVIClientEvent(RTVIEvent.BotStoppedSpeaking, onBotStoppedSpeaking);

  const handleBotLlmText = useCallback((data: BotLLMTextData) => {
    setBotInterimText((prev) => prev + data.text);
  }, []);

  const handleBotLlmStarted = useCallback(() => {
    setBotInterimText("");
  }, []);

  const handleBotLlmStopped = useCallback(() => {
    setBotInterimText((current) => {
      const cleaned = current
        .replace(/\[END\]/g, "")
        .replace(/\[interrupted[^\]]*\]/g, "")
        .replace(STT_NAME_FIXUPS, "Scout")
        .trim();
      if (cleaned) {
        setBotMessages((prev) => {
          if (prev.length > 0 && prev[prev.length - 1] === cleaned) {
            return prev;
          }
          return [...prev, cleaned];
        });
      }
      return "";
    });
  }, []);

  useRTVIClientEvent(RTVIEvent.BotLlmText, handleBotLlmText);
  useRTVIClientEvent(RTVIEvent.BotLlmStarted, handleBotLlmStarted);
  useRTVIClientEvent(RTVIEvent.BotLlmStopped, handleBotLlmStopped);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [botMessages, botInterimText]);

  return (
    <div id="voice-session-fullscreen" className="fixed inset-0 bg-[#090909] flex flex-col">
      <div className="relative flex-1 min-h-0">
        <VoiceOrb state={orbState} />

        {isConnecting && (
          <div id="voice-session-connecting" className="absolute inset-0 flex items-center justify-center z-10">
            <p className="text-gray-400 text-sm animate-pulse">Connecting...</p>
          </div>
        )}

        {error && (
          <div id="voice-session-error" className="absolute inset-0 flex items-center justify-center z-20 bg-[#090909]/80">
            <div className="flex flex-col items-center gap-3 px-6 py-4 rounded-xl bg-red-950/60 border border-red-800 max-w-sm text-center">
              <p className="text-red-300 text-sm">{error}</p>
              <p className="text-gray-400 text-xs animate-pulse">Attempting to reconnect...</p>
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 flex justify-center px-4 pb-3 bg-[#090909]">
        <div
          ref={scrollRef}
          id="voice-session-transcript-box"
          className="w-full max-w-xl rounded-xl border border-gray-700/50 bg-[#090909] px-6 py-5 overflow-y-auto scroll-smooth"
          style={{ height: "9.5rem" }}
        >
          {botMessages.length === 0 && !botInterimText ? (
            <p className="text-gray-500 text-base italic text-center mt-3">...</p>
          ) : (
            <div id="voice-session-transcript-flow" className="text-base italic leading-relaxed">
              {botMessages.map((msg, i) => (
                <span
                  key={i}
                  className={`transition-opacity duration-300 ${
                    i === botMessages.length - 1
                      ? "text-gray-200"
                      : "text-gray-400"
                  }`}
                >
                  {msg}{" "}
                </span>
              ))}
              {botInterimText && (
                <span className="text-gray-200">
                  {botInterimText.replace(/\[END\]/g, "").replace(/\[interrupted[^\]]*\]/g, "").replace(STT_NAME_FIXUPS, "Scout")}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
