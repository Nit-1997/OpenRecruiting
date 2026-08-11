"use client";

import { useState, useEffect, useRef, use } from "react";
import { getRuntimeConfig } from "@/lib/runtime-config";
import DormantView from "@/components/voice/DormantView";
import VoiceProvider from "@/components/voice/VoiceProvider";
import VoiceSession from "@/components/voice/VoiceSession";

interface SessionPageProps {
  params: Promise<{ sessionToken: string }>;
}

// The backend port. Was 8000 in two inline defaults, which is not where the
// backend listens; .env sets NEXT_PUBLIC_API_URL and now actually reaches here.
const DEFAULT_API_BASE = "http://localhost:8004";

const STATUS_POLL_INTERVAL = 1000;

function getStatusUrl(sessionToken: string): string {
  // The backend base comes from the runtime config, not process.env: this app
  // declared no build args, so NEXT_PUBLIC_API_URL was undefined in the bundle
  // and every read fell through to the default below. That default was port
  // 8000 while the backend listens on 8004, so local status polling reached
  // nothing at all. See src/lib/runtime-config.ts.
  //
  // A branch testing `hostname.includes("localhost:3000")` used to sit here and
  // was dead on arrival: `hostname` never contains a port (that is `host`).
  // Removed rather than fixed — the localhost case below already covers it.
  const base = getRuntimeConfig().apiUrl || DEFAULT_API_BASE;

  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    if (hostname !== "localhost" && hostname !== "127.0.0.1") {
      // Served from a real host (e.g. the tunnel the Recall bot loads): the
      // backend is reachable on the same origin.
      return `${window.location.protocol}//${window.location.host}/api/v2/public/voice/status/${sessionToken}`;
    }
  }
  return `${base}/api/v2/public/voice/status/${sessionToken}`;
}

export default function SessionPage({ params }: SessionPageProps) {
  const { sessionToken } = use(params);
  const [phase, setPhase] = useState<"dormant" | "active">("dormant");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const statusUrl = getStatusUrl(sessionToken);

    async function checkStatus() {
      try {
        const res = await fetch(statusUrl);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "activating" || data.status === "active") {
          setPhase("active");
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
        }
      } catch {
        // silently retry on network errors
      }
    }

    checkStatus();
    pollingRef.current = setInterval(checkStatus, STATUS_POLL_INTERVAL);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [sessionToken]);

  if (phase === "dormant") {
    return <DormantView />;
  }

  return (
    <main id="voice-session-page" className="h-screen w-screen overflow-hidden bg-[#090909]">
      <VoiceProvider sessionToken={sessionToken}>
        <VoiceSession />
      </VoiceProvider>
    </main>
  );
}
