"use client";

import { useState, useEffect, useRef, use } from "react";
import DormantView from "@/components/voice/DormantView";
import VoiceProvider from "@/components/voice/VoiceProvider";
import VoiceSession from "@/components/voice/VoiceSession";

interface SessionPageProps {
  params: Promise<{ sessionToken: string }>;
}

const STATUS_POLL_INTERVAL = 1000;

function getStatusUrl(sessionToken: string): string {
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      return `${base}/api/v2/public/voice/status/${sessionToken}`;
    }

    if (host.includes("localhost:3000")) {
      return `http://localhost:8004/api/v2/public/voice/status/${sessionToken}`;
    }

    return `${window.location.protocol}//${host}/api/v2/public/voice/status/${sessionToken}`;
  }
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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
