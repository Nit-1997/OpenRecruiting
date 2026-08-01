export function getOfferUrl(sessionToken: string): string {
  // Recall-bot camera page → v2 voice agent (port 8011, Caddy /voice-ws-v2/*).
  // v1 (:8001 / /voice-ws) was retired 2026-06-01.
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return `http://localhost:8011/api/offer/${sessionToken}`;
    }

    if (host.includes("localhost:3000")) {
      return `http://localhost:8004/voice-ws-v2/api/offer/${sessionToken}`;
    }

    const protocol = window.location.protocol;
    return `${protocol}//${host}/voice-ws-v2/api/offer/${sessionToken}`;
  }
  return `http://localhost:8011/api/offer/${sessionToken}`;
}

export const ICE_SERVERS = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];
