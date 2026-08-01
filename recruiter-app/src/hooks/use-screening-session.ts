'use client';

// Per-tab storage for the candidate screening-session JWT. Mirrors
// use-feedback-session: key is `screening_session_${token}`, stored in
// sessionStorage (not localStorage — a screening link should not leak across
// tabs/sessions).

import { useCallback, useEffect, useState } from 'react';

function storageKey(token: string): string {
  return `screening_session_${token}`;
}

export function readScreeningSession(token: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage.getItem(storageKey(token));
  } catch {
    return null;
  }
}

export function writeScreeningSession(token: string, sessionToken: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(storageKey(token), sessionToken);
  } catch {
    /* sessionStorage unavailable (private mode) — caller still has the token in memory */
  }
}

export function clearScreeningSession(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(storageKey(token));
  } catch {
    /* ignore */
  }
}

/**
 * React binding for the screening session token. `sessionToken` is null until
 * read on mount (SSR-safe). `set`/`clear` keep storage and state in sync.
 */
export function useScreeningSession(token: string) {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSessionToken(readScreeningSession(token));
    setReady(true);
  }, [token]);

  const set = useCallback(
    (value: string) => {
      writeScreeningSession(token, value);
      setSessionToken(value);
    },
    [token],
  );

  const clear = useCallback(() => {
    clearScreeningSession(token);
    setSessionToken(null);
  }, [token]);

  return { sessionToken, ready, set, clear };
}
