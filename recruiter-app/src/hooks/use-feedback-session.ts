'use client';

// Per-tab storage for the interviewer feedback-session JWT. Mirrors the v1
// portal: key is `feedback_session_${token}`, stored in sessionStorage (not
// localStorage — a feedback link should not leak across tabs/sessions).

import { useCallback, useEffect, useState } from 'react';

function storageKey(token: string): string {
  return `feedback_session_${token}`;
}

export function readFeedbackSession(token: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage.getItem(storageKey(token));
  } catch {
    return null;
  }
}

export function writeFeedbackSession(token: string, sessionToken: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(storageKey(token), sessionToken);
  } catch {
    /* sessionStorage unavailable (private mode) — caller still has the token in memory */
  }
}

export function clearFeedbackSession(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(storageKey(token));
  } catch {
    /* ignore */
  }
}

/**
 * React binding for the feedback session token. `sessionToken` is null until
 * read on mount (SSR-safe). `set`/`clear` keep storage and state in sync.
 */
export function useFeedbackSession(token: string) {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSessionToken(readFeedbackSession(token));
    setReady(true);
  }, [token]);

  const set = useCallback(
    (value: string) => {
      writeFeedbackSession(token, value);
      setSessionToken(value);
    },
    [token],
  );

  const clear = useCallback(() => {
    clearFeedbackSession(token);
    setSessionToken(null);
  }, [token]);

  return { sessionToken, ready, set, clear };
}
